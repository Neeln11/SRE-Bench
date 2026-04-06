"""
app.py — Gradio UI for SRE-Bench.
Starts the FastAPI server in the background, then launches the Gradio interface.
"""
import os
import subprocess
import threading
import time

import gradio as gr
import requests

# ---------------------------------------------------------------------------
# Start the FastAPI backend in a background thread
# ---------------------------------------------------------------------------

def start_backend():
    subprocess.Popen(
        ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

def wait_for_backend(timeout=30):
    """Poll until the FastAPI server is ready."""
    for _ in range(timeout):
        try:
            r = requests.get("http://localhost:8000/health", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False

# Start backend once at import time
threading.Thread(target=start_backend, daemon=True).start()
wait_for_backend()

# ---------------------------------------------------------------------------
# Gradio action functions
# ---------------------------------------------------------------------------

def run_stress_test():
    env = os.environ.copy()
    env["SRE_BENCH_URL"] = "http://localhost:8000"
    try:
        result = subprocess.check_output(
            ["python", "test_agent.py", "stress"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=120,
            env=env,
        )
        return result
    except subprocess.CalledProcessError as e:
        return e.output
    except subprocess.TimeoutExpired:
        return "Timed out after 120 seconds."


def run_auto_agent():
    env = os.environ.copy()
    env["SRE_BENCH_URL"] = "http://localhost:8000"
    try:
        result = subprocess.check_output(
            ["python", "test_agent.py", "auto"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=300,
            env=env,
        )
        return result
    except subprocess.CalledProcessError as e:
        return e.output
    except subprocess.TimeoutExpired:
        return "Timed out after 300 seconds."


def run_inference():
    hf_token = os.getenv("HF_TOKEN", "")
    if not hf_token:
        return "⚠️  HF_TOKEN secret is not set. Please add it in Space Settings → Variables and secrets."
    env = os.environ.copy()
    env["HF_TOKEN"] = hf_token
    env["TASK_ID"] = os.getenv("TASK_ID", "disk_full")
    env["SRE_BENCH_URL"] = "http://localhost:8000"
    try:
        result = subprocess.check_output(
            ["python", "inference.py"],
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            timeout=300,
        )
        return result
    except subprocess.CalledProcessError as e:
        return e.output
    except subprocess.TimeoutExpired:
        return "Timed out after 300 seconds."


def get_health():
    try:
        r = requests.get("http://localhost:8000/health", timeout=5)
        tasks = requests.get("http://localhost:8000/tasks", timeout=5)
        return f"✅ Server status: {r.json()}\n\nAvailable tasks:\n{tasks.text}"
    except Exception as e:
        return f"❌ Server not responding: {e}"


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------

with gr.Blocks(title="SRE-Bench Agent", theme=gr.themes.Soft()) as demo:
    gr.Markdown("""
# 🚨 SRE-Bench: Incident Response Environment
An AI benchmark where agents act as on-call Site Reliability Engineers, diagnosing and fixing production incidents through a simulated terminal API.

**3 Tasks:** Disk Full (Easy) → DB Pool Exhausted (Medium) → Silent Data Corruption (Hard)
""")

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 🛠️ Actions")
            btn_health = gr.Button("🏥 Check Server Health", variant="secondary")
            btn_stress = gr.Button("🧪 Run Stress Tests (6/6)", variant="primary")
            btn_auto   = gr.Button("🤖 Run Optimal Agent (all tasks)", variant="primary")
            btn_infer  = gr.Button("🧠 Run LLM Inference Agent", variant="secondary")
            gr.Markdown("""
> **Note:** LLM Inference requires `HF_TOKEN` set in Space Secrets.
""")
        with gr.Column(scale=2):
            output = gr.Textbox(lines=30, label="Output", placeholder="Click a button to run...")

    btn_health.click(get_health, outputs=output)
    btn_stress.click(run_stress_test, outputs=output)
    btn_auto.click(run_auto_agent, outputs=output)
    btn_infer.click(run_inference, outputs=output)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)