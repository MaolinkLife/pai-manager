"""The voice state names the chat message that is sounding.

The chat button guessed whether a message was sounding (a flag
only streaming TTS sets, plus a timer by text length), so after a normal answer
it showed "silent" while the voice spoke and needed two clicks to stop.
"""

import asyncio
import queue
import threading

import pytest

from modules.tts import state as voice_state_module
from modules.tts.state import voice_state

pytestmark = pytest.mark.regression


@pytest.fixture
def broadcasts(monkeypatch):
    sent = []
    monkeypatch.setattr(
        voice_state_module,
        "_broadcast_voice_state",
        lambda stage, reason, message_id=None: sent.append((stage, reason, message_id)),
    )
    voice_state.enter_listening("test_reset")
    sent.clear()
    yield sent
    voice_state.enter_listening("test_reset")


def test_speech_names_the_message_it_voices(broadcasts):
    voice_state.enter_speaking("tts_active", message_id="m1")

    assert voice_state.snapshot().message_id == "m1"
    assert broadcasts[-1] == ("speaking", "tts_active", "m1")


def test_leaving_speech_drops_the_message(broadcasts):
    voice_state.enter_speaking("tts_active", message_id="m1")
    voice_state.enter_listening("tts_stopped")

    assert voice_state.snapshot().message_id is None
    assert broadcasts[-1] == ("listening", "tts_stopped", None)


def test_the_next_message_is_announced_even_without_a_pause(broadcasts):
    voice_state.enter_speaking("tts_active", message_id="m1")
    voice_state.enter_speaking("tts_active", message_id="m2")

    assert [item[2] for item in broadcasts] == ["m1", "m2"]


def test_queued_text_keeps_its_message_until_it_sounds():
    from modules.tts.manager import TTSManager

    manager = TTSManager.__new__(TTSManager)  # no providers, no worker thread
    manager._queue = queue.Queue()
    manager._interrupt = threading.Event()
    manager._worker_stop = threading.Event()
    manager._debug = lambda *args, **kwargs: None
    spoken = []
    manager._speak_immediate = lambda text, refuse_pause=False, message_id=None: spoken.append(
        (text, message_id)
    )

    manager.enqueue("Привет", message_id="m1")
    manager._queue.put(None)
    manager._worker_loop()

    assert spoken == [("Привет", "m1")]


def test_voicing_an_answer_passes_its_message_id(monkeypatch):
    from core import decision_layer as decision_layer_module

    calls = []
    monkeypatch.setattr(
        decision_layer_module,
        "speak_line",
        lambda text, refuse_pause=False, message_id=None: calls.append((text, message_id)) or True,
    )
    monkeypatch.setattr(
        decision_layer_module.config_service,
        "get_config_value",
        lambda path, default=None: True if path == "voice.enabled" else default,
    )

    decision_layer_module.DecisionLayer.handle_response(object(), "Ответ", message_id="m1")

    assert calls == [("Ответ", "m1")]


def test_playing_a_saved_message_passes_its_id(monkeypatch):
    from modules.generative import conversation

    calls = []
    monkeypatch.setattr(
        conversation.database_service,
        "get_message_by_id",
        lambda msg_id: {"id": msg_id, "content": "Сохранённый ответ"},
    )
    monkeypatch.setattr(
        conversation.config_service,
        "get_config_value",
        lambda path, default=None: True if path == "voice.enabled" else default,
    )
    monkeypatch.setattr(
        conversation.decision_layer,
        "handle_response",
        lambda text, message_id=None: calls.append((text, message_id)),
    )

    conversation.play_message("m7")

    assert calls == [("Сохранённый ответ", "m7")]


def test_playback_status_names_the_sounding_message(broadcasts):
    from routes import voice_routes

    voice_state.enter_speaking("tts_active", message_id="m1")

    status = asyncio.run(voice_routes.playback_status())

    assert status["stage"] == "speaking"
    assert status["message_id"] == "m1"
