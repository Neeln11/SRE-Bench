"""
Task 2 — MEDIUM: DB Connection Pool Exhausted
Root cause: auth service leaks DB connections on failed logins.
Fix requires correlating 3 log sources before the fix command works.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from environment import Action, CommandType, IncidentEnv


INITIAL_SERVICES = [
    {"name": "api",      "status": "degraded", "error_rate": 0.38, "latency_p99_ms": 8100},
    {"name": "database", "status": "degraded", "error_rate": 0.12, "latency_p99_ms": 950},
    {"name": "auth",     "status": "healthy",  "error_rate": 0.02, "latency_p99_ms": 95},
    {"name": "payments", "status": "healthy",  "error_rate": 1e-5, "latency_p99_ms": 210},
]

API_LOG = """\
=== /var/log/api/api.log (last 40 lines) ===
[03:44:01] INFO  GET /products 200 112ms
[03:44:02] ERROR GET /checkout 500 8102ms — upstream timeout
[03:44:02] ERROR POST /orders  500 8201ms — upstream timeout
[03:44:03] ERROR GET /checkout 500 8098ms — upstream timeout
[03:44:04] WARN  DB query pool: waiting for connection (pool_size=50, active=50)
[03:44:05] ERROR DB connection timeout after 8000ms
[03:44:05] WARN  DB query pool: waiting for connection (pool_size=50, active=50)
Pattern: all 50 connections active, none releasing — connection leak suspected.
"""

DB_METRICS = """\
=== Database Metrics ===
Active connections:   50 / 50  (pool EXHAUSTED) [CRITICAL]
Idle connections:      0
Waiting queries:      142
Avg query time:       880ms   (baseline: 12ms)
Slow queries (>1s):   139
Connection age stats:
  oldest connection:  47 minutes  <-- ANOMALY (should recycle every 5min)
  avg connection age: 38 minutes
  connections from auth service: 48 / 50  <-- ANOMALY
"""

AUTH_LOG = """\
=== /var/log/auth/auth.log (last 40 lines) ===
[03:00:12] INFO  Login success user=alice
[03:01:44] WARN  Login failed  user=bob  (attempt 1/5)
[03:01:44] DEBUG Opening DB connection for audit log...
[03:01:45] WARN  Login failed  user=bob  (attempt 2/5) — connection NOT released after failure
[03:01:46] DEBUG Opening DB connection for audit log...
[03:01:47] WARN  Login failed  user=bob  (attempt 3/5) — connection NOT released after failure
...
ROOT CAUSE: auth.audit_log() opens a DB connection on every failed login but
only closes it in the success path. 48 leaked connections over 47 minutes.
"""

FIX_RESULT = """\
=== Applying fix: restart_auth_with_connection_cleanup ===
[OK] Auth service gracefully stopped — releasing 48 stale DB connections
[OK] DB connection pool: 2/50 active (freed 48)
[OK] Waiting queries draining... 142 -> 0
[OK] API p99 latency: 8100ms -> 145ms
[OK] API error rate:  38% -> 0.4%
[OK] All services healthy.
"""


class DBPoolEnv(IncidentEnv):

    TASK_ID = "db_pool_exhausted"

    def __init__(self):
        super().__init__(self.TASK_ID)

    def _build_initial_state(self) -> Dict[str, Any]:
        return {
            "incident_description": (
                "ALERT: API and DB services degraded. API p99=8.1s, error rate 38%. "
                "DB shows high connection count. Started ~50 minutes ago gradually."
            ),
            "services": [s.copy() for s in INITIAL_SERVICES],
            "root_cause": "db_connection_leak_auth",
            "api_log_read": False,
            "db_metrics_checked": False,
            "auth_log_read": False,
            "sources_correlated": False,
            "fix_applied": False,
            "resolved": False,
            "data_destroyed": False,
            "wrong_fix_attempted": False,
        }

    def _execute_command(self, action: Action) -> Tuple[str, Optional[str]]:
        cmd    = action.command
        params = action.params
        state  = self._state

        sources_seen = sum([
            state["api_log_read"],
            state["db_metrics_checked"],
            state["auth_log_read"],
        ])

        if cmd == CommandType.READ_LOG:
            service = params.get("service", "")
            if service == "api":
                state["api_log_read"] = True
                return API_LOG, None
            elif service == "auth":
                state["auth_log_read"] = True
                return AUTH_LOG, None
            else:
                return f"No log for '{service}'. Try: api, auth, database, payments", None

        elif cmd == CommandType.CHECK_METRICS:
            target = params.get("target", "")
            if target in ("database", "db"):
                state["db_metrics_checked"] = True
                return DB_METRICS, None
            elif target == "api":
                return "API p99=8100ms error_rate=38% — all failures are DB timeouts.", None
            else:
                return f"Targets: api, database, auth, payments", None

        elif cmd == CommandType.APPLY_FIX:
            fix_type = params.get("fix_type", "")
            if fix_type == "restart_auth_with_connection_cleanup":
                if sources_seen < 2:
                    return (
                        "Fix attempted but not effective — you haven't gathered enough "
                        "diagnostic information to confirm the root cause.\n"
                        "Read at least 2 of: api log, db metrics, auth log."
                    ), None
                state["sources_correlated"] = True
                state["fix_applied"] = True
                state["resolved"] = True
                for svc in state["services"]:
                    svc["status"] = "healthy"
                    svc["error_rate"] = max(1e-5, round(0.001 * {"api":4,"database":1,"auth":0,"payments":0}.get(svc["name"],1), 3))
                    svc["latency_p99_ms"] = {"api":145,"database":14,"auth":92,"payments":210}.get(svc["name"], 100)
                return FIX_RESULT, None

            # Accept natural LLM variants for the auth restart fix
            is_auth_fix = (
                "auth" in fix_type.lower() and
                any(w in fix_type.lower() for w in ("restart","fix","cleanup","reset","recycle"))
            ) or fix_type in (
                "restart_auth", "fix_auth_leak", "restart_auth_service",
                "auth_connection_cleanup", "fix_connection_leak",
            )
            if is_auth_fix:
                if sources_seen < 2:
                    return (
                        "Fix attempted but not effective — read more logs first.\n"
                        "You need: api log + db metrics + auth log to confirm the leak."
                    ), None
                state["sources_correlated"] = True
                state["fix_applied"] = True
                state["resolved"] = True
                for svc in state["services"]:
                    svc["status"] = "healthy"
                    svc["error_rate"] = max(1e-5, round(0.001 * {"api":4,"database":1,"auth":0,"payments":0}.get(svc["name"],1), 3))
                    svc["latency_p99_ms"] = {"api":145,"database":14,"auth":92,"payments":210}.get(svc["name"], 100)
                return FIX_RESULT, None
            elif fix_type == "restart_service":
                state["wrong_fix_attempted"] = True
                svc = params.get("service","api")
                return f"Restarted {svc}. DB pool still exhausted — service degraded again in 15s.", None
            elif fix_type == "increase_pool_size":
                state["wrong_fix_attempted"] = True
                return "Pool size increased to 100 but leak continues — pool exhausted again in 8 minutes.", None
            else:
                return (
                    f"Unknown fix '{fix_type}'. "
                    "Try: restart_auth_with_connection_cleanup, restart_service, increase_pool_size"
                ), None

        elif cmd == CommandType.RESTART_SERVICE:
            state["wrong_fix_attempted"] = True
            return "Service restarted. Root cause (connection leak) unchanged — will re-exhaust pool.", None

        elif cmd == CommandType.RUN_DIAGNOSTIC:
            return (
                "Quick diagnostic:\n"
                "CPU: 22%  MEM: 61%  DISK: 44%\n"
                "DB connections: 50/50 EXHAUSTED\n"
                "Hint: trace which service holds the connections."
            ), None

        elif cmd == CommandType.ROLLBACK:
            state["wrong_fix_attempted"] = True
            return "Rolled back last deploy (3 days ago). Pool still exhausted — not a deploy issue.", None

        elif cmd == CommandType.ESCALATE:
            return (
                "Senior SRE asks: which service is holding all the DB connections? "
                "Check DB metrics to see connection ownership breakdown."
            ), None

        return "Unknown command.", f"Command '{cmd}' not recognised."

    def _compute_reward(
        self, action: Action, terminal_output: str
    ) -> Tuple[float, Dict[str, float]]:
        state = self._state
        cmd   = action.command
        params = action.params
        breakdown: Dict[str, float] = {}
        reward = 1e-5

        if cmd == CommandType.READ_LOG and params.get("service") == "api":
            if not state.get("_api_log_reward"):
                breakdown["read_api_log"] = 0.05
                reward += 0.05
                state["_api_log_reward"] = True

        if cmd == CommandType.CHECK_METRICS and params.get("target") in ("database", "db"):
            if not state.get("_db_metrics_reward"):
                breakdown["check_db_metrics"] = 0.10
                reward += 0.10
                state["_db_metrics_reward"] = True

        if cmd == CommandType.READ_LOG and params.get("service") == "auth":
            if not state.get("_auth_log_reward"):
                breakdown["read_auth_log"] = 0.10
                reward += 0.10
                state["_auth_log_reward"] = True

        if state.get("resolved") and not state.get("_fix_reward_given"):
            breakdown["root_cause_identified"] = 0.30
            breakdown["correct_fix_applied"]   = 0.25
            breakdown["service_recovered"]     = 0.20
            reward += 0.75
            state["_fix_reward_given"] = True
            if self._step_count <= 7:
                breakdown["sla_bonus"] = 0.05
                reward += 0.05

        if state.get("wrong_fix_attempted") and not state.get("_wrong_penalty"):
            breakdown["wrong_fix_penalty"] = -0.05
            reward -= 0.05
            state["_wrong_penalty"] = True

        return reward, breakdown
