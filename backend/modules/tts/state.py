from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from modules.system.logger import log_audit_entry, AuditStatus


class VoiceStage(str, Enum):
    LISTENING = "listening"
    WAITING = "waiting"
    SPEAKING = "speaking"


@dataclass
class VoiceStateSnapshot:
    stage: VoiceStage
    changed_at: datetime
    reason: Optional[str]
    message_id: Optional[str] = None


def _broadcast_voice_state(stage: str, reason: Optional[str], message_id: Optional[str] = None) -> None:
    """Fire-and-forget WS push of the voice stage onto the uvicorn loop.

    Transitions happen in TTS worker threads, so the coroutine is scheduled
    via the main-loop registry; before the loop is registered (boot window)
    the event is silently dropped.
    """
    try:
        import asyncio
        import json

        from core.event_loop_registry import get_main_loop
        from core.websocket_manager import manager

        loop = get_main_loop()
        if loop is None:
            return
        payload = {
            "type": "voice_state",
            "stage": stage,
            "reason": reason,
            "message_id": message_id,
            "timestamp": datetime.utcnow().isoformat(),
        }
        asyncio.run_coroutine_threadsafe(
            manager.send_message(json.dumps(payload, ensure_ascii=False)), loop
        )
    except Exception:
        pass


class VoiceStateController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stage = VoiceStage.LISTENING
        self._changed_at = datetime.utcnow()
        self._reason: Optional[str] = None
        self._message_id: Optional[str] = None

    def _set_stage(
        self, stage: VoiceStage, reason: Optional[str], message_id: Optional[str] = None
    ) -> None:
        # Only speech belongs to a chat message; every other stage has none.
        if stage != VoiceStage.SPEAKING:
            message_id = None
        with self._lock:
            if self._stage == stage and reason == self._reason and message_id == self._message_id:
                return
            self._stage = stage
            self._changed_at = datetime.utcnow()
            self._reason = reason
            self._message_id = message_id

        log_audit_entry(
            "voice_state_transition",
            "[Voice] Stage updated",
            AuditStatus.INFO,
            details={"stage": stage.value, "reason": reason, "message_id": message_id},
        )
        _broadcast_voice_state(stage.value, reason, message_id)

    def enter_waiting(self, reason: Optional[str] = None) -> None:
        self._set_stage(VoiceStage.WAITING, reason)

    def enter_listening(self, reason: Optional[str] = None) -> None:
        self._set_stage(VoiceStage.LISTENING, reason)

    def enter_speaking(self, reason: Optional[str] = None, message_id: Optional[str] = None) -> None:
        self._set_stage(VoiceStage.SPEAKING, reason, message_id)

    def stage(self) -> VoiceStage:
        with self._lock:
            return self._stage

    def snapshot(self) -> VoiceStateSnapshot:
        with self._lock:
            return VoiceStateSnapshot(self._stage, self._changed_at, self._reason, self._message_id)

    def is_listening(self) -> bool:
        return self.stage() == VoiceStage.LISTENING


voice_state = VoiceStateController()

__all__ = ["VoiceStage", "VoiceStateSnapshot", "voice_state", "VoiceStateController"]
