"""Call session flag — a user-initiated continuous voice conversation.

Kept import-light on purpose: vad_listener and the decision layer read the
flag to relax their gates during a call (trigger words bypassed, TTS speaks
even when voice.enabled is off), while the orchestration lives in
modules/voice/call.py. A call is an explicit user action, so it overrides
the config flags that govern the always-on background voice mode.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional


class _CallState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = False
        self._started_at: Optional[datetime] = None
        # True when the call itself spawned the VAD loop (background voice
        # mode was off) — hang-up must stop it; otherwise leave it running.
        self._vad_started_by_call = False

    def activate(self, *, vad_started_by_call: bool) -> None:
        with self._lock:
            self._active = True
            self._started_at = datetime.now(timezone.utc)
            self._vad_started_by_call = vad_started_by_call

    def deactivate(self) -> bool:
        """Returns whether the VAD loop was started by this call."""
        with self._lock:
            started_by_call = self._vad_started_by_call
            self._active = False
            self._started_at = None
            self._vad_started_by_call = False
            return started_by_call

    def is_active(self) -> bool:
        with self._lock:
            return self._active

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "active": self._active,
                "started_at": self._started_at.isoformat() if self._started_at else None,
            }


call_state = _CallState()


def is_call_active() -> bool:
    return call_state.is_active()
