"""Tests for the sherpa-onnx STT branch.

We don't load a real sherpa model in tests — the recognizer is patched at the
module level. The point is to verify:

  * transcribe_audio routes to sherpa_onnx_engine when stt.provider == "sherpa_onnx"
  * the default path (whisper) is unchanged
  * the recognizer is rebuilt when settings change (fingerprint behaviour)
  * misconfigured profiles raise SherpaUnavailableError cleanly
"""

from __future__ import annotations

import struct
import wave
from typing import Any

import pytest

from modules.voice import sherpa_onnx_engine
from modules.voice import stt as stt_module


@pytest.fixture(autouse=True)
def reset_recognizer():
    """Make sure tests do not share a cached recognizer between runs."""
    sherpa_onnx_engine.release()
    yield
    sherpa_onnx_engine.release()


@pytest.fixture
def fake_recognizer(monkeypatch):
    """Patch _build_recognizer to hand back a fake whose stream.result.text is configurable."""
    state = {"text": "hello world"}

    class _FakeStream:
        def __init__(self):
            self.result = type("R", (), {"text": state["text"]})()

        def accept_waveform(self, sample_rate, samples):
            self.sample_rate = sample_rate
            self.samples = samples

    class _FakeRecognizer:
        def __init__(self, cfg):
            self.cfg = cfg

        def create_stream(self):
            return _FakeStream()

        def decode_stream(self, stream):
            stream.result.text = state["text"]

    def _setter(text: str) -> None:
        state["text"] = text

    monkeypatch.setattr(sherpa_onnx_engine, "_build_recognizer", lambda cfg: _FakeRecognizer(cfg))
    return _setter


@pytest.fixture
def wav_file(tmp_path):
    path = tmp_path / "sample.wav"
    sample_rate = 16000
    samples = b"".join(struct.pack("<h", int(0.1 * 32767)) for _ in range(sample_rate // 4))  # 0.25s
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples)
    return str(path)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_default_provider_is_whisper(monkeypatch):
    monkeypatch.setattr(
        stt_module.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: default,
    )
    assert stt_module._resolve_provider() == "whisper"


@pytest.mark.regression
def test_resolve_provider_normalises_case(monkeypatch):
    monkeypatch.setattr(
        stt_module.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: "Sherpa_OnnX" if path == "stt.provider" else default,
    )
    assert stt_module._resolve_provider() == "sherpa_onnx"


@pytest.mark.regression
def test_invalid_provider_falls_back_to_whisper(monkeypatch):
    """An unknown DB value must not silently fail — fall back to the default."""
    monkeypatch.setattr(
        stt_module.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: "vosk-xyz" if path == "stt.provider" else default,
    )
    assert stt_module._resolve_provider() == "whisper"


# ---------------------------------------------------------------------------
# sherpa engine
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_sherpa_transcribe_returns_recognizer_text(fake_recognizer, wav_file, monkeypatch):
    monkeypatch.setattr(
        sherpa_onnx_engine.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: {
            "model_type": "transducer",
            "tokens": "/fake/tokens.txt",
            "encoder": "/fake/encoder.onnx",
            "decoder": "/fake/decoder.onnx",
            "joiner": "/fake/joiner.onnx",
        } if path == "stt.sherpa_onnx" else default,
    )
    fake_recognizer("test transcript")
    result = sherpa_onnx_engine.transcribe(wav_file)
    assert result == "test transcript"


@pytest.mark.regression
def test_sherpa_recognizer_rebuilt_when_settings_change(fake_recognizer, wav_file, monkeypatch):
    state = {"cfg": {"model_type": "transducer", "tokens": "/a", "encoder": "/a", "decoder": "/a", "joiner": "/a"}}

    monkeypatch.setattr(
        sherpa_onnx_engine.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: state["cfg"] if path == "stt.sherpa_onnx" else default,
    )
    sherpa_onnx_engine.transcribe(wav_file)
    first_fingerprint = sherpa_onnx_engine._RECOGNIZER_CFG_FINGERPRINT

    state["cfg"] = {"model_type": "transducer", "tokens": "/b", "encoder": "/b", "decoder": "/b", "joiner": "/b"}
    sherpa_onnx_engine.transcribe(wav_file)
    second_fingerprint = sherpa_onnx_engine._RECOGNIZER_CFG_FINGERPRINT
    assert first_fingerprint != second_fingerprint


@pytest.mark.regression
def test_relative_paths_resolve_against_stt_models_dir():
    """Relative paths must land inside backend/storage/models/stt, not CWD."""
    from constants.paths import STT_MODELS_DIR

    resolved = sherpa_onnx_engine._resolve_model_path("sherpa-onnx-en/encoder.onnx")
    assert resolved.startswith(STT_MODELS_DIR)
    assert resolved.endswith("encoder.onnx")


@pytest.mark.regression
def test_absolute_paths_pass_through_unchanged():
    import os

    absolute = os.path.join(os.sep, "abs", "models", "encoder.onnx")
    assert sherpa_onnx_engine._resolve_model_path(absolute) == absolute


@pytest.mark.regression
def test_empty_path_returns_empty_string():
    assert sherpa_onnx_engine._resolve_model_path(None) == ""
    assert sherpa_onnx_engine._resolve_model_path("   ") == ""


@pytest.mark.regression
def test_sherpa_misconfigured_transducer_raises(wav_file, monkeypatch):
    """Missing tokens path must raise SherpaUnavailableError rather than letting sherpa-onnx crash on its own."""
    monkeypatch.setattr(
        sherpa_onnx_engine.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: {
            "model_type": "transducer",
            "tokens": "",  # missing
            "encoder": "/a",
            "decoder": "/a",
            "joiner": "/a",
        } if path == "stt.sherpa_onnx" else default,
    )
    with pytest.raises(sherpa_onnx_engine.SherpaUnavailableError):
        sherpa_onnx_engine.transcribe(wav_file)


# ---------------------------------------------------------------------------
# Routing through transcribe_audio
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_transcribe_audio_routes_to_sherpa_when_selected(fake_recognizer, wav_file, monkeypatch):
    def _cfg(path, default=None, user_uuid=None):
        if path == "stt.provider":
            return "sherpa_onnx"
        if path == "stt.sherpa_onnx":
            return {"model_type": "transducer", "tokens": "/t", "encoder": "/e", "decoder": "/d", "joiner": "/j"}
        return default

    monkeypatch.setattr(stt_module.config_service, "get_config_value", _cfg)
    monkeypatch.setattr(sherpa_onnx_engine.config_service, "get_config_value", _cfg)

    fake_recognizer("from sherpa")
    text = stt_module.transcribe_audio(wav_file)
    assert text == "from sherpa"
