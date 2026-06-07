"""Unit tests for the Qwen-TTS provider.

We don't load the real Qwen model — the faster_qwen3_tts.FasterQwen3TTS class
is patched at the module level. The tests check:

  * is_available reflects whether the package import succeeded
  * synthesize loads the model lazily and writes a valid wav
  * shutdown drops the cached model
  * per-request voice/language overrides reach generate()
  * empty text fails cleanly via TTSProviderError
"""

from __future__ import annotations

import os
import wave
from typing import Any

import numpy as np
import pytest

from modules.tts.providers import qwen as qwen_module
from modules.tts.providers.base import TTSProviderError
from modules.tts.types import TTSRequest


@pytest.fixture
def fake_model_factory(monkeypatch):
    """Patch FasterQwen3TTS.from_pretrained so no real weights load."""
    calls = {"from_pretrained": 0, "generate": []}

    class _FakeModel:
        def __init__(self):
            self.unloaded = False

        def generate(self, **kwargs):
            calls["generate"].append(kwargs)
            sample_rate = 24000
            samples = np.zeros(sample_rate // 10, dtype=np.float32)  # 0.1s of silence
            return samples, sample_rate

    class _FakeQwen:
        @staticmethod
        def from_pretrained(**kwargs):
            calls["from_pretrained"] += 1
            return _FakeModel()

    monkeypatch.setattr(qwen_module, "_fq", type("_M", (), {"FasterQwen3TTS": _FakeQwen}))
    return calls


@pytest.fixture
def config_stub(monkeypatch):
    state = {
        "model_name": "Qwen/test",
        "device": "cpu",
        "dtype": "float32",
        "max_seq_len": 1024,
        "language": "English",
        "temperature": 0.8,
        "top_k": 40,
    }

    def _setter(**overrides):
        state.update(overrides)

    monkeypatch.setattr(
        "modules.system.config.get_config_value",
        lambda path, default=None, user_uuid=None: state if path == "voice.voice_modules.qwen" else default,
    )
    return _setter


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_is_available_reflects_package_import(monkeypatch):
    provider = qwen_module.QwenTTSProvider()
    assert provider.is_available() is True

    monkeypatch.setattr(qwen_module, "_fq", None)
    assert provider.is_available() is False


# ---------------------------------------------------------------------------
# synthesize
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_synthesize_writes_valid_wav(fake_model_factory, config_stub, tmp_path):
    provider = qwen_module.QwenTTSProvider()
    out = tmp_path / "out.wav"
    result = provider.synthesize(TTSRequest(text="hello"), str(out))

    assert result.success is True
    assert result.provider == "qwen"
    assert os.path.exists(out) and os.path.getsize(out) > 0
    with wave.open(str(out), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 24000


@pytest.mark.regression
def test_synthesize_loads_model_once(fake_model_factory, config_stub, tmp_path):
    provider = qwen_module.QwenTTSProvider()
    provider.synthesize(TTSRequest(text="one"), str(tmp_path / "a.wav"))
    provider.synthesize(TTSRequest(text="two"), str(tmp_path / "b.wav"))
    assert fake_model_factory["from_pretrained"] == 1
    assert len(fake_model_factory["generate"]) == 2


@pytest.mark.regression
def test_synthesize_empty_text_raises(config_stub, tmp_path):
    provider = qwen_module.QwenTTSProvider()
    with pytest.raises(TTSProviderError):
        provider.synthesize(TTSRequest(text="   "), str(tmp_path / "x.wav"))


@pytest.mark.regression
def test_per_request_language_overrides_config(fake_model_factory, config_stub, tmp_path):
    provider = qwen_module.QwenTTSProvider()
    provider.synthesize(TTSRequest(text="hi", language="Chinese"), str(tmp_path / "o.wav"))
    assert fake_model_factory["generate"][-1]["language"] == "Chinese"


@pytest.mark.regression
def test_request_language_auto_falls_back_to_config(fake_model_factory, config_stub, tmp_path):
    provider = qwen_module.QwenTTSProvider()
    provider.synthesize(TTSRequest(text="hi", language="auto"), str(tmp_path / "o.wav"))
    assert fake_model_factory["generate"][-1]["language"] == "English"


@pytest.mark.regression
def test_sampling_tunables_forwarded(fake_model_factory, config_stub, tmp_path):
    provider = qwen_module.QwenTTSProvider()
    provider.synthesize(TTSRequest(text="hi"), str(tmp_path / "o.wav"))
    call = fake_model_factory["generate"][-1]
    # Tunables in the stub should flow through.
    assert call["temperature"] == 0.8
    assert call["top_k"] == 40


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_shutdown_drops_cached_model(fake_model_factory, config_stub, tmp_path):
    provider = qwen_module.QwenTTSProvider()
    provider.synthesize(TTSRequest(text="hi"), str(tmp_path / "o.wav"))
    assert provider._model is not None
    provider.shutdown()
    assert provider._model is None


@pytest.mark.regression
def test_shutdown_when_never_loaded_is_noop():
    provider = qwen_module.QwenTTSProvider()
    # Must not raise even though _model was never built.
    provider.shutdown()
