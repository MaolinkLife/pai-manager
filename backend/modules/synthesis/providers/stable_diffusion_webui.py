from __future__ import annotations

import base64
import os
from typing import Any, Dict

import requests

from modules.synthesis.providers.base import ImageProviderError
from modules.synthesis.types import (
    ImageGenerationRequest,
    ImageGenerationResult,
    SynthesisModelInfo,
)
from modules.system.logger import AuditStatus, log_audit_entry
from modules.system.service import get_config_value


class StableDiffusionWebUIProvider:
    def __init__(self) -> None:
        pass

    def release_resources(self) -> None:
        return None

    @staticmethod
    def _get_str_setting(path: str, env_name: str, default: str) -> str:
        value = get_config_value(path, None)
        if isinstance(value, str):
            value = value.strip()
            if value:
                return value
        return (os.getenv(env_name) or default).strip()

    @staticmethod
    def _get_bool_setting(path: str, env_name: str, default: bool) -> bool:
        value = get_config_value(path, None)
        if isinstance(value, bool):
            return value
        env_val = os.getenv(env_name)
        if isinstance(env_val, str) and env_val.strip():
            return env_val.strip().lower() in {"1", "true", "yes", "on"}
        return default

    @staticmethod
    def _get_int_setting(path: str, env_name: str, default: int) -> int:
        value = get_config_value(path, None)
        try:
            if value is not None:
                return max(1, int(value))
        except Exception:
            pass
        env_val = os.getenv(env_name)
        try:
            if env_val is not None and str(env_val).strip():
                return max(1, int(env_val))
        except Exception:
            pass
        return default

    @staticmethod
    def _get_float_setting(path: str, env_name: str, default: float) -> float:
        value = get_config_value(path, None)
        try:
            if value is not None:
                return float(value)
        except Exception:
            pass
        env_val = os.getenv(env_name)
        try:
            if env_val is not None and str(env_val).strip():
                return float(env_val)
        except Exception:
            pass
        return default

    def _runtime_settings(self) -> Dict[str, Any]:
        base_url = self._get_str_setting(
            "synthesis.sd_webui.base_url",
            "SD_WEBUI_BASE_URL",
            "http://127.0.0.1:7860",
        ).rstrip("/")
        return {
            "enabled": self._get_bool_setting(
                "synthesis.sd_webui.enabled",
                "SD_WEBUI_ENABLED",
                False,
            ),
            "base_url": base_url,
            "bearer_token": self._get_str_setting(
                "synthesis.sd_webui.bearer_token",
                "SD_WEBUI_BEARER_TOKEN",
                "",
            ),
            "timeout_sec": self._get_int_setting(
                "synthesis.sd_webui.timeout_sec",
                "SD_WEBUI_TIMEOUT_SEC",
                180,
            ),
            "checkpoint": self._get_str_setting(
                "synthesis.sd_webui.checkpoint",
                "SD_WEBUI_CHECKPOINT",
                "",
            ),
            "sampler_name": self._get_str_setting(
                "synthesis.sd_webui.sampler_name",
                "SD_WEBUI_SAMPLER_NAME",
                "DPM++ 2M",
            ),
            "scheduler": self._get_str_setting(
                "synthesis.sd_webui.scheduler",
                "SD_WEBUI_SCHEDULER",
                "Automatic",
            ),
            "cfg_scale_default": self._get_float_setting(
                "synthesis.sd_webui.cfg_scale_default",
                "SD_WEBUI_CFG_SCALE_DEFAULT",
                2.0,
            ),
        }

    @staticmethod
    def _endpoint(base_url: str) -> str:
        return f"{base_url}/sdapi/v1/txt2img"

    @staticmethod
    def _decode_first_image(payload: dict) -> bytes:
        images = payload.get("images")
        if not isinstance(images, list) or not images:
            raise ImageProviderError("Stable Diffusion WebUI returned no images.")
        encoded = str(images[0] or "").strip()
        if not encoded:
            raise ImageProviderError("Stable Diffusion WebUI returned an empty image payload.")
        if "," in encoded and encoded.lower().startswith("data:image"):
            encoded = encoded.split(",", 1)[1]
        try:
            return base64.b64decode(encoded)
        except Exception as exc:  # pragma: no cover
            raise ImageProviderError("Failed to decode Stable Diffusion image payload.") from exc

    def generate(
        self,
        request: ImageGenerationRequest,
        model: SynthesisModelInfo,
    ) -> ImageGenerationResult:
        if not request.prompt.strip():
            raise ImageProviderError("Prompt is required.")

        settings = self._runtime_settings()
        if not settings.get("enabled", False):
            raise ImageProviderError(
                "Stable Diffusion WebUI provider is disabled in config (synthesis.sd_webui.enabled=false)."
            )

        cfg_scale = (
            request.guidance_scale
            if request.guidance_scale > 0
            else float(settings.get("cfg_scale_default", 2.0))
        )
        override_settings = {}
        checkpoint = str(settings.get("checkpoint") or "").strip()
        if checkpoint:
            override_settings["sd_model_checkpoint"] = checkpoint

        query = {
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt or "",
            "styles": [],
            "seed": int(request.seed) if request.seed is not None else -1,
            "sampler_name": str(settings.get("sampler_name") or "DPM++ 2M"),
            "scheduler": str(settings.get("scheduler") or "Automatic"),
            "batch_size": 1,
            "n_iter": 1,
            "steps": int(request.num_inference_steps),
            "cfg_scale": float(cfg_scale),
            "width": int(request.width),
            "height": int(request.height),
            "send_images": True,
            "save_images": False,
            "override_settings": override_settings,
        }

        headers = {"Content-Type": "application/json"}
        bearer_token = str(settings.get("bearer_token") or "").strip()
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"

        try:
            response = requests.post(
                self._endpoint(str(settings.get("base_url") or "http://127.0.0.1:7860")),
                json=query,
                headers=headers,
                timeout=int(settings.get("timeout_sec") or 180),
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise ImageProviderError(
                f"Stable Diffusion WebUI request failed: {exc}"
            ) from exc
        except ValueError as exc:
            raise ImageProviderError(
                "Stable Diffusion WebUI returned invalid JSON."
            ) from exc

        image_bytes = self._decode_first_image(payload)
        log_audit_entry(
            "synthesis_sd_webui_generated",
            "[Synthesis] Stable Diffusion WebUI image generated.",
            AuditStatus.INFO,
            details={
                "provider": "stable_diffusion_webui",
                "endpoint": self._endpoint(str(settings.get("base_url") or "http://127.0.0.1:7860")),
                "model_id": model.model_id,
                "width": request.width,
                "height": request.height,
                "steps": request.num_inference_steps,
                "guidance_scale": cfg_scale,
                "seed": request.seed,
                "bytes": len(image_bytes),
            },
        )
        return ImageGenerationResult(
            provider="stable_diffusion_webui",
            model_id=model.model_id,
            image_bytes=image_bytes,
            mime_type="image/png",
            width=request.width,
            height=request.height,
            seed=request.seed,
        )
