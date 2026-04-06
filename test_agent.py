"""
test_agent.py — Interactive & Automated testing tool for SRE-Bench

3 modes:
  python test_agent.py manual        → YOU play the game step by step
  python test_agent.py auto          → Smart hardcoded agent plays all 3 tasks
  python test_agent.py stress        → Tests edge cases, penalties, wrong actions
  python test_agent.py manual --task disk_full|db_pool_exhausted|data_corruption
"""

import sys
import json
import os
sys.path.insert(0, '.')
sys.path.insert(0, './tasks')

from tasks import TASK_REGISTRY
from graders import grade_task
from environment import Action, CommandType

# ── colours for terminal ────────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BLUE   = "\033[94m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

COMMANDS = [c.value for c in CommandType]


# ── helpers ─────────────────────────────────────────────────────────────────

def print_header(text):
    print(f"\n{BOLD}{BLUE}{'='*60}{RESET}")
    print(f"{BOLD}{BLUE}  {text}{RESET}")
    print(f"{BOLD}{BLUE}{'='*60}{RESET}\n")

def print_obs(obs, step):
    print(f"{CYAN}{'─'*50}{RESET}")
    print(f"{BOLD}Step {step} | SLA remaining: {obs.sla_remaining}{RESET}")
    print(f"\n{BOLD}Services:{RESET}")
    for svc in obs.services:
        icon = f"{GREEN}●{RESET}" if svc.status == "healthy" else f"{RED}●{RESET}"
        print(f"  {icon} {svc.name:12} status={svc.status:10} "
              f"errors={svc.error_rate:.0%}  p99={svc.latency_p99_ms}ms")
    print(f"\n{BOLD}Terminal output:{RESET}")
    print(f"{obs.terminal_output}")
    if obs.last_command_error:
        print(f"{RED}Error: {obs.last_command_error}{RESET}")

def print_reward(reward, cumulative):
    color = GREEN if reward.value > 0 else (RED if reward.value < 0 else YELLOW)
    print(f"\n{color}{BOLD}Reward: {reward.value:+.2f}{RESET}  "
          f"(cumulative: {cumulative:.2f})")
    if reward.breakdown:
        for k, v in reward.breakdown.items():
            c = GREEN if v > 0 else RED
            print(f"  {c}{v:+.2f}  {k}{RESET}")

def print_final(score, task_id, steps):
    bar_len = int(score * 30)
    bar = f"{GREEN}{'█' * bar_len}{'░' * (30 - bar_len)}{RESET}"
    print(f"\n{BOLD}{'='*50}{RESET}")
    print(f"{BOLD}FINAL SCORE:  [{bar}]  {score:.3f} / 1.000{RESET}")
    print(f"Task: {task_id}  |  Steps used: {steps} / 15")
    if score >= 0.8:
        print(f"{GREEN}{BOLD}  EXCELLENT — full resolution!{RESET}")
    elif score >= 0.5:
        print(f"{YELLOW}{BOLD}  GOOD — partial resolution{RESET}")
    elif score > 0:
        print(f"{YELLOW}  PARTIAL — some progress made{RESET}")
    else:
        print(f"{RED}  FAILED — no progress or data destroyed{RESET}")
    print(f"{BOLD}{'='*50}{RESET}\n")


# ── MODE 1: Manual play ──────────────────────────────────────────────────────

def run_manual(task_id):
    print_header(f"MANUAL MODE — {task_id}")
    print("You are the on-call engineer. Type commands to investigate and fix the incident.")
    print(f"\n{BOLD}Available commands:{RESET}")
    for cmd in COMMANDS:
        print(f"  {CYAN}{cmd}{RESET}")
    print(f"\n{BOLD}How to enter a command:{RESET}")
    print("  Just type the command name and follow the prompts.")
    print("  Type  'hint'  for a nudge.  Type  'quit'  to exit.\n")

    env = TASK_REGISTRY[task_id]()
    obs = env.reset()
    cumulative = 0.0

    print(f"{BOLD}{RED}INCIDENT ALERT:{RESET} {obs.incident_description}\n")
    print_obs(obs, 0)

    while True:
        print()
        cmd_input = input(f"{BOLD}> Enter command: {RESET}").strip().lower()

        if cmd_input == "quit":
            break
        if cmd_input == "hint":
            _print_hint(task_id, env.state())
            continue
        if cmd_input == "state":
            print(json.dumps(env.state(), indent=2, default=str))
            continue
        if cmd_input not in COMMANDS:
            print(f"{RED}Unknown command. Choose from: {', '.join(COMMANDS)}{RESET}")
            continue

        params = _prompt_params(cmd_input)
        action = Action(command=cmd_input, params=params)

        obs, reward, done, info = env.step(action)
        cumulative += reward.value
        print_obs(obs, info['step'])
        print_reward(reward, cumulative)

        if done:
            score = grade_task(task_id, env.state())
            print_final(score, task_id, info['step'])
            break

    if not env._done:
        score = grade_task(task_id, env.state())
        print_final(score, task_id, env._step_count)


def _prompt_params(cmd):
    """Ask for the right params based on command type."""
    params = {}
    if cmd == "read_log":
        svc = input(f"  Which service log? {CYAN}(api / auth / orders / fulfillment / finance){RESET} → ").strip()
        params["service"] = svc
    elif cmd == "check_metrics":
        target = input(f"  Which target? {CYAN}(disk / api / database / auth / fulfillment / finance){RESET} → ").strip()
        params["target"] = target
    elif cmd == "run_diagnostic":
        dtype = input(f"  Diagnostic type? {CYAN}(deploy_history / leave blank for quick){RESET} → ").strip()
        params["type"] = dtype or "deploy_history"
    elif cmd == "apply_fix":
        fix_type = input(f"  Fix type? {CYAN}(e.g. delete_log / restart_auth_with_connection_cleanup / reprocess_affected_orders){RESET} → ").strip()
        params["fix_type"] = fix_type
        if fix_type in ("delete_log", "delete_file", "remove_file"):
            target = input(f"  Target file/path? → ").strip()
            params["target"] = target
        elif fix_type == "restart_service":
            svc = input(f"  Which service? → ").strip()
            params["service"] = svc
    elif cmd == "rollback":
        svc = input(f"  Which service to rollback? → ").strip()
        params["service"] = svc
    elif cmd == "restart_service":
        svc = input(f"  Which service to restart? → ").strip()
        params["service"] = svc
    return params


def _print_hint(task_id, state):
    hints = {
        "disk_full": [
            ("disk_checked", "Try: check_metrics → target: disk"),
            ("log_read",     "Try: read_log → service: app"),
            ("fix_applied",  "Use apply_fix → fix_type: delete_log, target: /var/log/app/app.log.2024-01-14"),
        ],
        "db_pool_exhausted": [
            ("api_log_read",      "Try: read_log → service: api"),
            ("db_metrics_checked","Try: check_metrics → target: database"),
            ("auth_log_read",     "Try: read_log → service: auth"),
            ("fix_applied",       "Use apply_fix → fix_type: restart_auth_with_connection_cleanup"),
        ],
        "data_corruption": [
            ("orders_log_read",      "Try: read_log → service: orders"),
            ("fulfillment_log_read", "Try: read_log → service: fulfillment"),
            ("finance_log_read",     "Try: read_log → service: finance"),
            ("deploy_checked",       "Try: run_diagnostic → type: deploy_history"),
            ("rollback_done",        "Try: rollback → service: orders"),
            ("reprocess_triggered",  "Try: apply_fix → fix_type: reprocess_affected_orders"),
        ],
    }
    for key, hint in hints.get(task_id, []):
        if not state.get(key):
            print(f"{YELLOW}Hint: {hint}{RESET}")
            return
    print(f"{GREEN}You've done everything! Just apply the final fix.{RESET}")


# ── MODE 2: Automated agent ──────────────────────────────────────────────────

OPTIMAL_SEQUENCES = {
    "disk_full": [
        Action(command=CommandType.CHECK_METRICS,   params={"target": "disk"}),
        Action(command=CommandType.READ_LOG,         params={"service": "app"}),
        Action(command=CommandType.APPLY_FIX,        params={"fix_type": "delete_log",
                                                              "target": "/var/log/app/app.log.2024-01-14"}),
    ],
    "db_pool_exhausted": [
        Action(command=CommandType.READ_LOG,         params={"service": "api"}),
        Action(command=CommandType.CHECK_METRICS,    params={"target": "database"}),
        Action(command=CommandType.READ_LOG,         params={"service": "auth"}),
        Action(command=CommandType.APPLY_FIX,        params={"fix_type": "restart_auth_with_connection_cleanup"}),
    ],
    "data_corruption": [
        Action(command=CommandType.READ_LOG,         params={"service": "orders"}),
        Action(command=CommandType.READ_LOG,         params={"service": "fulfillment"}),
        Action(command=CommandType.READ_LOG,         params={"service": "finance"}),
        Action(command=CommandType.RUN_DIAGNOSTIC,   params={"type": "deploy_history"}),
        Action(command=CommandType.ROLLBACK,         params={"service": "orders"}),
        Action(command=CommandType.APPLY_FIX,        params={"fix_type": "reprocess_affected_orders"}),
    ],
}

def run_auto():
    print_header("AUTO MODE — Optimal agent runs all 3 tasks")
    total_scores = []

    for task_id, actions in OPTIMAL_SEQUENCES.items():
        difficulty = {"disk_full": "EASY", "db_pool_exhausted": "MEDIUM", "data_corruption": "HARD"}[task_id]
        print(f"\n{BOLD}[{difficulty}] {task_id}{RESET}")
        print(f"{'─'*40}")

        env = TASK_REGISTRY[task_id]()
        obs = env.reset()
        print(f"Incident: {obs.incident_description[:80]}...")

        cumulative = 0.0
        for action in actions:
            obs, reward, done, info = env.step(action)
            cumulative += reward.value
            icon = f"{GREEN}✓{RESET}" if reward.value > 0 else f"{RED}✗{RESET}"
            print(f"  {icon} {action.command:22} reward={reward.value:+.2f}  "
                  f"done={str(done):5}  cumulative={cumulative:.2f}")
            if done:
                break

        score = grade_task(task_id, env.state())
        color = GREEN if score >= 0.8 else (YELLOW if score >= 0.5 else RED)
        print(f"  {color}{BOLD}Final grader score: {score:.3f}{RESET}")
        total_scores.append(score)

    avg = sum(total_scores) / len(total_scores)
    print(f"\n{BOLD}{'='*40}{RESET}")
    print(f"{BOLD}Average score across all tasks: {avg:.3f}{RESET}")
    bar_len = int(avg * 30)
    bar = f"{GREEN}{'█'*bar_len}{'░'*(30-bar_len)}{RESET}"
    print(f"[{bar}]")


# ── MODE 3: Stress / edge case testing ──────────────────────────────────────

def run_stress():
    print_header("STRESS TEST — Edge cases & penalty checks")
    results = []

    tests = [
        # (description, task_id, actions, expected_score_range)
        (
            "Wrong file deleted — should get partial then penalty",
            "disk_full",
            [
                Action(command=CommandType.CHECK_METRICS, params={"target": "disk"}),
                Action(command=CommandType.APPLY_FIX, params={"fix_type": "delete_log", "target": "wrong_file.log"}),
                Action(command=CommandType.READ_LOG, params={"service": "app"}),
                Action(command=CommandType.APPLY_FIX, params={"fix_type": "delete_log", "target": "/var/log/app/app.log.2024-01-14"}),
            ],
            (0.7, 1.0),
        ),
        (
            "Max steps hit without fix — should score partial",
            "disk_full",
            [Action(command=CommandType.CHECK_METRICS, params={"target": "api"})] * 15,
            (0.0, 0.3),
        ),
        (
            "Hard task: data wipe penalty should give 0.0",
            "data_corruption",
            [
                Action(command=CommandType.APPLY_FIX, params={"fix_type": "wipe_corrupted_orders"}),
            ],
            (0.0, 0.05),
        ),
        (
            "Hard task: partial — read logs but no rollback",
            "data_corruption",
            [
                Action(command=CommandType.READ_LOG, params={"service": "orders"}),
                Action(command=CommandType.READ_LOG, params={"service": "fulfillment"}),
                Action(command=CommandType.READ_LOG, params={"service": "finance"}),
            ],
            (0.15, 0.35),
        ),
        (
            "Medium task: fix without reading logs — should fail",
            "db_pool_exhausted",
            [
                Action(command=CommandType.APPLY_FIX,
                       params={"fix_type": "restart_auth_with_connection_cleanup"}),
            ],
            (0.0, 0.2),
        ),
        (
            "Escalate gives hints but no reward",
            "disk_full",
            [
                Action(command=CommandType.ESCALATE, params={}),
                Action(command=CommandType.CHECK_METRICS, params={"target": "disk"}),
                Action(command=CommandType.READ_LOG, params={"service": "app"}),
                Action(command=CommandType.APPLY_FIX,
                       params={"fix_type": "delete_log",
                               "target": "/var/log/app/app.log.2024-01-14"}),
            ],
            (0.8, 1.0),
        ),
    ]

    for desc, task_id, actions, (lo, hi) in tests:
        env = TASK_REGISTRY[task_id]()
        env.reset()
        for action in actions:
            _, _, done, _ = env.step(action)
            if done:
                break
        score = grade_task(task_id, env.state())
        passed = lo <= score <= hi
        icon = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
        print(f"  [{icon}]  {desc}")
        print(f"         score={score:.3f}  expected=[{lo:.2f}, {hi:.2f}]")
        results.append(passed)

    print(f"\n{BOLD}Results: {sum(results)}/{len(results)} tests passed{RESET}")
    if all(results):
        print(f"{GREEN}{BOLD}All stress tests passed!{RESET}")
    else:
        print(f"{RED}Some tests failed — check above.{RESET}")


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    task = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "--task" else None

    if mode == "manual":
        task_id = task or _pick_task()
        run_manual(task_id)
    elif mode == "auto":
        run_auto()
    elif mode == "stress":
        run_stress()
    else:
        print(f"Usage:")
        print(f"  python test_agent.py manual           → play yourself")
        print(f"  python test_agent.py manual --task disk_full")
        print(f"  python test_agent.py auto             → watch optimal agent")
        print(f"  python test_agent.py stress           → run edge case tests")


def _pick_task():
    print(f"\n{BOLD}Pick a task:{RESET}")
    tasks = list(TASK_REGISTRY.keys())
    for i, t in enumerate(tasks, 1):
        diff = ["Easy", "Medium", "Hard"][i-1]
        print(f"  {i}. {t}  ({diff})")
    choice = input("\nEnter number (1/2/3): ").strip()
    try:
        return tasks[int(choice) - 1]
    except:
        return tasks[0]


if __name__ == "__main__":
    main()
