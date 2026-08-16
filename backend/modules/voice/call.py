"""Call orchestration: start/stop a continuous voice conversation.

start_call: ensures the VAD loop is running (spawning it past the config
gates if background voice mode is off), marks the session active and
broadcasts ``call_state`` over WS so the visualizer can switch into call UI.
stop_call: cuts any current speech, clears the flag and stops the VAD loop
only when this call started it.
"""

from __future__ import annotations

import json

from core.websocket_manager import manager
from modules.system.logger import AuditStatus, log_audit_entry
from modules.tts.service import force_cut_voice
from modules.tts.state import voice_state
from modules.voice.call_state import call_state
from modules.voice.vad_listener import is_vad_running, start_vad_background, stop_vad


async def _broadcast_call_state(active: bool) -> None:
    try:
        await manager.send_message(
            json.dumps({"type": "call_state", "active": active}, ensure_ascii=False)
        )
    except Exception:
        pass


async def start_call() -> dict:
    if call_state.is_active():
        return {"status": "ok", "active": True, "message": "Call already active"}

    vad_started_by_call = not is_vad_running()
    # Activate the flag first: the VAD entry gate checks it when
    # voice.enabled is off (a call overrides background-mode config).
    call_state.activate(vad_started_by_call=vad_started_by_call)
    if vad_started_by_call:
        started, message = await start_vad_background(force=True)
        if not started:
            call_state.deactivate()
            return {"status": "error", "active": False, "message": message}

    voice_state.enter_listening("call_started")
    await _broadcast_call_state(True)
    log_audit_entry(
        "voice_call_started",
        "[Call] Voice call started.",
        AuditStatus.SUCCESS,
        details={"vad_started_by_call": vad_started_by_call},
    )
    return {"status": "ok", "active": True, "message": "Call started"}


async def stop_call() -> dict:
    if not call_state.is_active():
        return {"status": "ok", "active": False, "message": "No active call"}

    try:
        force_cut_voice()
    except Exception:
        pass
    vad_started_by_call = call_state.deactivate()
    if vad_started_by_call:
        try:
            await stop_vad(wait=True)
        except Exception:
            pass
    voice_state.enter_listening("call_ended")
    await _broadcast_call_state(False)
    log_audit_entry(
        "voice_call_stopped",
        "[Call] Voice call ended.",
        AuditStatus.INFO,
        details={"vad_stopped": vad_started_by_call},
    )
    return {"status": "ok", "active": False, "message": "Call ended"}


def call_status() -> dict:
    snapshot = call_state.snapshot()
    snapshot["status"] = "ok"
    snapshot["vad_running"] = is_vad_running()
    snapshot["stage"] = voice_state.stage().value
    return snapshot
