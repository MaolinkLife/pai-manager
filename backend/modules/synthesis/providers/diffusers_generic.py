from __future__ import annotations

import io
import gc
import os
import threading
import time
from pathlib import Path
from typing import Tuple

from constants.paths import STORAGE_DIR
from modules.synthesis.providers.base import ImageProviderError
from modules.synthesis.types import (
    ImageGenerationRequest,
    ImageGenerationResult,
    SynthesisModelInfo,
)
from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry


class DiffusersGenericProvider:
    def __init__(self) -> None:
        self._cache_lock = threading.Lock()
        self._cached_pipeline: object | None = None
        self._cached_device: str = ""
        self._cached_key: tuple[str, str, str, str] | None = None

    def _keep_loaded(self) -> bool:
        return bool(config_service.get_config_value("synthesis.diffusers.keep_loaded", True))

    def _save_output_image(self, image_bytes: bytes, model_id: str, seed: int | None) -> str:
        output_root = Path(STORAGE_DIR) / "outputs" / "images"
        output_root.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        safe_model = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in model_id)[:80]
        filename = f"{timestamp}_{safe_model}_{seed if seed is not None else 'random'}.png"
        path = output_root / filename
        path.write_bytes(image_bytes)
        return path.relative_to(Path(STORAGE_DIR)).as_posix()

    def _resolve_model_ref(self, model: SynthesisModelInfo) -> str:
        if model.source == "local":
            if model.path and (os.path.isdir(model.path) or os.path.isfile(model.path)):
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

    def _apply_scheduler(self, pipe: object, scheduler_name: str | None) -> None:
        name = str(scheduler_name or "").strip().lower()
        if not name:
            return
        scheduler_map = {
            "euler": "EulerDiscreteScheduler",
            "euler_a": "EulerAncestralDiscreteScheduler",
            "euler ancestral": "EulerAncestralDiscreteScheduler",
            "dpmpp_2m": "DPMSolverMultistepScheduler",
            "dpm++ 2m": "DPMSolverMultistepScheduler",
            "ddim": "DDIMScheduler",
            "pndm": "PNDMScheduler",
            "lms": "LMSDiscreteScheduler",
        }
        class_name = scheduler_map.get(name)
        if not class_name:
            return
        try:
            import diffusers

            scheduler_cls = getattr(diffusers, class_name)
            pipe.scheduler = scheduler_cls.from_config(pipe.scheduler.config)
        except Exception as exc:
            log_audit_entry(
                "synthesis_scheduler_apply_failed",
                "[Synthesis] Failed to apply scheduler; using pipeline default.",
                AuditStatus.WARNING,
                details={"scheduler": scheduler_name, "error": str(exc)},
            )

    def _apply_vae(self, pipe: object, model: SynthesisModelInfo, dtype: object) -> None:
        vae_path = str(getattr(model, "vae_path", "") or "").strip()
        if not vae_path:
            return
        path = Path(vae_path)
        if not path.exists():
            log_audit_entry(
                "synthesis_vae_missing",
                "[Synthesis] Configured VAE path does not exist; using pipeline default VAE.",
                AuditStatus.WARNING,
                details={"model_id": model.model_id, "vae_path": vae_path},
            )
            return
        try:
            from diffusers import AutoencoderKL

            if path.is_file():
                pipe.vae = AutoencoderKL.from_single_file(
                    str(path),
                    torch_dtype=dtype,
                    use_safetensors=path.suffix.lower() == ".safetensors",
                )
            else:
                pipe.vae = AutoencoderKL.from_pretrained(str(path), torch_dtype=dtype)
            log_audit_entry(
                "synthesis_vae_loaded",
                "[Synthesis] Custom VAE loaded.",
                AuditStatus.INFO,
                details={"model_id": model.model_id, "vae_path": vae_path},
            )
        except Exception as exc:
            log_audit_entry(
                "synthesis_vae_load_failed",
                "[Synthesis] Failed to load custom VAE; using pipeline default VAE.",
                AuditStatus.WARNING,
                details={"model_id": model.model_id, "vae_path": vae_path, "error": str(exc)},
            )

    def _build_pipeline(self, model: SynthesisModelInfo, model_ref: str | None = None):
        model_ref = model_ref or self._resolve_model_ref(model)
        torch, device, dtype = self._pick_device_dtype()
        model_path = Path(model_ref)

        started = time.time()
        try:
            if model_path.is_file() and model_path.suffix.lower() in {".safetensors", ".ckpt"}:
                if model.family == "sdxl-checkpoint":
                    from diffusers import StableDiffusionXLPipeline

                    pipe = StableDiffusionXLPipeline.from_single_file(
                        model_ref,
                        torch_dtype=dtype,
                        use_safetensors=model_path.suffix.lower() == ".safetensors",
                    )
                else:
                    from diffusers import StableDiffusionPipeline

                    pipe = StableDiffusionPipeline.from_single_file(
                        model_ref,
                        torch_dtype=dtype,
                        use_safetensors=model_path.suffix.lower() == ".safetensors",
                    )
            elif model.family == "z-image":
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

        self._apply_vae(pipe, model, dtype)
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
                "vae_path": model.vae_path,
                "load_ms": int((time.time() - started) * 1000),
            },
        )
        return pipe, device

    def _pipeline_cache_key(self, model: SynthesisModelInfo) -> tuple[str, str, str, str]:
        return (
            str(model.model_id or ""),
            str(model.family or ""),
            self._resolve_model_ref(model),
            str(model.vae_path or ""),
        )

    def _get_pipeline(self, model: SynthesisModelInfo) -> Tuple[object, str]:
        cache_key = self._pipeline_cache_key(model)
        if not self._keep_loaded():
            self.release_resources()
            return self._build_pipeline(model, cache_key[2])

        with self._cache_lock:
            if self._cached_pipeline is not None and self._cached_key == cache_key:
                return self._cached_pipeline, self._cached_device
            self._release_cached_pipeline_locked()
            pipe, device = self._build_pipeline(model, cache_key[2])
            self._cached_pipeline = pipe
            self._cached_device = device
            self._cached_key = cache_key
            return pipe, device

    def _release_cached_pipeline_locked(self) -> None:
        pipe = self._cached_pipeline
        device = self._cached_device
        self._cached_pipeline = None
        self._cached_device = ""
        self._cached_key = None
        if pipe is not None:
            self._release_pipeline(pipe, device, force=True)

    def _release_pipeline(self, pipe: object, device: str, *, force: bool = False) -> None:
        if not force and self._keep_loaded() and pipe is self._cached_pipeline:
            return
        try:
            if hasattr(pipe, "to"):
                pipe.to("cpu")
        except Exception:
            pass
        try:
            del pipe
        except Exception:
            pass
        gc.collect()
        if device == "cuda":
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.ipc_collect()
            except Exception:
                pass

    def release_resources(self) -> None:
        with self._cache_lock:
            self._release_cached_pipeline_locked()
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:
            pass

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
            sampler=request.sampler,
            scheduler=request.scheduler,
            comfyui_checkpoint=request.comfyui_checkpoint,
            persist_output=request.persist_output,
            use_prompt_engineering=request.use_prompt_engineering,
            allow_fallback=request.allow_fallback,
            use_visual_intent=request.use_visual_intent,
            visual_intent_input=request.visual_intent_input,
            visual_profile=request.visual_profile,
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
        self._apply_scheduler(pipe, request.scheduler or (model.defaults or {}).get("scheduler"))

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
        finally:
            self._release_pipeline(pipe, device)

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()
        output_path = self._save_output_image(image_bytes, model.model_id, request.seed) if request.persist_output else None

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
                "scheduler": request.scheduler or (model.defaults or {}).get("scheduler"),
                "elapsed_ms": int((time.time() - started) * 1000),
                "bytes": len(image_bytes),
                "output_path": output_path,
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
            output_path=output_path,
        )
