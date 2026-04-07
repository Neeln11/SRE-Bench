"""
graders.py — Deterministic graders for all 3 tasks.
Each grader inspects the final state dict and returns a float strictly in (0.0, 1.0).
Zero LLM calls. Zero randomness.
"""

from __future__ import annotations

from typing import Any, Dict


class BaseGrader:
    def clamp_score(self, score: float) -> float:
        """Strictly between 0 and 1 (exclusive)."""
        eps = 1e-5
        return float(max(eps, min(1.0 - eps, score)))

    def grade(self, state: Dict[str, Any]) -> float:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Task 1 — Disk Full
# ---------------------------------------------------------------------------

class DiskFullGrader(BaseGrader):
    """
    Scoring rubric:
      0.10  checked disk metrics
      0.10  read application log
      0.30  identified correct culprit file
      0.30  fix applied
      0.20  service health restored
      ----
      1.00  maximum
      -0.05 per wrong fix attempt (min 0.0)
    """

    def grade(self, state: Dict[str, Any]) -> float:
        score = 1e-5

        if state.get("disk_checked"):
            score += 0.10
        if state.get("log_read"):
            score += 0.10
        if state.get("correct_file_identified") or state.get("fix_applied"):
            score += 0.30
        if state.get("fix_applied"):
            score += 0.30

        services = {s["name"]: s for s in state.get("services", [])}
        api = services.get("api", {})
        if api.get("status") == "healthy" and api.get("error_rate", 0.99999) < 0.05:
            score += 0.20

        wrong = 1 if state.get("wrong_fix_attempted") else 0
        score -= wrong * 0.05

        return self.clamp_score(score)


# ---------------------------------------------------------------------------
# Task 2 — DB Pool Exhausted
# ---------------------------------------------------------------------------

class DBPoolGrader(BaseGrader):
    """
    Scoring rubric:
      0.05  read API log
      0.10  checked DB metrics
      0.10  read auth log
      0.30  applied correct fix (requires multi-source correlation)
      0.20  services restored to healthy
      0.05  resolved within SLA (≤7 steps)
      0.20  implicit for resolution
      ----
      1.00  maximum
      -0.05 per wrong fix attempt (min 0.0)
    """

    def grade(self, state: Dict[str, Any]) -> float:
        score = 1e-5

        if state.get("api_log_read"):
            score += 0.05
        if state.get("db_metrics_checked"):
            score += 0.10
        if state.get("auth_log_read"):
            score += 0.10
        if state.get("fix_applied"):
            score += 0.30

        services = {s["name"]: s for s in state.get("services", [])}
        healthy_count = sum(
            1 for s in services.values() if s.get("status") == "healthy"
        )
        if healthy_count == len(services) and state.get("resolved"):
            score += 0.20

        if state.get("resolved") and state.get("step", 99) <= 7:
            score += 0.05

        if state.get("resolved"):
            score += 0.20

        wrong = 1 if state.get("wrong_fix_attempted") else 0
        score -= wrong * 0.05

        return self.clamp_score(score)


# ---------------------------------------------------------------------------
# Task 3 — Data Corruption
# ---------------------------------------------------------------------------

class DataCorruptionGrader(BaseGrader):
    """
    Scoring rubric:
      0.07 × 3  read all three service logs             = 0.21
      0.06      checked deploy history                  = 0.06
      0.20      correct rollback of orders service      = 0.20
      0.15      traced chain across all 3 services      = 0.15
      0.20      triggered reprocess of affected orders  = 0.20
      0.15      full resolution                         = 0.15
      0.05      resolved within SLA (≤10 steps)         = 0.05
      ----
      1.07 raw max → capped to 1.0
      -0.50  data permanently destroyed
      -0.05  wrong fix
    """

    def grade(self, state: Dict[str, Any]) -> float:
        score = 1e-5

        if state.get("orders_log_read"):
            score += 0.07
        if state.get("fulfillment_log_read"):
            score += 0.07
        if state.get("finance_log_read"):
            score += 0.07
        if state.get("deploy_checked"):
            score += 0.06
        if state.get("rollback_done"):
            score += 0.20
        if state.get("chain_understood"):
            score += 0.15
        if state.get("reprocess_triggered"):
            score += 0.20
        if state.get("resolved"):
            score += 0.15
        if state.get("resolved") and state.get("step", 99) <= 10:
            score += 0.05

        if state.get("data_destroyed"):
            score -= 0.50
        if state.get("wrong_fix_attempted"):
            score -= 0.05

        score = max(1e-5, score)
        return self.clamp_score(score)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

GRADER_REGISTRY: Dict[str, BaseGrader] = {
    "disk_full":         DiskFullGrader(),
    "db_pool_exhausted": DBPoolGrader(),
    "data_corruption":   DataCorruptionGrader(),
}


def grade_task(task_id: str, state: Dict[str, Any]) -> float:
    grader = GRADER_REGISTRY.get(task_id)
    if grader is None:
        raise ValueError(f"No grader registered for task '{task_id}'")
    return grader.grade(state)
