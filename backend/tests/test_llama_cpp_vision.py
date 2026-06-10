"""Unit tests for the llama.cpp vision provider.

We don't talk to a real llama-server — modules.llama_cpp.client.ping and
chat_completion are patched. The tests verify:

  * disabled provider stays not_ready and exposes a useful error message
  * enabled + reachable + valid response returns status=success
  * enabled + unreachable returns status=not_ready (ping fails)
  * enabled + transport exception returns status=error (not raise)
  * VisualModule factory routes vision.active_provider="llama_cpp_vision"
    to the new adapter (regression against the if/elif chain).
"""

from __future__ import annotations

from typing import Any

import pytest
from PIL import Image

from modules.vision.providers import llama_cpp_vision as vision_module
from modules.vision.providers.llama_cpp_vision import LlamaCppVisionProvider


@pytest.fixture
def sample_image():
    return Image.new("RGB", (32, 32), color="white")


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_disabled_provider_not_ready():
    provider = LlamaCppVisionProvider({"enabled": False})
    assert provider.is_ready() is False
    assert "disabled" in provider._last_error.lower()


@pytest.mark.regression
def test_enabled_but_unreachable_not_ready(monkeypatch):
    monkeypatch.setattr(vision_module.llama_client, "ping", lambda **_: False)
    provider = LlamaCppVisionProvider({"enabled": True, "base_url": "http://test:9999"})
    assert provider.is_ready() is False
    assert "not reachable" in provider._last_error.lower()


@pytest.mark.regression
def test_ping_exception_handled(monkeypatch):
    def _raise(**_):
        raise RuntimeError("boom")

    monkeypatch.setattr(vision_module.llama_client, "ping", _raise)
    provider = LlamaCppVisionProvider({"enabled": True})
    assert provider.is_ready() is False
    assert "ping failed" in provider._last_error.lower()


# ---------------------------------------------------------------------------
# describe_image
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_describe_image_success(sample_image, monkeypatch):
    monkeypatch.setattr(vision_module.llama_client, "ping", lambda **_: True)

    captured: dict[str, Any] = {}

    def fake_chat(**kwargs):
        captured.update(kwargs)
        return {
            "choices": [
                {"message": {"role": "assistant", "content": "A small white square."}}
            ]
        }

    monkeypatch.setattr(vision_module.llama_client, "chat_completion", fake_chat)

    provider = LlamaCppVisionProvider({"enabled": True, "model": "test-vision"})
    result = provider.describe_image(sample_image, "Describe.")

    assert result["status"] == "success"
    assert result["summary"] == "A small white square."
    assert result["model"] == "test-vision"
    # Multimodal payload shape: content is a list with text + image_url.
    user_msg = captured["messages"][0]
    assert user_msg["role"] == "user"
    assert isinstance(user_msg["content"], list)
    types = [part.get("type") for part in user_msg["content"]]
    assert "text" in types and "image_url" in types
    # Data URL includes the image_format header.
    image_part = next(p for p in user_msg["content"] if p.get("type") == "image_url")
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.regression
def test_describe_image_not_ready_short_circuits(sample_image, monkeypatch):
    monkeypatch.setattr(vision_module.llama_client, "ping", lambda **_: False)
    # If chat_completion is called when not_ready, the test fails on the noop.
    monkeypatch.setattr(
        vision_module.llama_client,
        "chat_completion",
        lambda **_: pytest.fail("chat_completion must not run when not ready"),
    )

    provider = LlamaCppVisionProvider({"enabled": True})
    result = provider.describe_image(sample_image, "Describe.")
    assert result["status"] == "not_ready"


@pytest.mark.regression
def test_describe_image_transport_error_returns_error(sample_image, monkeypatch):
    monkeypatch.setattr(vision_module.llama_client, "ping", lambda **_: True)

    def _raise(**_):
        raise RuntimeError("backend timeout")

    monkeypatch.setattr(vision_module.llama_client, "chat_completion", _raise)

    provider = LlamaCppVisionProvider({"enabled": True})
    result = provider.describe_image(sample_image, "Describe.")
    assert result["status"] == "error"
    assert "timeout" in result["summary"].lower()


@pytest.mark.regression
def test_describe_image_empty_response_marked_error(sample_image, monkeypatch):
    monkeypatch.setattr(vision_module.llama_client, "ping", lambda **_: True)
    monkeypatch.setattr(
        vision_module.llama_client,
        "chat_completion",
        lambda **_: {"choices": [{"message": {"content": "   "}}]},
    )

    provider = LlamaCppVisionProvider({"enabled": True})
    result = provider.describe_image(sample_image, "Describe.")
    assert result["status"] == "error"


@pytest.mark.regression
def test_jpeg_format_changes_data_url(sample_image, monkeypatch):
    monkeypatch.setattr(vision_module.llama_client, "ping", lambda **_: True)
    captured: dict[str, Any] = {}

    def fake_chat(**kwargs):
        captured.update(kwargs)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(vision_module.llama_client, "chat_completion", fake_chat)

    provider = LlamaCppVisionProvider({"enabled": True, "image_format": "JPEG"})
    provider.describe_image(sample_image, "Describe.")
    image_part = next(
        p for p in captured["messages"][0]["content"] if p.get("type") == "image_url"
    )
    assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")


# ---------------------------------------------------------------------------
# Factory wiring
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_visual_module_routes_llama_cpp_vision(monkeypatch):
    """vision.active_provider="llama_cpp_vision" must build LlamaCppVisionProvider."""
    from modules.vision import visual_module as vm_mod

    monkeypatch.setattr(
        vm_mod.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: {
            "vision.active_provider": "llama_cpp_vision",
            "vision.vision_modules.llama_cpp_vision": {"enabled": False, "base_url": "http://x"},
        }.get(path, default),
    )

    module = vm_mod.VisualModule()
    assert isinstance(module.provider, LlamaCppVisionProvider)
    assert module.provider.base_url == "http://x"
