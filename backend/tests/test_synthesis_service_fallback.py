import pytest

from modules.synthesis.providers.base import ImageProviderError
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
        return "z_image_turbo"

    def get_model(self, model_id):
        return self._models.get(model_id)

    def reload(self):
        return None


def _model(model_id, family, default=False):
    return SynthesisModelInfo(
        model_id=model_id,
        label=model_id,
        family=family,
        source="huggingface",
        installed=False,
        hf_repo_id=f"dummy/{model_id}",
        default=default,
        defaults={},
    )


def test_z_turbo_falls_back_to_stable_diffusion(monkeypatch):
    service = SynthesisService()
    service._registry = _RegistryStub(
        [
            _model("z_image_turbo", "z-image", default=True),
            _model("stable_diffusion_webui", "stable-diffusion-webui"),
            _model("stable_diffusion_v1_5", "stable-diffusion"),
        ]
    )

    diffusers_calls = []
    webui_calls = []

    def fake_diffusers_generate(request, model):
        diffusers_calls.append(model.model_id)
        if model.model_id == "z_image_turbo":
            raise ImageProviderError("z turbo crash")
        return ImageGenerationResult(
            provider=request.provider,
            model_id=model.model_id,
            image_bytes=b"ok",
            width=request.width,
            height=request.height,
        )

    def fake_webui_generate(request, model):
        webui_calls.append(model.model_id)
        return ImageGenerationResult(
            provider="stable_diffusion_webui",
            model_id=model.model_id,
            image_bytes=b"ok",
            width=request.width,
            height=request.height,
        )

    monkeypatch.setattr(service._provider, "generate", fake_diffusers_generate)
    monkeypatch.setattr(service._sd_webui_provider, "generate", fake_webui_generate)

    result = service.generate_image(
        ImageGenerationRequest(prompt="test prompt", allow_fallback=True)
    )

    assert diffusers_calls == ["z_image_turbo"]
    assert webui_calls == ["stable_diffusion_webui"]
    assert result.model_id == "stable_diffusion_webui"
    assert result.provider == "stable_diffusion_webui"


def test_z_turbo_tries_next_fallback_when_webui_fails(monkeypatch):
    service = SynthesisService()
    service._registry = _RegistryStub(
        [
            _model("z_image_turbo", "z-image", default=True),
            _model("stable_diffusion_webui", "stable-diffusion-webui"),
            _model("stable_diffusion_v1_5", "stable-diffusion"),
        ]
    )

    diffusers_calls = []
    webui_calls = []

    def fake_diffusers_generate(request, model):
        diffusers_calls.append(model.model_id)
        if model.model_id == "z_image_turbo":
            raise ImageProviderError("z turbo crash")
        return ImageGenerationResult(
            provider=request.provider,
            model_id=model.model_id,
            image_bytes=b"ok",
            width=request.width,
            height=request.height,
        )

    def fake_webui_generate(request, model):
        webui_calls.append(model.model_id)
        raise ImageProviderError("webui disabled")

    monkeypatch.setattr(service._provider, "generate", fake_diffusers_generate)
    monkeypatch.setattr(service._sd_webui_provider, "generate", fake_webui_generate)

    result = service.generate_image(
        ImageGenerationRequest(prompt="test prompt", allow_fallback=True)
    )

    assert webui_calls == ["stable_diffusion_webui"]
    assert diffusers_calls == ["z_image_turbo", "stable_diffusion_v1_5"]
    assert result.model_id == "stable_diffusion_v1_5"


def test_z_turbo_strict_mode_does_not_fall_back(monkeypatch):
    service = SynthesisService()
    service._registry = _RegistryStub(
        [
            _model("z_image_turbo", "z-image", default=True),
            _model("stable_diffusion_v1_5", "stable-diffusion"),
        ]
    )

    diffusers_calls = []

    def fake_diffusers_generate(request, model):
        diffusers_calls.append(model.model_id)
        raise ImageProviderError("z turbo crash")

    monkeypatch.setattr(service._provider, "generate", fake_diffusers_generate)

    with pytest.raises(ImageProviderError, match="z turbo crash"):
        service.generate_image(
            ImageGenerationRequest(prompt="test prompt", allow_fallback=False)
        )

    assert diffusers_calls == ["z_image_turbo"]


def test_diffusers_provider_selects_requested_model(monkeypatch):
    service = SynthesisService()
    service._registry = _RegistryStub(
        [
            _model("z_image_turbo", "z-image", default=True),
            _model("stable_diffusion_v1_5", "stable-diffusion"),
        ]
    )

    calls = []

    def fake_diffusers_generate(request, model):
        calls.append((request.provider, request.model, model.model_id))
        return ImageGenerationResult(
            provider=request.provider,
            model_id=model.model_id,
            image_bytes=b"ok",
        )

    monkeypatch.setattr(service._provider, "generate", fake_diffusers_generate)

    result = service.generate_image(
        ImageGenerationRequest(
            prompt="test prompt",
            provider="diffusers",
            model="z_image_turbo",
            allow_fallback=False,
        )
    )

    assert calls == [("diffusers", "z_image_turbo", "z_image_turbo")]
    assert result.provider == "diffusers"
    assert result.model_id == "z_image_turbo"


def test_legacy_model_id_provider_still_selects_model(monkeypatch):
    service = SynthesisService()
    service._registry = _RegistryStub([_model("z_image_turbo", "z-image", default=True)])

    calls = []

    def fake_diffusers_generate(request, model):
        calls.append((request.provider, request.model, model.model_id))
        return ImageGenerationResult(
            provider=request.provider,
            model_id=model.model_id,
            image_bytes=b"ok",
        )

    monkeypatch.setattr(service._provider, "generate", fake_diffusers_generate)

    result = service.generate_image(
        ImageGenerationRequest(
            prompt="test prompt",
            provider="z_image_turbo",
            allow_fallback=False,
        )
    )

    assert calls == [("diffusers", "z_image_turbo", "z_image_turbo")]
    assert result.provider == "diffusers"
