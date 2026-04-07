"""
main.py — FastAPI wrapper exposing the OpenEnv API.
Endpoints: POST /reset, POST /step, GET /state, GET /health, GET /tasks
"""

from __future__ import annotations

import asyncio
import json as _json
import os
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

import gradio as gr
from environment import Action, Observation, Reward
from graders import grade_task
from tasks import TASK_REGISTRY

# --- Gradio UI Definition ---
def run_inference(task_id, hf_token, model_name, api_base):
    # This is a placeholder for the actual inference logic if needed by UI
    from inference import run_agent_on_task
    try:
        result = run_agent_on_task(task_id, hf_token, model_name, api_base)
        return result
    except Exception as e:
        return f"Error: {e}"

with gr.Blocks(title="SRE-Bench Dashboard") as demo:
    gr.Markdown("# 🛠️ SRE-Bench: Incident Response Environment")
    with gr.Tab("Status"):
        gr.Markdown("### Service Health")
        output_status = gr.Textbox(label="System Status", value="Waiting for agent...", interactive=False)
    with gr.Tab("Run Inference"):
        gr.Markdown("### Manually trigger agent inference")
        task_input = gr.Dropdown(choices=["disk_full", "db_pool_exhausted", "data_corruption"], label="Task ID", value="disk_full")
        token_input = gr.Textbox(label="HF Token (optional)", type="password")
        model_input = gr.Textbox(label="Model Name", value="gpt-4o")
        api_input = gr.Textbox(label="API Base URL", value="https://api.openai.com/v1")
        btn_infer = gr.Button("🚀 Run Agent")
        output_infer = gr.Textbox(label="Inference Logs", lines=10)
        btn_infer.click(run_inference, inputs=[task_input, token_input, model_input, api_input], outputs=output_infer)

app = FastAPI(
    title="SRE-Bench: Incident Response Environment",
    description=(
        "An OpenEnv where an AI agent acts as an on-call SRE. "
        "It reads logs, runs diagnostics, identifies root cause, "
        "and fixes production incidents through a simulated terminal API."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session: one env instance per session_id
_sessions: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ResetRequest(BaseModel):
    task_id: str = "disk_full"
    session_id: str = "default"


class StepRequest(BaseModel):
    action: Action
    session_id: str = "default"


class StepResponse(BaseModel):
    observation: Observation
    reward: Reward
    done: bool
    info: Dict[str, Any]
    final_score: Optional[float] = Field(0.01, ge=0.01, le=0.99)


class GradeRequest(BaseModel):
    session_id: str = "default"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

# Optimal demo sequences for the live dashboard
DEMO_SEQUENCES: Dict[str, list] = {
    "disk_full": [
        Action(command="check_metrics", params={"target": "disk"}),
        Action(command="read_log",      params={"service": "app"}),
        Action(command="apply_fix",     params={"fix_type": "delete_log", "target": "/var/log/app/app.log.2024-01-14"}),
    ],
    "db_pool_exhausted": [
        Action(command="read_log",      params={"service": "api"}),
        Action(command="check_metrics", params={"target": "database"}),
        Action(command="read_log",      params={"service": "auth"}),
        Action(command="apply_fix",     params={"fix_type": "restart_auth_with_connection_cleanup"}),
    ],
    "data_corruption": [
        Action(command="read_log",      params={"service": "orders"}),
        Action(command="read_log",      params={"service": "fulfillment"}),
        Action(command="read_log",      params={"service": "finance"}),
        Action(command="run_diagnostic",params={"type": "deploy_history"}),
        Action(command="rollback",      params={"service": "orders"}),
        Action(command="apply_fix",     params={"fix_type": "reprocess_affected_orders"}),
    ],
}


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return open("dashboard.html", encoding="utf-8").read()


@app.get("/stream-solve/{task_id}")
async def stream_solve(task_id: str, request: Request):
    if task_id not in TASK_REGISTRY:
        return {"error": f"Unknown task '{task_id}'"}

    async def generator():
        env = TASK_REGISTRY[task_id]()
        obs = env.reset()
        _sessions["demo"] = env
        yield f"data: {_json.dumps({'type': 'reset', 'obs': obs.model_dump()})}\n\n"

        for action in DEMO_SEQUENCES.get(task_id, []):
            await asyncio.sleep(1.5)
            if await request.is_disconnected():
                break
            obs, reward, done, info = env.step(action)
            payload = {
                "type": "step",
                "action": {"command": str(action.command), "params": action.params},
                "obs": obs.model_dump(),
                "reward": reward.model_dump(),
                "done": done,
                "info": {k: v for k, v in info.items() if isinstance(v, (int, float, str, bool, type(None)))},
            }
            yield f"data: {_json.dumps(payload)}\n\n"
            if done:
                break

        score = grade_task(task_id, env.state())
        # Global Safety Net: strict (0, 1)
        score = float(max(0.01, min(0.99, score)))
        yield f"data: {_json.dumps({'type': 'end', 'score': score})}\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
def health():
    return {"status": "ok", "env": "sre-bench", "version": "1.0.0"}


@app.get("/tasks")
def list_tasks():
    return {
        "tasks": [
            {
                "id": "disk_full",
                "difficulty": "easy",
                "description": "Disk 100% full — find the culprit file and free space to restore the API.",
            },
            {
                "id": "db_pool_exhausted",
                "difficulty": "medium",
                "description": "DB connection pool exhausted — trace auth service leak across 3 log sources and fix.",
            },
            {
                "id": "data_corruption",
                "difficulty": "hard",
                "description": (
                    "Silent data corruption from a serializer bug — "
                    "trace cascading failure across orders/fulfillment/finance, "
                    "rollback, and reprocess without data loss."
                ),
            },
        ]
    }


@app.post("/reset", response_model=Observation)
def reset(req: ResetRequest = ResetRequest()):
    if req.task_id not in TASK_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown task '{req.task_id}'. Valid: {list(TASK_REGISTRY.keys())}",
        )
    env = TASK_REGISTRY[req.task_id]()
    obs = env.reset()
    _sessions[req.session_id] = env
    return obs


@app.post("/step", response_model=StepResponse)
def step(req: StepRequest = None):
    if req is None:
        raise HTTPException(
            status_code=400,
            detail="Step request requires an 'action'. Example: {\"action\": {\"command\": \"read_log\", \"params\": {\"service\": \"api\"}}}",
        )
    env = _sessions.get(req.session_id)
    if env is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{req.session_id}' not found. Call /reset first.",
        )
    obs, reward, done, info = env.step(req.action)
    final_score = 0.01
    if done:
        final_score = env.state().get("cumulative_reward", 0.05)
        final_score = float(max(0.01, min(0.99, final_score)))
        info["final_score"] = final_score
        
    return StepResponse(
        observation=obs,
        reward=reward,
        done=done,
        info=info,
        final_score=final_score,
    )


@app.get("/state")
def get_state(session_id: str = "default"):
    env = _sessions.get(session_id)
    if env is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found. Call /reset first.",
        )
    return env.state()


@app.post("/grade")
def grade(req: GradeRequest = GradeRequest()):
    session_id = req.session_id
    env = _sessions.get(session_id)
    if env is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    score = grade_task(env.task_id, env.state())
    # Global Safety Net: strict (0, 1)
    eps = 0.01
    score = float(max(eps, min(0.99, score)))
    return {"task_id": env.task_id, "score": score}


# ---------------------------------------------------------------------------
# Mount Gradio UI
# ---------------------------------------------------------------------------
app = gr.mount_gradio_app(
    app, 
    demo, 
    path="/",
    # These parameters moved from Blocks to launch/mount in Gradio 6.0
)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=7860, workers=1)

if __name__ == "__main__":
    main()
