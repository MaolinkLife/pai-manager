from __future__ import annotations

import os
import random
import time
import uuid
from pathlib import Path
from typing import Any, Dict

import requests

from constants.paths import STORAGE_DIR
from modules.synthesis.providers.base import ImageProviderError
from modules.synthesis.types import ImageGenerationRequest, ImageGenerationResult, SynthesisModelInfo
from modules.system.logger import AuditStatus, log_audit_entry
from modules.system.service import get_config_value


class ComfyUIProvider:
    def release_resources(self) -> None:
        return None

    @staticmethod
    def _get_str_setting(path: str, env_name: str, default: str) -> str:
        value = get_config_value(path, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
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

    def _runtime_settings(self) -> Dict[str, Any]:
        return {
            "enabled": self._get_bool_setting("synthesis.comfyui.enabled", "COMFYUI_ENABLED", False),
            "base_url": self._get_str_setting(
                "synthesis.comfyui.base_url",
                "COMFYUI_BASE_URL",
                "http://127.0.0.1:8188",
            ).rstrip("/"),
            "timeout_sec": self._get_int_setting("synthesis.comfyui.timeout_sec", "COMFYUI_TIMEOUT_SEC", 180),
            "default_model": self._get_str_setting("synthesis.comfyui.default_model", "COMFYUI_DEFAULT_MODEL", ""),
        }

    @staticmethod
    def _object_choices(object_info: dict[str, Any], node_name: str, input_name: str) -> list[str]:
        node = object_info.get(node_name)
        if not isinstance(node, dict):
            return []
        required = ((node.get("input") or {}).get("required") or {})
        raw = required.get(input_name)
        if not isinstance(raw, list) or not raw:
            return []
        choices = raw[0]
        if not isinstance(choices, list):
            return []
        return [str(item) for item in choices if str(item).strip()]

    def inspect(self) -> dict[str, Any]:
        settings = self._runtime_settings()
        base_url = str(settings.get("base_url") or "http://127.0.0.1:8188").rstrip("/")
        timeout_sec = min(10, int(settings.get("timeout_sec") or 180))
        endpoints: list[dict[str, Any]] = []

        def probe(path: str) -> Any:
            url = f"{base_url}{path}"
            started = time.time()
            try:
                response = requests.get(url, timeout=timeout_sec)
                elapsed_ms = int((time.time() - started) * 1000)
                endpoints.append({"path": path, "method": "GET", "status": response.status_code, "ok": response.ok, "elapsed_ms": elapsed_ms})
                response.raise_for_status()
                if response.headers.get("content-type", "").lower().startswith("application/json"):
                    return response.json()
                return response.text
            except Exception as exc:
                endpoints.append({"path": path, "method": "GET", "status": None, "ok": False, "error": str(exc)})
                return None

        system_stats = probe("/system_stats")
        object_info = probe("/object_info")
        embeddings = probe("/embeddings")
        queue = probe("/queue")

        checkpoints = self._object_choices(object_info if isinstance(object_info, dict) else {}, "CheckpointLoaderSimple", "ckpt_name")
        loras = self._object_choices(object_info if isinstance(object_info, dict) else {}, "LoraLoader", "lora_name")
        vaes = self._object_choices(object_info if isinstance(object_info, dict) else {}, "VAELoader", "vae_name")
        controlnets = self._object_choices(object_info if isinstance(object_info, dict) else {}, "ControlNetLoader", "control_net_name")
        samplers = self._object_choices(object_info if isinstance(object_info, dict) else {}, "KSampler", "sampler_name")
        schedulers = self._object_choices(object_info if isinstance(object_info, dict) else {}, "KSampler", "scheduler")

        advertised_endpoints = [
            {"path": "/system_stats", "method": "GET", "purpose": "Runtime and GPU information"},
            {"path": "/object_info", "method": "GET", "purpose": "All node schemas and model choices"},
            {"path": "/object_info/{node}", "method": "GET", "purpose": "Single node schema"},
            {"path": "/embeddings", "method": "GET", "purpose": "Textual inversion embeddings"},
            {"path": "/queue", "method": "GET", "purpose": "Current queue state"},
            {"path": "/history", "method": "GET", "purpose": "Prompt history"},
            {"path": "/history/{prompt_id}", "method": "GET", "purpose": "Single prompt history"},
            {"path": "/prompt", "method": "POST", "purpose": "Queue workflow prompt"},
            {"path": "/view", "method": "GET", "purpose": "Download generated file"},
            {"path": "/ws", "method": "WS", "purpose": "Progress/events websocket"},
        ]

        return {
            "enabled": bool(settings.get("enabled")),
            "base_url": base_url,
            "configured_checkpoint": str(settings.get("default_model") or ""),
            "available": isinstance(system_stats, dict) and isinstance(object_info, dict),
            "system": system_stats if isinstance(system_stats, dict) else None,
            "queue": queue if isinstance(queue, dict) else None,
            "nodes_count": len(object_info) if isinstance(object_info, dict) else 0,
            "resources": {
                "checkpoints": checkpoints,
                "loras": loras,
                "vaes": vaes,
                "controlnets": controlnets,
                "embeddings": embeddings if isinstance(embeddings, list) else [],
                "samplers": samplers,
                "schedulers": schedulers,
            },
            "endpoints": advertised_endpoints,
            "probed_endpoints": endpoints,
        }

    @staticmethod
    def _save_output_image(image_bytes: bytes, model_id: str, seed: int | None) -> str:
        output_root = Path(STORAGE_DIR) / "outputs" / "images"
        output_root.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        safe_model = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in model_id)[:80]
        filename = f"{timestamp}_{safe_model}_{seed if seed is not None else 'random'}.png"
        path = output_root / filename
        path.write_bytes(image_bytes)
        return path.relative_to(Path(STORAGE_DIR)).as_posix()

    @staticmethod
    def _resolve_seed(seed: int | None) -> int:
        if seed is not None:
            return int(seed)
        return random.randint(0, 2**63 - 1)

    @staticmethod
    def _comfy_sampler(value: str | None) -> str:
        normalized = str(value or "").strip().lower()
        return {
            "euler": "euler",
            "euler_a": "euler_ancestral",
            "euler ancestral": "euler_ancestral",
            "dpmpp_2m": "dpmpp_2m",
            "dpm++ 2m": "dpmpp_2m",
            "ddim": "ddim",
            "lms": "lms",
        }.get(normalized, "euler")

    @staticmethod
    def _comfy_scheduler(value: str | None) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"dpmpp_2m", "dpm++ 2m"}:
            return "karras"
        return "normal"

    def _build_txt2img_workflow(
        self,
        *,
        request: ImageGenerationRequest,
        checkpoint: str,
        seed: int,
    ) -> dict[str, Any]:
        return {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": checkpoint},
            },
            "2": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": request.prompt, "clip": ["1", 1]},
            },
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": request.negative_prompt or "", "clip": ["1", 1]},
            },
            "4": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": int(request.width),
                    "height": int(request.height),
                    "batch_size": 1,
                },
            },
            "5": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed,
                    "steps": int(request.num_inference_steps),
                    "cfg": float(request.guidance_scale),
                    "sampler_name": self._comfy_sampler(request.sampler or request.scheduler),
                    "scheduler": self._comfy_scheduler(request.scheduler),
                    "denoise": 1.0,
                    "model": ["1", 0],
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "latent_image": ["4", 0],
                },
            },
            "6": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
            },
            "7": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": "pai_image_generator", "images": ["6", 0]},
            },
        }

    @staticmethod
    def _first_output_image(history_payload: dict[str, Any], prompt_id: str) -> dict[str, Any]:
        history_item = history_payload.get(prompt_id)
        if not isinstance(history_item, dict):
            raise ImageProviderError("ComfyUI returned no history item for generated prompt.")
        outputs = history_item.get("outputs")
        if not isinstance(outputs, dict):
            raise ImageProviderError("ComfyUI history contains no outputs.")

        for output in outputs.values():
            if not isinstance(output, dict):
                continue
            images = output.get("images")
            if isinstance(images, list) and images:
                image = images[0]
                if isinstance(image, dict) and image.get("filename"):
                    return image
        raise ImageProviderError("ComfyUI finished without an image output.")

    def _queue_prompt(self, base_url: str, workflow: dict[str, Any], timeout_sec: int) -> str:
        payload = {
            "prompt": workflow,
            "client_id": str(uuid.uuid4()),
        }
        try:
            response = requests.post(f"{base_url}/prompt", json=payload, timeout=timeout_sec)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise ImageProviderError(f"ComfyUI prompt request failed: {exc}") from exc
        except ValueError as exc:
            raise ImageProviderError("ComfyUI /prompt returned invalid JSON.") from exc

        prompt_id = str(data.get("prompt_id") or "").strip()
        if not prompt_id:
            raise ImageProviderError("ComfyUI /prompt did not return prompt_id.")
        return prompt_id

    def _wait_for_history(self, base_url: str, prompt_id: str, timeout_sec: int) -> dict[str, Any]:
        deadline = time.time() + timeout_sec
        last_error = ""
        while time.time() < deadline:
            try:
                response = requests.get(f"{base_url}/history/{prompt_id}", timeout=10)
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict) and payload.get(prompt_id):
                    return payload
            except Exception as exc:
                last_error = str(exc)
            time.sleep(1.0)
        suffix = f" Last error: {last_error}" if last_error else ""
        raise ImageProviderError(f"ComfyUI generation timed out after {timeout_sec}s.{suffix}")

    def _download_image(self, base_url: str, image: dict[str, Any], timeout_sec: int) -> bytes:
        params = {
            "filename": str(image.get("filename") or ""),
            "subfolder": str(image.get("subfolder") or ""),
            "type": str(image.get("type") or "output"),
        }
        try:
            response = requests.get(f"{base_url}/view", params=params, timeout=timeout_sec)
            response.raise_for_status()
            return response.content
        except requests.RequestException as exc:
            raise ImageProviderError(f"ComfyUI image download failed: {exc}") from exc

    def generate(self, request: ImageGenerationRequest, model: SynthesisModelInfo) -> ImageGenerationResult:
        if not request.prompt.strip():
            raise ImageProviderError("Prompt is required.")

        settings = self._runtime_settings()
        if not settings.get("enabled", False):
            raise ImageProviderError("ComfyUI provider is disabled in config (synthesis.comfyui.enabled=false).")

        checkpoint = str(request.comfyui_checkpoint or settings.get("default_model") or "").strip()
        if not checkpoint:
            raise ImageProviderError("ComfyUI checkpoint is not configured (synthesis.comfyui.default_model).")

        base_url = str(settings.get("base_url") or "http://127.0.0.1:8188").rstrip("/")
        timeout_sec = int(settings.get("timeout_sec") or 180)
        seed = self._resolve_seed(request.seed)
        workflow = self._build_txt2img_workflow(request=request, checkpoint=checkpoint, seed=seed)

        log_audit_entry(
            "synthesis_comfyui_request",
            "[Synthesis] ComfyUI request prepared.",
            AuditStatus.INFO,
            details={
                "provider": "comfyui",
                "endpoint": "POST /prompt",
                "base_url": base_url,
                "timeout_sec": timeout_sec,
                "checkpoint": checkpoint,
                "prompt": request.prompt,
                "negative_prompt": request.negative_prompt or "",
                "width": request.width,
                "height": request.height,
                "steps": request.num_inference_steps,
                "guidance_scale": request.guidance_scale,
                "seed": seed,
                "sampler": request.sampler,
                "scheduler": request.scheduler,
                "workflow": workflow,
            },
        )

        started = time.time()
        prompt_id = self._queue_prompt(base_url, workflow, timeout_sec)
        history = self._wait_for_history(base_url, prompt_id, timeout_sec)
        image_meta = self._first_output_image(history, prompt_id)
        image_bytes = self._download_image(base_url, image_meta, timeout_sec)
        output_path = self._save_output_image(image_bytes, model.model_id, seed) if request.persist_output else None

        log_audit_entry(
            "synthesis_comfyui_generated",
            "[Synthesis] ComfyUI image generated.",
            AuditStatus.INFO,
            details={
                "provider": "comfyui",
                "base_url": base_url,
                "prompt_id": prompt_id,
                "checkpoint": checkpoint,
                "width": request.width,
                "height": request.height,
                "steps": request.num_inference_steps,
                "guidance_scale": request.guidance_scale,
                "seed": seed,
                "scheduler": request.scheduler,
                "elapsed_ms": int((time.time() - started) * 1000),
                "bytes": len(image_bytes),
                "output_path": output_path,
            },
        )
        return ImageGenerationResult(
            provider="comfyui",
            model_id=model.model_id,
            image_bytes=image_bytes,
            mime_type="image/png",
            width=request.width,
            height=request.height,
            seed=seed,
            output_path=output_path,
        )
