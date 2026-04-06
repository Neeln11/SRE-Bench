"""
Task 3 — HARD: Silent Data Corruption (Cascading Failure)
Root cause: a bad deploy pushed a serializer bug that corrupts order data.
Orders service writes garbage -> fulfillment silently drops rows ->
finance double-counts. No single log reveals the full picture.
Agent must: trace chain across 3 services, rollback config, trigger re-process
WITHOUT wiping valid data.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from environment import Action, CommandType, IncidentEnv


INITIAL_SERVICES = [
    {"name": "orders",      "status": "healthy",  "error_rate": 0.01, "latency_p99_ms": 95},
    {"name": "fulfillment", "status": "healthy",  "error_rate": 0.02, "latency_p99_ms": 220},
    {"name": "finance",     "status": "healthy",  "error_rate": 0.00, "latency_p99_ms": 180},
    {"name": "api",         "status": "healthy",  "error_rate": 0.01, "latency_p99_ms": 140},
]

ORDERS_LOG = """\
=== /var/log/orders/orders.log ===
[08:02:14] INFO  Deploy v2.4.1 activated (serializer: msgpack -> json_v2)
[08:02:15] INFO  Order #10041 created — payload written to queue
[08:02:16] INFO  Order #10042 created — payload written to queue
[08:02:17] WARN  Order #10043 — json_v2 encoder: unicode escape in item_id field
[08:02:18] INFO  Order #10044 created — payload written to queue
...
[08:47:01] INFO  Order #10891 created — payload written to queue

No errors reported. Orders service believes it is functioning correctly.
Note: json_v2 serializer silently replaces unrecognised chars with '?' in item_id.
"""

FULFILLMENT_LOG = """\
=== /var/log/fulfillment/fulfillment.log ===
[08:02:15] INFO  Processing order #10041 — OK
[08:02:16] INFO  Processing order #10042 — OK
[08:02:17] WARN  Order #10043 item_id='PROD???' not found in catalogue — SKIPPING
[08:02:18] INFO  Processing order #10044 — OK
[08:02:19] WARN  Order #10045 item_id='SKU??1' not found in catalogue — SKIPPING
...
[08:47:01] WARN  Skipped 412 orders this hour (item_id not found)  <-- ANOMALY

Fulfillment silently skips unrecognised item IDs.
Orders with '?' in item_id are NEVER fulfilled — no error raised upstream.
"""

FINANCE_LOG = """\
=== /var/log/finance/finance.log ===
[08:02:15] INFO  Invoice #INV-10041 generated — $124.00
[08:02:16] INFO  Invoice #INV-10042 generated — $87.50
[08:02:17] INFO  Invoice #INV-10043 generated — $210.00  <-- order was skipped by fulfillment
[08:02:18] INFO  Invoice #INV-10043 generated — $210.00  <-- DUPLICATE (retry triggered by timeout)
...
Finance generates invoices from the orders queue independently of fulfillment.
Skipped orders still get invoiced — and retried — causing double-billing.
Estimated impact: 412 orders skipped, ~180 double-billed. $47,200 overcharge.
"""

DEPLOY_HISTORY = """\
=== Deploy History (last 24h) ===
08:02:11  orders-service  v2.4.1  serializer: upgraded msgpack -> json_v2  [ACTIVE]
07:55:00  finance-service v1.9.3  tax_rate update  [ACTIVE]
06:30:00  fulfillment     v3.1.0  warehouse routing update  [ACTIVE]

Config diff for orders v2.4.1:
- serializer: "msgpack"
+ serializer: "json_v2"
  json_v2_options:
+   unknown_char_replacement: "?"   <-- THIS IS THE BUG
"""

REPROCESS_RESULT = """\
=== Re-processing 412 affected orders ===
[OK] Identified orders #10043–#10891 with corrupted item_id (contains '?')
[OK] Re-fetched original item_ids from orders database (pre-serialization values preserved)
[OK] Re-queued 412 orders to fulfillment with correct item_ids
[OK] Reversed 180 duplicate invoices — $47,200 credit issued
[OK] Fulfillment processing corrected orders...
[OK] All 412 orders fulfilled.
[OK] Finance reconciliation complete. No overcharges remaining.
INCIDENT RESOLVED.
"""

WRONG_WIPE = """\
=== DESTRUCTIVE ACTION DETECTED ===
Wiped orders table for range #10043–#10891.
412 orders permanently deleted — customers will need to re-place orders.
Finance invoices remain — now orphaned (no matching orders).
Data loss is UNRECOVERABLE from this environment.
[CRITICAL] This made the incident significantly worse.
"""


class DataCorruptionEnv(IncidentEnv):

    TASK_ID = "data_corruption"

    def __init__(self):
        super().__init__(self.TASK_ID)

    def _build_initial_state(self) -> Dict[str, Any]:
        return {
            "incident_description": (
                "ALERT (low priority): Finance team reports ~180 duplicate invoices "
                "in the last hour. No service errors. No alerts fired. "
                "Ticket raised 45 minutes after deploy window."
            ),
            "services": [s.copy() for s in INITIAL_SERVICES],
            "root_cause": "serializer_bug_json_v2",
            "orders_log_read":      False,
            "fulfillment_log_read": False,
            "finance_log_read":     False,
            "deploy_checked":       False,
            "chain_understood":     False,
            "rollback_done":        False,
            "reprocess_triggered":  False,
            "data_destroyed":       False,
            "resolved":             False,
            "wrong_fix_attempted":  False,
        }

    def _execute_command(self, action: Action) -> Tuple[str, Optional[str]]:
        cmd    = action.command
        params = action.params
        state  = self._state

        logs_read = sum([
            state["orders_log_read"],
            state["fulfillment_log_read"],
            state["finance_log_read"],
        ])

        if cmd == CommandType.READ_LOG:
            service = params.get("service", "")
            if service == "orders":
                state["orders_log_read"] = True
                return ORDERS_LOG, None
            elif service == "fulfillment":
                state["fulfillment_log_read"] = True
                return FULFILLMENT_LOG, None
            elif service == "finance":
                state["finance_log_read"] = True
                return FINANCE_LOG, None
            else:
                return f"No log for '{service}'. Try: orders, fulfillment, finance, api", None

        elif cmd == CommandType.CHECK_METRICS:
            target = params.get("target", "")
            if target == "orders":
                return "Orders: 850 rps, p99=95ms, error_rate=1% — looks healthy.", None
            elif target == "fulfillment":
                return (
                    "Fulfillment: 438 rps processed, 412 skipped (WARN) — "
                    "skip reason: item_id not found in catalogue."
                ), None
            elif target == "finance":
                return "Finance: 1262 invoices generated (expected ~850). 180 duplicates detected.", None
            else:
                return f"Targets: orders, fulfillment, finance, api", None

        elif cmd == CommandType.RUN_DIAGNOSTIC:
            diag = params.get("type", "")
            if diag == "deploy_history" or diag == "":
                state["deploy_checked"] = True
                return DEPLOY_HISTORY, None
            return "Run with type=deploy_history for recent changes.", None

        elif cmd == CommandType.ROLLBACK:
            service = params.get("service", "")
            if service == "orders":
                if logs_read < 2:
                    return (
                        "Rollback of orders v2.4.1 applied. "
                        "Serializer reverted to msgpack. "
                        "New orders will serialize correctly. "
                        "But 412 already-corrupted orders still need reprocessing."
                    ), None
                state["rollback_done"] = True
                return (
                    "Rollback of orders v2.4.1 applied. Serializer reverted to msgpack.\n"
                    "New orders will serialize correctly.\n"
                    "412 previously corrupted orders still need reprocessing via apply_fix(reprocess_affected_orders)."
                ), None
            else:
                state["wrong_fix_attempted"] = True
                return f"Rolled back {service} — not the source of corruption. Problem persists.", None

        elif cmd == CommandType.APPLY_FIX:
            fix_type = params.get("fix_type", "")

            if fix_type == "reprocess_affected_orders":
                if not state["rollback_done"]:
                    return (
                        "Cannot reprocess — serializer bug still active. "
                        "Rollback orders service first."
                    ), None
                if not state["orders_log_read"] or not state["fulfillment_log_read"]:
                    return (
                        "Reprocess attempted but incomplete understanding of affected range. "
                        "Read orders and fulfillment logs to confirm scope."
                    ), None
                state["chain_understood"] = True
                state["reprocess_triggered"] = True
                state["resolved"] = True
                for svc in state["services"]:
                    svc["status"] = "healthy"
                return REPROCESS_RESULT, None

            elif fix_type == "wipe_corrupted_orders":
                state["data_destroyed"] = True
                state["wrong_fix_attempted"] = True
                return WRONG_WIPE, None

            elif fix_type == "restart_service":
                state["wrong_fix_attempted"] = True
                return "Service restarted. Serializer config unchanged. Corruption continues.", None

            else:
                return (
                    f"Unknown fix '{fix_type}'. "
                    "Try: reprocess_affected_orders, wipe_corrupted_orders, restart_service"
                ), None

        elif cmd == CommandType.RESTART_SERVICE:
            state["wrong_fix_attempted"] = True
            return "Restarted. Serializer config loaded from same bad config. Problem unchanged.", None

        elif cmd == CommandType.ESCALATE:
            if logs_read == 0:
                return "Escalated. Senior SRE asks: have you checked the logs across all 3 services?", None
            elif logs_read == 1:
                return "Senior SRE: the issue spans multiple services — check fulfillment and finance logs too.", None
            else:
                return "Senior SRE: you have the data. Check recent deploys — something changed the serializer.", None

        return "Unknown command.", f"Command '{cmd}' not recognised."

    def _compute_reward(
        self, action: Action, terminal_output: str
    ) -> Tuple[float, Dict[str, float]]:
        state  = self._state
        cmd    = action.command
        params = action.params
        breakdown: Dict[str, float] = {}
        reward = 0.0

        for svc, key in [("orders","_ord"), ("fulfillment","_ful"), ("finance","_fin")]:
            log_key = f"{svc}_log_read"
            rew_key = f"_log_reward{key}"
            if state.get(log_key) and not state.get(rew_key):
                breakdown[f"read_{svc}_log"] = 0.07
                reward += 0.07
                state[rew_key] = True

        if state.get("deploy_checked") and not state.get("_deploy_reward"):
            breakdown["checked_deploy_history"] = 0.06
            reward += 0.06
            state["_deploy_reward"] = True

        if state.get("rollback_done") and not state.get("_rollback_reward"):
            breakdown["correct_rollback"] = 0.20
            reward += 0.20
            state["_rollback_reward"] = True

        if state.get("resolved") and not state.get("_fix_reward_given"):
            breakdown["chain_traced"]         = 0.15
            breakdown["reprocess_triggered"]  = 0.20
            breakdown["incident_resolved"]    = 0.15
            reward += 0.50
            state["_fix_reward_given"] = True
            if self._step_count <= 10:
                breakdown["sla_bonus"] = 0.05
                reward += 0.05

        if state.get("data_destroyed") and not state.get("_destroy_penalty"):
            breakdown["data_destruction_penalty"] = -0.50
            reward -= 0.50
            state["_destroy_penalty"] = True

        if state.get("wrong_fix_attempted") and not state.get("_wrong_penalty"):
            breakdown["wrong_fix_penalty"] = -0.05
            reward -= 0.05
            state["_wrong_penalty"] = True

        return reward, breakdown
