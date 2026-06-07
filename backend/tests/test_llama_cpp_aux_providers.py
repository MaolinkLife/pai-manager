"""Tests for the llama.cpp adapters in analyzer + moral_matrix domains.

These mirror the test_llama_cpp_provider.py shape — same idea, different
interfaces. The whole point is parity: a user who can pick llama.cpp for the
chat model can also pick it for analyzer / moral evaluations.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from modules.analyzer.providers import llama_cpp as analyzer_llama
from modules.moral_matrix.providers import llama_cpp as moral_llama


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def analyzer_cfg(monkeypatch):
    state = {
        "enabled": True,
        "base_url": "http://test-llama:9999",
        "model": "analyzer.gguf",
        "temperature": 0.2,
        "max_tokens": 256,
        "request_timeout": 10,
    }

    def _setter(**overrides):
        state.update(overrides)

    monkeypatch.setattr(
        analyzer_llama.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: (
            state if path == "analyzer.providers.llama_cpp"
            else "ANALYZE THE INPUT" if path == "analyzer.system_prompt"
            else default
        ),
    )
    return _setter


@pytest.fixture
def moral_cfg(monkeypatch):
    state = {
        "enabled": True,
        "base_url": "http://test-llama:9999",
        "model": "moral.gguf",
        "temperature": 0.4,
        "max_tokens": 128,
        "request_timeout": 10,
    }

    def _setter(**overrides):
        state.update(overrides)

    monkeypatch.setattr(
        moral_llama.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: (
            state if path == "moral.providers.llama_cpp"
            else "EVALUATE THE PAYLOAD" if path == "moral.system_prompt"
            else default
        ),
    )
    return _setter


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_analyzer_provider_disabled_by_default(monkeypatch):
    monkeypatch.setattr(
        analyzer_llama.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: {"enabled": False} if path == "analyzer.providers.llama_cpp" else default,
    )
    provider = analyzer_llama.LlamaCppAnalyzerProvider()
    assert provider.is_available() is False


@pytest.mark.regression
def test_moral_provider_disabled_by_default(monkeypatch):
    monkeypatch.setattr(
        moral_llama.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: {"enabled": False} if path == "moral.providers.llama_cpp" else default,
    )
    provider = moral_llama.LlamaCppMoralProvider()
    assert provider.is_available() is False


@pytest.mark.regression
def test_analyzer_provider_enabled_when_flag_set(analyzer_cfg):
    provider = analyzer_llama.LlamaCppAnalyzerProvider()
    assert provider.is_available() is True


@pytest.mark.regression
def test_moral_provider_enabled_when_flag_set(moral_cfg):
    provider = moral_llama.LlamaCppMoralProvider()
    assert provider.is_available() is True


# ---------------------------------------------------------------------------
# Analyzer analyze()
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.anyio
async def test_analyzer_analyze_parses_json_response(analyzer_cfg, monkeypatch):
    captured: dict[str, Any] = {}

    def fake_chat(**kwargs):
        captured.update(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps({"emotion": "joy", "intent": "share"}),
                    }
                }
            ]
        }

    monkeypatch.setattr(analyzer_llama.llama_client, "chat_completion", fake_chat)

    provider = analyzer_llama.LlamaCppAnalyzerProvider()
    result = await provider.analyze("Hello!", {"media_count": 0})

    assert result == {"emotion": "joy", "intent": "share"}
    assert captured["base_url"] == "http://test-llama:9999"
    assert captured["model"] == "analyzer.gguf"
    # System prompt + user JSON payload both present.
    assert captured["messages"][0]["role"] == "system"
    assert captured["messages"][1]["role"] == "user"
    assert "hasMedia" in captured["messages"][1]["content"]


@pytest.mark.regression
@pytest.mark.anyio
async def test_analyzer_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(
        analyzer_llama.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: {"enabled": False} if path == "analyzer.providers.llama_cpp" else default,
    )
    provider = analyzer_llama.LlamaCppAnalyzerProvider()
    result = await provider.analyze("Hello!", {})
    assert result is None


@pytest.mark.regression
@pytest.mark.anyio
async def test_analyzer_returns_none_on_empty_assistant(analyzer_cfg, monkeypatch):
    def fake_chat(**kwargs):
        return {"choices": [{"message": {"content": "  "}}]}

    monkeypatch.setattr(analyzer_llama.llama_client, "chat_completion", fake_chat)

    provider = analyzer_llama.LlamaCppAnalyzerProvider()
    # provider.analyze() catches the ValueError and returns None.
    result = await provider.analyze("x", {})
    assert result is None


# ---------------------------------------------------------------------------
# Moral run()
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.anyio
async def test_moral_run_parses_json_response(moral_cfg, monkeypatch):
    def fake_chat(**kwargs):
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps({"verdict": "neutral", "weight": 0.5}),
                    }
                }
            ]
        }

    monkeypatch.setattr(moral_llama.llama_client, "chat_completion", fake_chat)

    provider = moral_llama.LlamaCppMoralProvider()
    result = await provider.run({"text": "hello"})
    assert result == {"verdict": "neutral", "weight": 0.5}


@pytest.mark.regression
@pytest.mark.anyio
async def test_moral_run_strips_code_fence(moral_cfg, monkeypatch):
    """parse_provider_json tolerates ``` fences around the JSON body."""
    def fake_chat(**kwargs):
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "```json\n{\"verdict\":\"ok\"}\n```",
                    }
                }
            ]
        }

    monkeypatch.setattr(moral_llama.llama_client, "chat_completion", fake_chat)

    provider = moral_llama.LlamaCppMoralProvider()
    result = await provider.run({"text": "hello"})
    assert result == {"verdict": "ok"}


@pytest.mark.regression
@pytest.mark.anyio
async def test_moral_run_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(
        moral_llama.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: {"enabled": False} if path == "moral.providers.llama_cpp" else default,
    )
    provider = moral_llama.LlamaCppMoralProvider()
    result = await provider.run({"text": "x"})
    assert result is None
