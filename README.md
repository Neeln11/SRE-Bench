---
title: SRE-Bench Incident Response Environment
emoji: 🚨
colorFrom: red
colorTo: red
sdk: docker
pinned: false
tags:
  - openenv
  - sre
  - incident-response
  - rl-environment
  - agent-evaluation
---

# 🚨 SRE-Bench: Incident Response Environment

An **OpenEnv** environment where an AI agent acts as an on-call Site Reliability Engineer. The agent is presented with a live production incident and must read logs, run diagnostics, identify the root cause, and apply the correct fix — all through a structured terminal API.

---

## 🎯 Why This Environment Matters

Every tech company has engineers on call 24/7. When a production database goes down at 3 AM, you can't just ask a standard chatbot to "fix it." Before engineering teams will trust AI to act as an Autonomous SRE, they need a safe, sandboxed way to prove the AI won't accidentally wipe customer data while trying to solve an outage.

**SRE-Bench provides that exact proving ground.**

---

## 💻 Why a Text-Based "Chat" Interface?

You might wonder why the agent interacts via JSON commands (`read_log`, `check_metrics`) instead of a traditional UI. This is intentional:

- **Real Engineers use Terminals:** When humans debug a server, they SSH into a terminal, run `htop`, check `tail -f logs`, and run bash scripts.
- **Tool Use:** By giving the LLM a strict text-based API, we force it to interact with systems exactly like a real engineer using CLI tools.
- **Reasoning Loop:** The agent must observe the terminal output, "think" (chain-of-thought) about what it means, and decide on the next logical command. This evaluates true agentic reasoning capabilities.

---

## 🚀 The Ultimate Goal: Level 2 On-Call Automation

The core value of systems like this is **burnout prevention**. Currently, if a disk fills up, a human gets paged in the middle of the night. With agents proven by SRE-Bench, the future workflow becomes:

> PagerDuty triggers the AI Agent → The Agent reads the logs and finds the huge file → The Agent deletes it and restarts the API → The Agent messages Slack: *"Hey, the disk filled up at 3 AM. I cleared out the old logs and the system is green. Go back to sleep."*

---

## 🖥️ Interactive Web Interfaces

SRE-Bench comes with two beautiful Frontend UIs to visualize the benchmark:

1. **The Gradio Control Panel (`http://localhost:7860`)**: A polished hub to manually trigger health checks, mass-execute stress tests, or launch inference agents with a single click.
2. **The Live Action Dashboard (`http://localhost:8000/`)**: A sleek, animated terminal UI (inspired by dark-mode IDEs) where you can watch the AI agent's reasoning, command-execution, and the real-time health of microservices play out visually.

---

## 🌍 Environment Description

The agent interacts with a simulated production system consisting of multiple services (API, database, auth, fulfillment, finance). Each episode presents a different incident. The agent must:

- Observe the incident alert and current service health
- Run diagnostic commands to gather information
- Identify the root cause
- Apply the correct, targeted fix
- Verify that services recover

> **The key challenge:** the root cause is never obvious from a single source. Medium and hard tasks require correlating information across multiple logs before any fix will work.

---

## ⚡ Action Space

| Command | Description | Example params |
|---|---|---|
| `read_log` | Read service logs | `{"service": "api"}` |
| `check_metrics` | Check service/infra metrics | `{"target": "disk"}` |
| `run_diagnostic` | Run a diagnostic query | `{"type": "deploy_history"}` |
| `apply_fix` | Apply a remediation | `{"fix_type": "delete_log", "target": "/var/log/app/app.log.2024-01-14"}` |
| `rollback` | Roll back a service | `{"service": "orders"}` |
| `restart_service` | Restart a service | `{"service": "auth"}` |
| `escalate` | Get a hint from senior SRE | `{}` |

---

## 👁️ Observation Space

| Field | Type | Description |
|---|---|---|
| `terminal_output` | string | Output from the last command |
| `services` | list | Service health objects: name, status, error_rate, latency_p99_ms |
| `step` | int | Current step (max 15) |
| `sla_remaining` | int | Steps before SLA breach (SLA bonus if resolved within 12) |
| `incident_description` | string | The initial PagerDuty-style alert |
| `last_command_error` | string\|null | Error if command was invalid |

---

## 📋 Tasks

### Task 1 — Disk Full *(Easy)*
- **Incident:** API service degraded — 45% error rate, 4.2s p99 latency.
- **Root cause:** A 40GB rotated log file that was never compressed has filled `/var/log` to 100%.
- **What the agent must do:** `check_metrics(disk)` → `read_log(app)` → `apply_fix(delete_log, correct_file)`.
- **Why it's easy:** Single root cause, 2–3 commands, linear reasoning.

### Task 2 — DB Connection Pool Exhausted *(Medium)*
- **Incident:** API p99 = 8.1s, error rate 38%. Started gradually 50 minutes ago.
- **Root cause:** Auth service leaks a DB connection on every failed login. After 50 minutes, all 50 pool connections are held by auth, blocking everything else.
- **What the agent must do:** Read API log + DB metrics + auth log, correlate the connection ownership data, then apply `restart_auth_with_connection_cleanup`. The fix does nothing if the agent hasn't read at least 2 sources.
- **Why it's medium:** Root cause is invisible in any single log — requires multi-source correlation.

### Task 3 — Silent Data Corruption *(Hard)*
- **Incident:** Low-priority ticket: finance reports ~180 duplicate invoices. No service errors. No latency alerts.
- **Root cause:** A deploy 45 minutes ago changed the orders service serializer to `json_v2`, which silently replaces unrecognised characters with `?`. Orders writes corrupt `item_id` fields → fulfillment silently drops those rows → finance double-bills on retry.
- **What the agent must do:** Read orders + fulfillment + finance logs, check deploy history, rollback the config change, then trigger reprocess — without wiping the orders table (which incurs -0.50 penalty).
- **Why it's hard:** No single log shows the full picture. The orders service appears healthy. The agent must connect 4 separate data sources, understand causality, and apply a two-step fix in the right order.

---

## 🏆 Reward Function

```
Per step:
  +0.05-0.10   Running correct diagnostic commands
  +0.07-0.10   Reading relevant logs (each source)
  +0.20-0.30   Identifying root cause
  +0.20-0.30   Applying correct fix
  +0.20        Service health fully restored
  +0.05        SLA bonus (fast resolution)

Penalties:
  -0.05        Wrong fix attempted (no data loss)
  -0.30        Destructive action on wrong target
  -0.50        Permanent data loss (hard task)
```

All rewards are bounded strictly within `(0.0, 1.0)` — exclusive of both endpoints.

---

## 🔌 API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/tasks` | List all tasks |
| POST | `/reset` | Start a new episode |
| POST | `/step` | Execute one action |
| GET | `/state` | Get full internal state |
| POST | `/grade` | Get final grader score |

### Example Usage

```python
import requests

# Start episode
obs = requests.post("https://neel-110-sre-bench-env.hf.space/reset",
    json={"task_id": "disk_full", "session_id": "test"}).json()

# Take a step
result = requests.post("https://neel-110-sre-bench-env.hf.space/step", json={
    "action": {"command": "check_metrics", "params": {"target": "disk"}},
    "session_id": "test"
}).json()

print(result["observation"]["terminal_output"])
print(result["reward"])
```

---

## 🛠️ Setup & Running Locally

```bash
# Clone and install
git clone https://github.com/Neeln11/SRE-Bench
cd SRE-Bench
pip install -r requirements.txt

# Run the environment server (FastAPI) AND the Gradio Web UI
python app.py

# (Optional) Run the inference script manually
set HF_TOKEN=your_token
set API_BASE_URL=https://router.huggingface.co/v1
set MODEL_NAME=Qwen/Qwen2.5-72B-Instruct
python inference.py
```

### Docker

```bash
docker build -t sre-bench .
docker run -p 7860:7860 \
  -e HF_TOKEN=your_token \
  -e API_BASE_URL=https://router.huggingface.co/v1 \
  -e MODEL_NAME=Qwen/Qwen2.5-72B-Instruct \
  sre-bench
```

---

## 📊 Baseline Scores

Scores obtained with `Qwen/Qwen2.5-72B-Instruct` via HuggingFace router:

| Task | Difficulty | Baseline Score |
|---|---|---|
| disk_full | Easy | ~0.90 |
| db_pool_exhausted | Medium | ~0.85 |
| data_corruption | Hard | ~0.25 |

The hard task score of ~0.25 demonstrates meaningful difficulty progression — the agent typically identifies the orders log anomaly but fails to trace the full chain and applies a wrong fix.

---

## 🔧 Environment Variables

| Variable | Required | Description |
|---|---|---|
| `HF_TOKEN` | Yes | HuggingFace / API key for inference |
| `API_BASE_URL` | Yes | LLM endpoint URL |
| `MODEL_NAME` | Yes | Model identifier |
| `SRE_BENCH_URL` | No | Environment URL (default: http://localhost:7860) |
| `TASK_ID` | No | Task to run: `all`, `disk_full`, `db_pool_exhausted`, `data_corruption` |
