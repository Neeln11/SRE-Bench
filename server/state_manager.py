"""
state_manager.py — Session state management for SRE-Bench.

Provides a thin wrapper around the in-memory session dict so that
session lifecycle (creation, retrieval, cleanup) is handled in one place
rather than scattered across route handlers.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from environment import IncidentEnv


class SessionNotFound(KeyError):
    """Raised when a session_id has no active environment."""


class StateManager:
    """
    Thread-unsafe in-memory store for active IncidentEnv sessions.
    Each session_id maps to exactly one environment instance.
    Replace the backing store with Redis / a db for multi-worker deployments.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, IncidentEnv] = {}

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, session_id: str, env: IncidentEnv) -> None:
        """Register a newly-reset environment under *session_id*."""
        self._sessions[session_id] = env

    def get(self, session_id: str) -> IncidentEnv:
        """Return the environment for *session_id* or raise SessionNotFound."""
        env = self._sessions.get(session_id)
        if env is None:
            raise SessionNotFound(
                f"Session '{session_id}' not found. Call /reset first."
            )
        return env

    def get_or_none(self, session_id: str) -> Optional[IncidentEnv]:
        """Return the environment or None (non-raising variant)."""
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> None:
        """Remove a session (no-op if it doesn't exist)."""
        self._sessions.pop(session_id, None)

    def list_sessions(self) -> Dict[str, Any]:
        """Return a summary of all active sessions (for debugging)."""
        return {
            sid: {
                "task_id": env.task_id,
                "step": env._step_count,
                "done": env._done,
            }
            for sid, env in self._sessions.items()
        }

    def session_count(self) -> int:
        return len(self._sessions)

    # ------------------------------------------------------------------
    # Context manager support (for use in tests)
    # ------------------------------------------------------------------

    def __contains__(self, session_id: str) -> bool:
        return session_id in self._sessions

    def __repr__(self) -> str:  # pragma: no cover
        return f"<StateManager sessions={list(self._sessions.keys())}>"


# ---------------------------------------------------------------------------
# Module-level singleton used by main.py
# ---------------------------------------------------------------------------

session_store = StateManager()
