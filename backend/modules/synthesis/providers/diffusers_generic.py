from __future__ import annotations

import io
import os
import time
from typing import Dict, Tuple

from modules.synthesis.providers.base import ImageProviderError
from modules.synthesis.types import (
    ImageGenerationRequest,
    ImageGenerationResult,
    SynthesisModelInfo,
)
from services.logger_service import AuditStatus, log_audit_entry


class DiffusersGenericProvider:
    def __init__(self) -> None:
        self._cache: Dict[str, object] = {}
        self._cache_device: Dict[str, str] = {}

    def _resolve_model_ref(self, model: SynthesisModelInfo) -> str:
        if model.source == "local":
            if model.path and os.path.isdir(model.path):
                return model.path
            raise ImageProviderError(
                f"Local model '{model.model_id}' is not installed or path is invalid."
            )
        if model.hf_repo_id:
            return model.hf_repo_id
        raise ImageProviderError(
            f"Model '{model.model_id}' has no local path and no Hugging Face repo id."
        )

    def _pick_device_dtype(self):
        try:
            import torch
        except Exception as exc:  # pragma: no cover
            raise ImageProviderError("PyTorch is required for image synthesis.") from exc

        device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cuda":
            dtype = torch.bfloat16 if hasattr(torch, "bfloat16") else torch.float16
        else:
            dtype = torch.float32
        return torch, device, dtype

    def _build_pipeline(self, model: SynthesisModelInfo):
        model_ref = self._resolve_model_ref(model)
        torch, device, dtype = self._pick_device_dtype()

        started = time.time()
        try:
            if model.family == "z-image":
                from diffusers import ZImagePipeline

                pipe = ZImagePipeline.from_pretrained(
                    model_ref,
                    torch_dtype=dtype,
                    low_cpu_mem_usage=False,
                )
            else:
                from diffusers import AutoPipelineForText2Image

                pipe = AutoPipelineForText2Image.from_pretrained(
                    model_ref,
                    torch_dtype=dtype,
                )
        except Exception as exc:
            raise ImageProviderError(
                f"Failed to load model '{model.model_id}' from '{model_ref}': {exc}"
            ) from exc

        pipe.to(device)

        log_audit_entry(
            "synthesis_diffusers_pipeline_loaded",
            "[Synthesis] Diffusers pipeline loaded.",
            AuditStatus.INFO,
            details={
                "model_id": model.model_id,
                "family": model.family,
                "device": device,
                "source": model.source,
                "model_ref": model_ref,
                "load_ms": int((time.time() - started) * 1000),
            },
        )
        return pipe, device

    def _get_pipeline(self, model: SynthesisModelInfo) -> Tuple[object, str]:
        if model.model_id not in self._cache:
            pipe, device = self._build_pipeline(model)
            self._cache[model.model_id] = pipe
            self._cache_device[model.model_id] = device
        return self._cache[model.model_id], self._cache_device[model.model_id]

    def _merge_with_defaults(self, request: ImageGenerationRequest, model: SynthesisModelInfo) -> ImageGenerationRequest:
        defaults = model.defaults or {}
        width = int(defaults.get("width", request.width))
        height = int(defaults.get("height", request.height))
        steps = int(defaults.get("num_inference_steps", request.num_inference_steps))
        guidance = float(defaults.get("guidance_scale", request.guidance_scale))

        # Request values should override defaults if explicitly set by caller.
        if request.width:
            width = request.width
        if request.height:
            height = request.height
        if request.num_inference_steps:
            steps = request.num_inference_steps
        guidance = request.guidance_scale if request.guidance_scale is not None else guidance

        return ImageGenerationRequest(
            prompt=request.prompt,
            provider=request.provider,
            model=request.model,
            negative_prompt=request.negative_prompt,
            width=width,
            height=height,
            num_inference_steps=steps,
            guidance_scale=guidance,
            seed=request.seed,
        )

    def generate(
        self,
        request: ImageGenerationRequest,
        model: SynthesisModelInfo,
    ) -> ImageGenerationResult:
        if not request.prompt.strip():
            raise ImageProviderError("Prompt is required.")

        request = self._merge_with_defaults(request, model)
        pipe, device = self._get_pipeline(model)

        generator = None
        if request.seed is not None:
            try:
                import torch

                generator = torch.Generator(device=device).manual_seed(int(request.seed))
            except Exception:
                generator = None

        started = time.time()
        try:
            output = pipe(
                prompt=request.prompt,
                negative_prompt=request.negative_prompt,
                height=request.height,
                width=request.width,
                num_inference_steps=request.num_inference_steps,
                guidance_scale=request.guidance_scale,
                generator=generator,
            )
            image = output.images[0]
        except Exception as exc:
            raise ImageProviderError(
                f"Image generation failed for model '{model.model_id}': {exc}"
            ) from exc

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()

        log_audit_entry(
            "synthesis_image_generated",
            "[Synthesis] Image generated.",
            AuditStatus.INFO,
            details={
                "model_id": model.model_id,
                "family": model.family,
                "provider": request.provider,
                "width": request.width,
                "height": request.height,
                "steps": request.num_inference_steps,
                "guidance_scale": request.guidance_scale,
                "seed": request.seed,
                "elapsed_ms": int((time.time() - started) * 1000),
                "bytes": len(image_bytes),
            },
        )

        return ImageGenerationResult(
            provider=request.provider,
            model_id=model.model_id,
            image_bytes=image_bytes,
            mime_type="image/png",
            width=request.width,
            height=request.height,
            seed=request.seed,
        )
