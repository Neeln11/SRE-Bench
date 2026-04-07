"""
SRE-Bench: Incident Response Environment
Core models and environment class implementing the OpenEnv spec.
"""

from __future__ import annotations

import random
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Action space
# ---------------------------------------------------------------------------

class CommandType(str, Enum):
    READ_LOG        = "read_log"
    CHECK_METRICS   = "check_metrics"
    RUN_DIAGNOSTIC  = "run_diagnostic"
    APPLY_FIX       = "apply_fix"
    ROLLBACK        = "rollback"
    RESTART_SERVICE = "restart_service"
    ESCALATE        = "escalate"


class Action(BaseModel):
    command: CommandType
    params: Dict[str, str] = Field(default_factory=dict)

    class Config:
        use_enum_values = True


# ---------------------------------------------------------------------------
# Observation (what the agent sees)
# ---------------------------------------------------------------------------

class ServiceStatus(BaseModel):
    name: str
    status: str          # "healthy" | "degraded" | "down"
    error_rate: float = Field(..., ge=0.01, le=0.99)   # Strictly (0, 1) exclusive
    latency_p99_ms: int


class Observation(BaseModel):
    terminal_output: str
    services: List[ServiceStatus]
    step: int
    sla_remaining: int   # steps remaining before SLA breach
    incident_description: str
    last_command_error: Optional[str] = None


# ---------------------------------------------------------------------------
# Reward
# ---------------------------------------------------------------------------

class Reward(BaseModel):
    value: float = Field(..., ge=0.01, le=0.99)  # strictly (0, 1) exclusive
    breakdown: Dict[str, float] = Field(default_factory=dict)
    done: bool = False
    info: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Base environment
# ---------------------------------------------------------------------------

class IncidentEnv:
    """
    OpenEnv-compliant incident response environment.
    Subclassed per task scenario.
    """

    MAX_STEPS: int = 15
    SLA_STEPS: int = 12   # after this many steps, SLA is breached

    def __init__(self, task_id: str):
        self.task_id = task_id
        self._state: Dict[str, Any] = {}
        self._step_count: int = 0
        self._episode_reward: float = 0.01  # start strictly above 0
        self._done: bool = False

    # ------------------------------------------------------------------
    # OpenEnv API
    # ------------------------------------------------------------------

    def reset(self) -> Observation:
        """Return a fresh initial observation."""
        self._step_count = 0
        self._episode_reward = 0.01
        self._done = False
        self._state = self._build_initial_state()
        return self._build_observation("Incident detected. Terminal ready.")

    def step(self, action: Action) -> Tuple[Observation, Reward, bool, Dict]:
        """Execute one action and return (obs, reward, done, info)."""
        eps = 1e-5

        if self._done:
            obs = self._build_observation("Episode already finished.")
            return obs, Reward(value=0.01, done=True), True, {}

        self._step_count += 1
        terminal_output, error = self._execute_command(action)
        reward_value, breakdown = self._compute_reward(action, terminal_output)

        # Clip cumulative so it stays strictly in (0.01, 0.99)
        self._episode_reward = min(0.99, max(0.01, self._episode_reward + reward_value))

        resolved  = self._state.get("resolved", False)
        timed_out = self._step_count >= self.MAX_STEPS
        self._done = resolved or timed_out

        obs = self._build_observation(terminal_output, error)

        def clamp(v): return float(max(0.01, min(0.99, v)))

        final_reward       = clamp(reward_value + (0.05 if resolved else 0.0))
        clamped_cumulative = clamp(self._episode_reward)

        # Sanitize breakdown: ensure no 0.0 or negative values exist
        clean_breakdown = {k: clamp(v) for k, v in breakdown.items()}

        reward = Reward(
            value=final_reward,
            breakdown=clean_breakdown,
            done=self._done,
            info={
                "resolved": resolved,
                "timed_out": timed_out,
                "cumulative_reward": clamped_cumulative,
                "step": self._step_count,
            },
        )
        return obs, reward, self._done, reward.info

    def state(self) -> Dict[str, Any]:
        """Return the full internal state (for graders and debugging)."""
        eps = 1e-5
        cumulative = float(max(0.01, min(0.99, self._episode_reward)))
        return {
            **self._state,
            "step": self._step_count,
            "done": self._done,
            "cumulative_reward": cumulative
        }

    def close(self):
        pass

    # ------------------------------------------------------------------
    # To be implemented by each task subclass
    # ------------------------------------------------------------------

    def _build_initial_state(self) -> Dict[str, Any]:
        raise NotImplementedError

    def _execute_command(self, action: Action) -> Tuple[str, Optional[str]]:
        raise NotImplementedError

    def _compute_reward(
        self, action: Action, terminal_output: str
    ) -> Tuple[float, Dict[str, float]]:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_observation(
        self, terminal_output: str, error: Optional[str] = None
    ) -> Observation:
        services = [
            ServiceStatus(**s) for s in self._state.get("services", [])
        ]
        return Observation(
            terminal_output=terminal_output,
            services=services,
            step=self._step_count,
            sla_remaining=max(0, self.SLA_STEPS - self._step_count),
            incident_description=self._state.get("incident_description", ""),
            last_command_error=error,
        )