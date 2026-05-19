import base64
import io

import pytest
from PIL import Image

import modules.vision.providers.ollama_vision as ollama_vision
from modules.vision.providers.ollama_vision import OllamaVisionProvider


pytestmark = pytest.mark.regression


def test_ollama_vision_probe_uses_real_png_fixture(monkeypatch):
    captured = {}

    def fake_chat_image(messages, model=None, options=None, keep_alive=None):
        captured["messages"] = messages
        captured["model"] = model
        captured["options"] = options
        captured["keep_alive"] = keep_alive
        return "A red rectangle, a blue circle, and VISION TEST text."

    monkeypatch.setattr(ollama_vision.ollama_client, "is_available", lambda: True)
    monkeypatch.setattr(ollama_vision.ollama_client, "chat_image", fake_chat_image)

    provider = OllamaVisionProvider(
        {
            "model": "qwen-vl:test",
            "max_tokens": 120,
            "keep_alive": "5m",
        }
    )

    assert provider.is_ready() is True
    assert captured["model"] == "qwen-vl:test"
    assert captured["keep_alive"] == "5m"
    assert captured["options"]["num_predict"] >= 48

    encoded = captured["messages"][0]["images"][0]
    raw = base64.b64decode(encoded)
    with Image.open(io.BytesIO(raw)) as image:
        assert image.format == "PNG"
        assert image.size == (256, 256)


def test_ollama_vision_describe_image_uses_configured_format(monkeypatch):
    captured = {}

    def fake_chat_image(messages, model=None, options=None, keep_alive=None):
        captured["messages"] = messages
        captured["model"] = model
        captured["options"] = options
        captured["keep_alive"] = keep_alive
        return "The image shows a simple test shape."

    monkeypatch.setattr(ollama_vision.ollama_client, "is_available", lambda: True)
    monkeypatch.setattr(ollama_vision.ollama_client, "chat_image", fake_chat_image)

    provider = OllamaVisionProvider(
        {
            "model": "qwen-vl:test",
            "max_tokens": 88,
            "probe_enabled": False,
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
