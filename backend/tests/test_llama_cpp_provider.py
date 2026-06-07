"""Unit tests for modules/generative/providers/llama_cpp.py.

Covers:
  * is_available reads from DB-first config and respects the ``enabled`` flag.
  * Sync generate uses the OpenAI-style choices[0].message.content shape.
  * Sampler merges DB defaults with per-request options.
  * Streaming yields content deltas and terminates on finish_reason.

Network calls are stubbed via monkeypatch — no real llama-server is required.
"""

from __future__ import annotations

from typing import Any

import pytest

from modules.generative.providers import llama_cpp as llama_cpp_provider
from modules.generative.providers.base import ProviderError, ProviderNotAvailable
from modules.generative.types import GenerateRequest


@pytest.fixture
def force_config(monkeypatch):
    """Force a known llama_cpp config dict regardless of DB state."""
    state = {
        "enabled": True,
        "base_url": "http://test-llama:9999",
        "model": "test.gguf",
        "temperature": 0.5,
        "top_p": 0.8,
        "max_tokens": 64,
        "request_timeout": 5,
        "stream_timeout": 5,
    }

    def _setter(**overrides: Any) -> None:
        state.update(overrides)

    monkeypatch.setattr(
        llama_cpp_provider.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: state if path == "api.providers.llama_cpp" else default,
    )
    return _setter


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_provider_disabled_by_default(monkeypatch):
    monkeypatch.setattr(
        llama_cpp_provider.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: {"enabled": False} if path == "api.providers.llama_cpp" else default,
    )
    provider = llama_cpp_provider.LlamaCppGenerateProvider()
    assert provider.is_available() is False


@pytest.mark.regression
def test_provider_enabled_when_flag_set(force_config):
    provider = llama_cpp_provider.LlamaCppGenerateProvider()
    assert provider.is_available() is True


# ---------------------------------------------------------------------------
# generate (sync)
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_generate_parses_openai_choices_shape(force_config, monkeypatch):
    captured: dict[str, Any] = {}

    def fake_chat_completion(**kwargs):
        captured.update(kwargs)
        return {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hello back."},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4},
        }

    monkeypatch.setattr(llama_cpp_provider.llama_client, "chat_completion", fake_chat_completion)

    provider = llama_cpp_provider.LlamaCppGenerateProvider()
    result = provider.generate(
        GenerateRequest(
            messages=[{"role": "user", "content": "Hi"}],
            options={},
            metadata={},
        )
    )

    assert result.provider == "llama_cpp"
    assert result.content == "Hello back."
    assert result.metadata["finish_reason"] == "stop"
    assert result.metadata["usage"]["prompt_tokens"] == 12
    # base_url passes through from config (no trailing slash).
    assert captured["base_url"] == "http://test-llama:9999"
    assert captured["model"] == "test.gguf"
    assert captured["sampler"]["temperature"] == 0.5


@pytest.mark.regression
def test_generate_raises_when_disabled(monkeypatch):
    monkeypatch.setattr(
        llama_cpp_provider.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: {"enabled": False} if path == "api.providers.llama_cpp" else default,
    )
    provider = llama_cpp_provider.LlamaCppGenerateProvider()
    with pytest.raises(ProviderNotAvailable):
        provider.generate(GenerateRequest(messages=[{"role": "user", "content": "Hi"}]))


@pytest.mark.regression
def test_generate_wraps_transport_error(force_config, monkeypatch):
    import requests

    def fake_chat_completion(**kwargs):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(llama_cpp_provider.llama_client, "chat_completion", fake_chat_completion)

    provider = llama_cpp_provider.LlamaCppGenerateProvider()
    with pytest.raises(ProviderError) as excinfo:
        provider.generate(GenerateRequest(messages=[{"role": "user", "content": "Hi"}]))
    assert "connection refused" in str(excinfo.value)


# ---------------------------------------------------------------------------
# sampler merging
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_sampler_request_options_override_db_defaults(force_config):
    provider = llama_cpp_provider.LlamaCppGenerateProvider()
    cfg = provider._get_provider_config()
    request = GenerateRequest(
        messages=[{"role": "user", "content": "x"}],
        options={"temperature": 0.1, "top_p": 0.7},
    )
    sampler = provider._sampler_from(request, cfg)
    # Request wins over DB.
    assert sampler["temperature"] == 0.1
    assert sampler["top_p"] == 0.7
    # DB-only key still flows through.
    assert sampler["max_tokens"] == 64


@pytest.mark.regression
def test_sampler_num_predict_alias_picked_up_as_max_tokens(force_config):
    provider = llama_cpp_provider.LlamaCppGenerateProvider()
    cfg = provider._get_provider_config()
    request = GenerateRequest(
        messages=[{"role": "user", "content": "x"}],
        options={"num_predict": 256},
    )
    sampler = provider._sampler_from(request, cfg)
    # num_predict alias is normalised into max_tokens for llama-server.
    assert sampler["max_tokens"] == 256


# ---------------------------------------------------------------------------
# streaming
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.anyio
async def test_stream_yields_deltas_and_completes(force_config, monkeypatch):
    chunks = [
        {"choices": [{"delta": {"content": "Hel"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "lo"}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]

    async def fake_astream(**kwargs):
        for chunk in chunks:
            yield chunk

    monkeypatch.setattr(llama_cpp_provider.llama_client, "astream_chat_completion", fake_astream)

    provider = llama_cpp_provider.LlamaCppGenerateProvider()
    collected: list[str] = []
    done_seen = False
    async for chunk in provider.stream(
        GenerateRequest(
            messages=[{"role": "user", "content": "Hi"}],
            options={},
            metadata={},
        )
    ):
        if chunk.done:
            done_seen = True
        elif chunk.content:
            collected.append(chunk.content)

    assert collected == ["Hel", "lo"]
    assert done_seen is True


@pytest.fixture
def anyio_backend():
    return "asyncio"
