"""Facade helpers for TTS operations, replacing legacy voice_service."""

from __future__ import annotations

from typing import Dict

from modules.tts.manager import TTSManager
from modules.tts.types import TTSRequest
from modules.tts.state import voice_state

_tts_manager: TTSManager | None = None


def _get_tts_manager() -> TTSManager:
    global _tts_manager
    if _tts_manager is None:
        _tts_manager = TTSManager()
    return _tts_manager


def speak_line(text: str, refuse_pause: bool = False) -> bool:
    if not text:
        return False
    _get_tts_manager().enqueue(text, refuse_pause=refuse_pause)
    return True


def generate_tts(text: str, filename: str):
    return _get_tts_manager().synthesize_to_file(TTSRequest(text=text), filename)


def play_voice_output(file_path: str) -> None:
    _get_tts_manager().play_file(file_path)


def stream_speak_line(text: str, devices: list[int]):
    result = speak_line(text)
    return result


def check_if_speaking() -> bool:
    return voice_state.stage().value == "speaking"


def set_speaking(flag: bool) -> None:
    if flag:
        voice_state.enter_speaking("tts_active")
    else:
        voice_state.enter_listening("tts_idle")


def force_cut_voice() -> None:
    _get_tts_manager().stop()


def log_last_output(text: str) -> None:
    _get_tts_manager().log_output(text)


def is_self_trigger(text: str) -> bool:
    return _get_tts_manager().matches_recent_output(text)


def shutdown() -> None:
    global _tts_manager
    if _tts_manager is not None:
        _tts_manager.shutdown()
        _tts_manager = None


def describe_providers() -> Dict[str, Dict[str, object]]:
    print("[TTS Service] Запрос статуса TTS провайдеров.")
    return _get_tts_manager().describe_providers()
