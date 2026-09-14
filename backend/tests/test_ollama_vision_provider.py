import base64
import io

import pytest
from PIL import Image

import modules.vision.providers.ollama_vision as ollama_vision
from modules.vision.providers.ollama_vision import OllamaVisionProvider


pytestmark = pytest.mark.regression


def _vision_model(monkeypatch, *capabilities):
    monkeypatch.setattr(ollama_vision.ollama_client, "is_available", lambda: True)
    monkeypatch.setattr(
        ollama_vision.ollama_client,
        "model_supports_vision",
        lambda model: {"supported": "vision" in capabilities, "capabilities": list(capabilities)},
    )


def _no_generation(*args, **kwargs):
    raise AssertionError("a model is not run to check what it can do")


def test_readiness_asks_only_the_metadata(monkeypatch):
    """No test image is sent to find out whether a model can see."""
    _vision_model(monkeypatch, "completion", "vision")
    monkeypatch.setattr(ollama_vision.ollama_client, "chat_image_response", _no_generation)
    monkeypatch.setattr(ollama_vision.ollama_client, "chat_image", _no_generation)

    assert OllamaVisionProvider({"model": "qwen-vl:test"}).is_ready() is True


def test_a_model_that_does_not_declare_vision_is_unavailable(monkeypatch):
    monkeypatch.setattr(ollama_vision.ollama_client, "is_available", lambda: True)
    monkeypatch.setattr(
        ollama_vision.ollama_client,
        "model_supports_vision",
        lambda model: {"supported": False, "reason": "model metadata does not declare vision", "capabilities": ["completion"]},
    )
    monkeypatch.setattr(ollama_vision.ollama_client, "chat_image_response", _no_generation)
    monkeypatch.setattr(ollama_vision, "log_audit_entry", lambda *args, **kwargs: None)
    provider = OllamaVisionProvider({"model": "llava:latest"})

    assert provider.is_ready() is False
    assert provider._last_probe_error == "model metadata does not declare vision"


def test_ollama_vision_describe_image_uses_configured_format(monkeypatch):
    captured = {}

    def fake_chat_image_response(messages, model=None, options=None, keep_alive=None):
        captured["messages"] = messages
        captured["model"] = model
        captured["options"] = options
        captured["keep_alive"] = keep_alive
        return {"content": "The image shows a simple test shape.", "thinking": "", "done_reason": "stop"}

    _vision_model(monkeypatch, "completion", "vision")
    monkeypatch.setattr(ollama_vision.ollama_client, "chat_image_response", fake_chat_image_response)

    provider = OllamaVisionProvider(
        {
            "model": "qwen-vl:test",
            "max_tokens": 88,
            "image_format": "PNG",
            "keep_alive": "5m",
        }
    )
    image = Image.new("RGB", (32, 32), "red")

    result = provider.describe_image(image, "Describe this image.")

    assert result["status"] == "success"
    assert result["summary"] == "The image shows a simple test shape."
    assert captured["model"] == "qwen-vl:test"
    assert captured["keep_alive"] == "5m"
    assert captured["options"]["num_predict"] == 88

    encoded = captured["messages"][0]["images"][0]
    raw = base64.b64decode(encoded)
    with Image.open(io.BytesIO(raw)) as encoded_image:
        assert encoded_image.format == "PNG"
