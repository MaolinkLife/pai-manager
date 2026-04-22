import pytest

from modules.synthesis.service import SynthesisService
from modules.synthesis.types import (
    ImageGenerationRequest,
    ImageGenerationResult,
    SynthesisModelInfo,
)


pytestmark = pytest.mark.regression


class _RegistryStub:
    def __init__(self, models):
        self._models = {model.model_id: model for model in models}

    def list_models(self):
        return [self._models[key] for key in sorted(self._models.keys())]

    def get_default_model_id(self):
        return "stable_diffusion_webui"

    def get_model(self, model_id):
        return self._models.get(model_id)

    def reload(self):
        return None


def _model(model_id, family, default=False):
    return SynthesisModelInfo(
        model_id=model_id,
        label=model_id,
        family=family,
        source="remote",
        installed=True,
        default=default,
        defaults={},
    )


def test_webui_model_uses_webui_provider(monkeypatch):
    service = SynthesisService()
    service._registry = _RegistryStub(
        [_model("stable_diffusion_webui", "stable-diffusion-webui", default=True)]
    )

    called = {"webui": 0, "diffusers": 0}

    def fake_webui_generate(request, model):
        called["webui"] += 1
        return ImageGenerationResult(
            provider="stable_diffusion_webui",
            model_id=model.model_id,
            image_bytes=b"img",
            width=request.width,
            height=request.height,
        )

    def fake_diffusers_generate(request, model):
        called["diffusers"] += 1
        return ImageGenerationResult(
            provider="diffusers",
            model_id=model.model_id,
            image_bytes=b"img",
            width=request.width,
            height=request.height,
        )

    monkeypatch.setattr(service._sd_webui_provider, "generate", fake_webui_generate)
    monkeypatch.setattr(service._provider, "generate", fake_diffusers_generate)

    result = service.generate_image(
        ImageGenerationRequest(prompt="hello", model="stable_diffusion_webui")
    )

    assert result.provider == "stable_diffusion_webui"
    assert called["webui"] == 1
    assert called["diffusers"] == 0
