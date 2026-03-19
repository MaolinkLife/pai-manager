from __future__ import annotations

import io
import time
from typing import Optional

from modules.synthesis.providers.base import ImageProvider, ImageProviderError
from modules.synthesis.types import ImageGenerationRequest, ImageGenerationResult
from services.logger_service import AuditStatus, log_audit_entry


class ZImageTurboProvider(ImageProvider):
    name = "z_image_turbo"

    def __init__(self, model_id: str = "Tongyi-MAI/Z-Image-Turbo") -> None:
        self._model_id = model_id
        self._pipeline = None
        self._device = "cpu"

    def _resolve_torch_dtype(self, torch_module, device: str):
        if device == "cuda":
            if hasattr(torch_module, "bfloat16"):
                return torch_module.bfloat16
            return torch_module.float16
        return torch_module.float32

    def _build_pipeline(self):
        try:
            import torch
        except Exception as exc:  # pragma: no cover
            raise ImageProviderError(
                "PyTorch is required for Z-Image-Turbo provider."
            ) from exc

        try:
            from diffusers import ZImagePipeline
        except Exception as exc:  # pragma: no cover
            raise ImageProviderError(
                "ZImagePipeline is unavailable. Update diffusers to a version that supports Z-Image-Turbo."
            ) from exc

        device = "cuda" if torch.cuda.is_available() else "cpu"
        torch_dtype = self._resolve_torch_dtype(torch, device)

        started = time.time()
        pipe = ZImagePipeline.from_pretrained(
            self._model_id,
            torch_dtype=torch_dtype,
            low_cpu_mem_usage=False,
        )
        pipe.to(device)

        self._pipeline = pipe
        self._device = device

        log_audit_entry(
            "synthesis_z_image_loaded",
            "[Synthesis] Z-Image-Turbo pipeline loaded.",
            AuditStatus.INFO,
            details={
                "model_id": self._model_id,
                "device": device,
                "load_ms": int((time.time() - started) * 1000),
            },
        )

    def _get_pipeline(self):
        if self._pipeline is None:
            self._build_pipeline()
        return self._pipeline

    @staticmethod
    def _make_generator(torch_module, device: str, seed: Optional[int]):
        if seed is None:
            return None
        try:
            return torch_module.Generator(device=device).manual_seed(int(seed))
        except Exception:
            return torch_module.Generator().manual_seed(int(seed))

    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        if not request.prompt.strip():
            raise ImageProviderError("Prompt is required.")

        try:
            import torch
        except Exception as exc:  # pragma: no cover
            raise ImageProviderError(
                "PyTorch is required for Z-Image-Turbo provider."
            ) from exc

        pipe = self._get_pipeline()
        generator = self._make_generator(torch, self._device, request.seed)

        started = time.time()
        try:
            out = pipe(
                prompt=request.prompt,
                negative_prompt=request.negative_prompt,
                height=request.height,
                width=request.width,
                num_inference_steps=request.num_inference_steps,
                guidance_scale=request.guidance_scale,
                generator=generator,
            )
            image = out.images[0]
        except Exception as exc:
            raise ImageProviderError(f"Z-Image-Turbo generation failed: {exc}") from exc

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        data = buffer.getvalue()

        log_audit_entry(
            "synthesis_z_image_generated",
            "[Synthesis] Z-Image-Turbo image generated.",
            AuditStatus.INFO,
            details={
                "provider": self.name,
                "width": request.width,
                "height": request.height,
                "steps": request.num_inference_steps,
                "guidance_scale": request.guidance_scale,
                "seed": request.seed,
                "elapsed_ms": int((time.time() - started) * 1000),
                "image_size_bytes": len(data),
            },
        )

        return ImageGenerationResult(
            provider=self.name,
            image_bytes=data,
            mime_type="image/png",
            width=request.width,
            height=request.height,
            seed=request.seed,
        )

