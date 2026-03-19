from __future__ import annotations

from dataclasses import asdict
from typing import List

from modules.synthesis.model_registry import SynthesisModelRegistry
from modules.synthesis.providers.diffusers_generic import DiffusersGenericProvider
from modules.synthesis.providers.base import ImageProviderError
from modules.synthesis.types import (
    ImageGenerationRequest,
    ImageGenerationResult,
    SynthesisModelInfo,
)
from services.logger_service import AuditStatus, log_audit_entry


class SynthesisService:
    def __init__(self) -> None:
        self._registry = SynthesisModelRegistry()
        self._provider = DiffusersGenericProvider()

    def list_models(self, refresh: bool = False) -> List[SynthesisModelInfo]:
        if refresh:
            self._registry.reload()
        return self._registry.list_models()

    def get_image_providers(self) -> list[str]:
        return sorted({model.model_id for model in self._registry.list_models()})

    def _resolve_target_model(self, request: ImageGenerationRequest) -> SynthesisModelInfo:
        model_id = (request.model or request.provider or "").strip().lower()
        if not model_id:
            default_model_id = self._registry.get_default_model_id()
            if not default_model_id:
                raise ImageProviderError("No image models are registered.")
            model_id = default_model_id

        model = self._registry.get_model(model_id)
        if model is None:
            available = ", ".join(m.model_id for m in self._registry.list_models())
            raise ImageProviderError(
                f"Unknown image model '{model_id}'. Available: {available}"
            )
        return model

    def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        model = self._resolve_target_model(request)
        provider_name = model.family.replace("-", "_")
        request.provider = provider_name
        request.model = model.model_id

        log_audit_entry(
            "synthesis_generate_image_start",
            "[Synthesis] Start image generation.",
            AuditStatus.INFO,
            details={
                "provider": provider_name,
                "model_id": model.model_id,
                "width": request.width,
                "height": request.height,
            },
        )
        return self._provider.generate(request, model)

    def dump_models_payload(self, refresh: bool = False) -> list[dict]:
        return [asdict(model) for model in self.list_models(refresh=refresh)]


synthesis_service = SynthesisService()
