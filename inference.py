"""
inference.py — Baseline inference script for SRE-Bench.

Mandatory format:
  [START] task=<task_id> env=sre-bench model=<model>
  [STEP]  step=<n> action=<json> reward=<0.00> done=<true|false> error=<msg|null>
  [END]   success=<true|false> steps=<n> rewards=<r1,r2,...>

Environment variables:
  API_BASE_URL  — LLM endpoint  (default: https://router.huggingface.co/v1)
  MODEL_NAME    — model string  (default: Qwen/Qwen2.5-72B-Instruct)
  HF_TOKEN      — API key
  SRE_BENCH_URL — environment URL (default: http://localhost:7860)
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from typing import List, Optional

import re
import requests
from openai import OpenAI

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Configuration (Strictly pulled from platform environment)
# ---------------------------------------------------------------------------

API_BASE_URL  = os.environ.get("API_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "https://router.huggingface.co/v1"
API_KEY       = os.environ.get("API_KEY")      or os.environ.get("HF_TOKEN")       or os.environ.get("OPENAI_API_KEY")
MODEL_NAME    = os.environ.get("MODEL_NAME")   or "Qwen/Qwen2.5-72B-Instruct"
ENV_BASE_URL  = os.getenv("SRE_BENCH_URL")      or "http://localhost:7860"

MAX_STEPS         = 15
SUCCESS_THRESHOLD = 0.5
TEMPERATURE       = 0.2
MAX_TOKENS        = 512

TASKS = ["disk_full", "db_pool_exhausted", "data_corruption"]

# Strict check for proxy variables (Fail-fast if the platform hasn't injected them)
if not API_KEY:
    print("  [CRITICAL] Missing API_KEY! Check platform environment injection.", flush=True)

client = OpenAI(base_url=API_BASE_URL, api_key=API_KEY)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = textwrap.dedent("""
You are an expert on-call Site Reliability Engineer (SRE). A production incident
has been detected. Diagnose and fix it as quickly as possible.

AVAILABLE COMMANDS — respond with ONLY valid JSON, no explanation, no markdown:

  {"command": "read_log",        "params": {"service": "api"}}
  {"command": "check_metrics",   "params": {"target": "disk"}}
  {"command": "run_diagnostic",  "params": {"type": "deploy_history"}}
  {"command": "apply_fix",       "params": {"fix_type": "delete_log", "target": "/var/log/app/app.log.2024-01-14"}}
  {"command": "rollback",        "params": {"service": "orders"}}
  {"command": "restart_service", "params": {"service": "auth"}}
  {"command": "escalate",        "params": {}}

Valid services: api, auth, orders, fulfillment, finance, database
Valid targets:  disk, api, database, auth, payments, fulfillment, finance

DIAGNOSIS STRATEGY:
1. Start: check_metrics(target=disk) for infra issues, then read_log for error patterns.
2. Connection issues: check db metrics to see which service owns connections.
3. Data/deploy issues: run_diagnostic(type=deploy_history).
4. Only apply_fix AFTER understanding root cause from at least 2 sources.

FIX REFERENCE:
- Disk full:       {"fix_type": "delete_log", "target": "<exact path from disk metrics ANOMALY>"}
- Connection leak: {"fix_type": "restart_auth_with_connection_cleanup"}
- Bad deploy:      rollback first, then {"fix_type": "reprocess_affected_orders"}

PENALTIES: wrong fix -0.05 | wrong delete -0.30 | data wipe -0.50 (NEVER do this)

OUTPUT: One JSON object only. No markdown. No explanation.
""").strip()


# ---------------------------------------------------------------------------
# Environment client helpers
# ---------------------------------------------------------------------------

def env_reset(task_id: str, session_id: str) -> dict:
    r = requests.post(
        f"{ENV_BASE_URL}/reset",
        json={"task_id": task_id, "session_id": session_id},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def env_step(action: dict, session_id: str) -> dict:
    r = requests.post(
        f"{ENV_BASE_URL}/step",
        json={"action": action, "session_id": session_id},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Agent: call LLM, parse JSON action
# ---------------------------------------------------------------------------

def get_action(conversation: List[dict]) -> Optional[dict]:
    content = ""
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=conversation,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
        )
        content = response.choices[0].message.content.strip()
        
        # 1. Try finding a JSON block anywhere in the text using regex
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            # 2. Fallback: extract substring from first { to last }
            start = content.find('{')
            end = content.rfind('}')
            if start != -1 and end != -1:
                json_str = content[start:end+1]
            else:
                json_str = content
                
        return json.loads(json_str)
    except Exception as e:
        print(f"  [DEBUG] LLM parse error: {e}. Raw: {content[:100]}...", flush=True)
        return {"command": "escalate", "params": {}}


# ---------------------------------------------------------------------------
# Run one task episode
# ---------------------------------------------------------------------------

def run_task(task_id: str) -> None:
    session_id = f"inference_{task_id}"
    rewards: List[str] = []
    step = 0
    done = False
    final_score = 0.01

    print(f"[START] task={task_id} env=sre-bench model={MODEL_NAME}", flush=True)

    try:
        # Reset environment
        obs = env_reset(task_id, session_id)
        incident = obs.get("incident_description", "")
        services_str = json.dumps(obs.get("services", []), indent=2)

        # Initialise conversation
        conversation = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"INCIDENT: {incident}\n\n"
                    f"CURRENT SERVICES:\n{services_str}\n\n"
                    f"SLA remaining: {obs.get('sla_remaining', 12)} steps\n"
                    "What is your first action?"
                ),
            },
        ]

        while not done and step < MAX_STEPS:
            action_dict = get_action(conversation)
            action_str  = json.dumps(action_dict)

            try:
                result      = env_step(action_dict, session_id)
                reward_val  = result["reward"]["value"]
                done        = result["done"]
                terminal    = result["observation"]["terminal_output"]
                error       = result["observation"].get("last_command_error")
                raw         = result.get("final_score")
                final_score = float(max(0.01, min(0.99, raw))) if raw is not None else 0.01
                step += 1

                rewards.append(f"{reward_val:.6f}")
                error_str = error if error else "null"
                print(
                    f"[STEP] step={step} action={action_str} "
                    f"reward={reward_val:.6f} done={'true' if done else 'false'} "
                    f"error={error_str}",
                    flush=True,
                )

                # Update conversation
                conversation.append({"role": "assistant", "content": action_str})
                sla = result["observation"].get("sla_remaining", 0)
                services_str = json.dumps(
                    result["observation"].get("services", []), indent=2
                )
                next_msg = (
                    f"Terminal output:\n{terminal}\n\n"
                    f"Services:\n{services_str}\n\n"
                    f"Step: {step}/{MAX_STEPS}  SLA remaining: {sla}\n"
                    f"Cumulative reward: {result['info'].get('cumulative_reward', 1e-5):.6f}\n"
                )
                if done:
                    next_msg += f"\nEpisode finished. Final score: {final_score:.6f}"
                else:
                    next_msg += "\nWhat is your next action?"
                conversation.append({"role": "user", "content": next_msg})

            except Exception as e:
                step += 1
                rewards.append("0.000010")
                print(
                    f"[STEP] step={step} action={action_str} "
                    f"reward=0.000010 done=false error={str(e)}",
                    flush=True,
                )

        success = final_score >= SUCCESS_THRESHOLD
        print(
            f"[END] success={'true' if success else 'false'} "
            f"steps={step} score={final_score:.6f} rewards={','.join(rewards)}",
            flush=True,
        )

    except Exception as e:
        final_score = 0.01
        default_rew = ",".join(["0.010000"] * max(1, step))
        print(
            f"[END] success=false steps={step} score={final_score:.6f} rewards={default_rew}",
            flush=True,
        )
        raise


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    task_arg = os.getenv("TASK_ID", "all")

    if task_arg == "all":
        for t in TASKS:
            run_task(t)
            print("", flush=True)  # blank line between tasks
    elif task_arg in TASKS:
        run_task(task_arg)
    else:
        print(f"Unknown TASK_ID '{task_arg}'. Options: all, {', '.join(TASKS)}")
        sys.exit(1)
