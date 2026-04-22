import pytest

from modules.synthesis.providers.stable_diffusion_webui import StableDiffusionWebUIProvider
from modules.synthesis.types import ImageGenerationRequest, SynthesisModelInfo


pytestmark = pytest.mark.regression


class _FakeResponse:
    def __init__(self):
        self._payload = {"images": ["aGVsbG8="]}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_sd_webui_provider_uses_config_values(monkeypatch):
    config_values = {
        "synthesis.sd_webui.enabled": True,
        "synthesis.sd_webui.base_url": "http://sd.local:7860",
        "synthesis.sd_webui.bearer_token": "secret-token",
        "synthesis.sd_webui.timeout_sec": 77,
        "synthesis.sd_webui.checkpoint": "anime.safetensors",
        "synthesis.sd_webui.sampler_name": "Euler a",
        "synthesis.sd_webui.scheduler": "Karras",
        "synthesis.sd_webui.cfg_scale_default": 3.3,
    }

    def fake_get_config_value(path, default=None):
        return config_values.get(path, default)

    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(
        "modules.synthesis.providers.stable_diffusion_webui.get_config_value",
        fake_get_config_value,
    )
    monkeypatch.setattr(
        "modules.synthesis.providers.stable_diffusion_webui.requests.post",
        fake_post,
    )

    provider = StableDiffusionWebUIProvider()
    model = SynthesisModelInfo(
        model_id="stable_diffusion_webui",
        label="Stable Diffusion WebUI API",
        family="stable-diffusion-webui",
        source="remote",
        installed=True,
    )
    result = provider.generate(
        ImageGenerationRequest(
            prompt="test prompt",
            guidance_scale=0.0,
            width=512,
            height=512,
            num_inference_steps=12,
        ),
        model,
    )

    assert captured["url"] == "http://sd.local:7860/sdapi/v1/txt2img"
    assert captured["timeout"] == 77
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert captured["json"]["override_settings"]["sd_model_checkpoint"] == "anime.safetensors"
    assert captured["json"]["sampler_name"] == "Euler a"
    assert captured["json"]["scheduler"] == "Karras"
    assert captured["json"]["cfg_scale"] == 3.3
    assert result.provider == "stable_diffusion_webui"
    assert result.image_bytes == b"hello"
