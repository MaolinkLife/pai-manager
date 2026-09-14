"""Vision against the real Ollama.

Skipped with the reason when Ollama is not running or no installed model
declares vision: a service that is switched off is not a failure.
"""

import pytest
import requests
from PIL import Image, ImageDraw

from modules.ollama import client as ollama_client
from modules.vision.providers.ollama_vision import OllamaVisionProvider

pytestmark = [pytest.mark.live, pytest.mark.live_ollama]


@pytest.fixture(scope="module")
def vision_model():
    if not ollama_client.is_available():
        pytest.skip("Ollama is not running")
    tags = requests.get(f"{ollama_client.OLLAMA_API_URL}/tags", timeout=10).json()
    # The smallest model that can see keeps the check light on a shared GPU.
    for model in sorted(tags.get("models", []), key=lambda item: int(item.get("size") or 0)):
        name = str(model.get("name") or "")
        if name and ollama_client.model_supports_vision(name).get("supported"):
            return name
    pytest.skip("no installed Ollama model declares vision in its metadata")


def test_a_model_that_declares_vision_passes_the_probe(vision_model):
    provider = OllamaVisionProvider({"model": vision_model, "max_tokens": 256})

    assert provider.is_ready(), f"{vision_model}: {provider._last_probe_error}"


def test_a_real_image_gets_a_real_description(vision_model):
    image = Image.new("RGB", (256, 256), "white")
    ImageDraw.Draw(image).rectangle((48, 48, 208, 208), fill=(220, 40, 40))
    provider = OllamaVisionProvider({"model": vision_model, "max_tokens": 256})

    result = provider.describe_image(image, "What colour is the square? Answer with one English word.")

    assert result["status"] == "success", result
    assert "red" in result["summary"].lower(), result["summary"]
