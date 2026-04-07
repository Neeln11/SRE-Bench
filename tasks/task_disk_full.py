"""
Task 1 — EASY: Disk Full
Root cause: A 40GB rotated log file filling /var/log/app/.
Fix: identify the file via check_metrics(disk) + read_log(app) then apply_fix(delete_log).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from environment import Action, CommandType, IncidentEnv


INITIAL_SERVICES = [
    {"name": "api",      "status": "degraded", "error_rate": 0.45, "latency_p99_ms": 4200},
    {"name": "database", "status": "healthy",  "error_rate": 0.01, "latency_p99_ms": 120},
    {"name": "auth",     "status": "healthy",  "error_rate": 1e-5, "latency_p99_ms": 80},
]

DISK_METRICS = """\
=== Disk Usage (/var/log) ===
Filesystem      Size   Used  Avail  Use%  Mounted on
/dev/sda1       100G   99.8G  200M  100%  /
/dev/sda2       500G   210G   290G   42%  /data

Top consumers in /var/log/app:
  40G   /var/log/app/app.log.2024-01-14         <-- ANOMALY: oversized rotated log
  120M  /var/log/app/app.log
   80M  /var/log/app/error.log

ACTION HINT: Delete the anomalous file to free disk space.
  Example: apply_fix(fix_type=delete_log, target=/var/log/app/app.log.2024-01-14)
"""

APP_LOG_TAIL = """\
=== /var/log/app/app.log (last 50 lines) ===
[2024-01-15 03:12:01] INFO  Request processed in 120ms
[2024-01-15 03:12:02] ERROR No space left on device — write failed
[2024-01-15 03:12:02] ERROR Failed to write session data: OSError(28, 'No space left on device')
[2024-01-15 03:12:03] ERROR No space left on device — write failed
[2024-01-15 03:12:03] WARN  API response queue backing up (size=1842)
[2024-01-15 03:12:04] ERROR Failed to write session data: OSError(28, 'No space left on device')
...
Root rotated log /var/log/app/app.log.2024-01-14 was never compressed (logrotate misconfiguration).
"""

API_METRICS = """\
=== API Service Metrics ===
p50 latency:  180ms   (baseline: 150ms)
p99 latency:  4200ms  (baseline: 300ms)  [ALERT]
Error rate:   45.2%   (baseline: <1%)    [ALERT]
Throughput:   120 rps (baseline: 800 rps)
Cause pattern: write timeouts -> session failures -> request queuing
"""


class DiskFullEnv(IncidentEnv):

    TASK_ID = "disk_full"

    def __init__(self):
        super().__init__(self.TASK_ID)

    def _build_initial_state(self) -> Dict[str, Any]:
        return {
            "incident_description": (
                "ALERT: API service degraded. Error rate 45%, p99 latency 4.2s. "
                "Started ~10 minutes ago. No recent deploys."
            ),
            "services": [s.copy() for s in INITIAL_SERVICES],
            "root_cause": "disk_full",
            "culprit_file": "/var/log/app/app.log.2024-01-14",
            "disk_checked": False,
            "log_read": False,
            "correct_file_identified": False,
            "fix_applied": False,
            "resolved": False,
            "data_destroyed": False,
            "wrong_fix_attempted": False,
        }

    def _execute_command(self, action: Action) -> Tuple[str, Optional[str]]:
        cmd = action.command
        params = action.params
        state = self._state

        if cmd == CommandType.CHECK_METRICS:
            target = params.get("target", "")
            if target == "disk":
                state["disk_checked"] = True
                return DISK_METRICS, None
            elif target == "api":
                return API_METRICS, None
            else:
                return f"Available targets: disk, api, database, auth", None

        elif cmd == CommandType.READ_LOG:
            service = params.get("service", "")
            if service == "app":
                state["log_read"] = True
                return APP_LOG_TAIL, None
            else:
                return f"No log found for service '{service}'. Try: app, error, auth", None

        elif cmd == CommandType.APPLY_FIX:
            fix_type = params.get("fix_type", "")
            target   = params.get("target", "")

            # Accept several natural fix_type variants an LLM might use
            is_delete_fix = fix_type in (
                "delete_log", "delete_file", "remove_file", "clear_log",
                "delete_old_log", "remove_log", "free_disk", "clear_disk_space",
            )
            # Accept full path, filename, or date-based match
            is_correct_target = (
                "app.log.2024-01-14" in target
                or target.strip("/").endswith("app.log.2024-01-14")
            )

            if is_delete_fix and is_correct_target:
                state["correct_file_identified"] = True
                state["fix_applied"] = True
                state["resolved"] = True
                for svc in state["services"]:
                    if svc["name"] == "api":
                        svc["status"] = "healthy"
                        svc["error_rate"] = 0.01
                        svc["latency_p99_ms"] = 160
                return (
                    "rm /var/log/app/app.log.2024-01-14\n"
                    "Freed 40GB. Disk usage: 60%\n"
                    "[OK] API service recovered. Error rate: 0.8%  p99: 160ms"
                ), None

            elif is_delete_fix and target:
                state["wrong_fix_attempted"] = True
                return (
                    f"Deleted {target} — disk usage barely changed. Service still degraded.\n"
                    "Hint: the 40GB file listed in check_metrics(disk) is the culprit."
                ), None

            elif fix_type in ("restart_service", "restart"):
                state["wrong_fix_attempted"] = True
                return "API restarted but disk still full — service degraded again within 30s.", None

            else:
                return (
                    f"Unknown fix_type '{fix_type}'.\n"
                    "To fix a disk-full issue use: fix_type=delete_log, target=<filename>\n"
                    "Example: {\"fix_type\": \"delete_log\", \"target\": \"/var/log/app/app.log.2024-01-14\"}"
                ), None

        elif cmd == CommandType.RESTART_SERVICE:
            state["wrong_fix_attempted"] = True
            return "Service restarted. Disk still at 100%. Service degraded again in 20s.", None

        elif cmd == CommandType.RUN_DIAGNOSTIC:
            return (
                "=== Quick Diagnostic ===\n"
                "CPU: 12%  MEM: 48%  DISK: 100% [CRITICAL]\n"
                "Network: normal  DB connections: 45/100\n"
                "Hint: disk pressure is causing write failures."
            ), None

        elif cmd == CommandType.ROLLBACK:
            state["wrong_fix_attempted"] = True
            return "No recent deployments to rollback. Disk issue persists.", None

        elif cmd == CommandType.ESCALATE:
            return "Escalated to senior SRE. They ask: have you checked disk usage?", None

        return "Unknown command.", f"Command '{cmd}' not recognised."

    def _compute_reward(
        self, action: Action, terminal_output: str
    ) -> Tuple[float, Dict[str, float]]:
        state  = self._state
        cmd    = action.command
        params = action.params
        breakdown: Dict[str, float] = {}
        reward = 1e-5

        if cmd == CommandType.CHECK_METRICS and params.get("target") == "disk":
            if not state.get("_disk_reward_given"):
                breakdown["correct_diagnostic"] = 0.10
                reward += 0.10
                state["_disk_reward_given"] = True

        if cmd == CommandType.READ_LOG and params.get("service") == "app":
            if not state.get("_log_reward_given"):
                breakdown["read_relevant_log"] = 0.10
                reward += 0.10
                state["_log_reward_given"] = True

        if state.get("resolved") and not state.get("_fix_reward_given"):
            breakdown["root_cause_identified"] = 0.30
            breakdown["correct_fix_applied"]   = 0.30
            breakdown["service_recovered"]     = 0.20
            reward += 0.80
            state["_fix_reward_given"] = True
            if self._step_count <= 5:
                breakdown["sla_bonus"] = 0.05
                reward += 0.05

        if state.get("wrong_fix_attempted") and not state.get("_wrong_penalty_given"):
            breakdown["wrong_fix_penalty"] = -0.05
            reward -= 0.05
            state["_wrong_penalty_given"] = True

        return reward, breakdown
