from __future__ import annotations

import base64
import io
import time
from typing import Any, Dict, Optional

from PIL import Image, ImageDraw

from modules.ollama import client as ollama_client
from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry


class OllamaVisionProvider:
    """Vision provider backed by Ollama /api/chat multimodal models."""

    def __init__(self, provider_config: Optional[Dict[str, Any]] = None):
        cfg = provider_config or {}
        self.model_id = str(
            cfg.get("model")
            or cfg.get("model_id")
            or config_service.get_config_value("api.visual_model", "")
            or ""
        ).strip()
        self.max_tokens = int(cfg.get("max_tokens", 512) or 512)
        self.probe_enabled = bool(cfg.get("probe_enabled", True))
        self.probe_cache_seconds = max(5, int(cfg.get("probe_cache_seconds", 300) or 300))
        self.keep_alive = cfg.get("keep_alive", None)
        image_format = str(cfg.get("image_format") or "PNG").strip().upper()
        self.image_format = image_format if image_format in {"PNG", "JPEG"} else "PNG"

        self._last_probe_at: float = 0.0
        self._last_probe_ok: Optional[bool] = None
        self._last_probe_error: str = ""

    def _build_probe_image_b64(self) -> str:
        # Use a real, simple image. Some VLMs return empty content for 1x1/tiny probes.
        image = Image.new("RGB", (256, 256), color="white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((28, 40, 118, 168), fill=(220, 48, 48))
        draw.ellipse((142, 48, 226, 132), fill=(42, 103, 220))
        draw.text((34, 205), "VISION TEST", fill=(10, 10, 10))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    @staticmethod
    def _is_error_content(content: str) -> bool:
        return str(content or "").strip().lower().startswith("[error]")

    def _probe_vision_support(self) -> bool:
        if not self.probe_enabled:
            metadata_support = ollama_client.model_supports_vision(self.model_id)
            if not metadata_support.get("supported"):
                self._last_probe_ok = False
                self._last_probe_error = str(metadata_support.get("reason") or "model metadata does not declare vision support")
                return False
            return True
        now = time.time()
        if self._last_probe_ok is not None and (now - self._last_probe_at) < self.probe_cache_seconds:
            return bool(self._last_probe_ok)

        metadata_support = ollama_client.model_supports_vision(self.model_id)
        if not metadata_support.get("supported"):
            self._last_probe_ok = False
            self._last_probe_error = str(metadata_support.get("reason") or "model metadata does not declare vision support")
            self._last_probe_at = now
            return False

        test_messages = [
            {
                "role": "user",
                "content": "List the shapes and text in this image.",
                "images": [self._build_probe_image_b64()],
            }
        ]
        try:
            # Keep probe extremely lightweight to avoid runner crashes on low-memory setups.
            content = str(
                ollama_client.chat_image(
                    test_messages,
                    model=self.model_id,
                    options={
                        "num_predict": max(self.max_tokens, 256),
                        "temperature": 0.0,
                    },
                    keep_alive=self.keep_alive,
                )
                or ""
            ).strip()
            ok = bool(content) and not self._is_error_content(content)
            self._last_probe_ok = ok
            self._last_probe_error = "" if ok else (content or "empty probe response")
        except Exception as exc:
            self._last_probe_ok = False
            self._last_probe_error = str(exc)
        self._last_probe_at = now
        if not self._last_probe_ok:
            log_audit_entry(
                "vision_ollama_probe_failed",
                "[OllamaVisionProvider] Vision probe failed; model marked unavailable.",
                AuditStatus.WARNING,
                details={"model_id": self.model_id, "error": self._last_probe_error},
            )
        return bool(self._last_probe_ok)

    def is_ready(self) -> bool:
        if not ollama_client.is_available():
            self._last_probe_ok = False
            self._last_probe_error = "ollama is unavailable"
            return False
        return self._probe_vision_support()

    def describe_image(self, image: Image.Image, prompt: str) -> Dict[str, Any]:
        if not self.is_ready():
            return {
                "summary": f"Visual module not available: {self._last_probe_error or 'ollama vision unavailable'}",
                "model": self.model_id,
                "status": "not_ready",
            }
        if image.mode != "RGB":
            image = image.convert("RGB")
        buffer = io.BytesIO()
        if self.image_format == "JPEG":
            image.save(buffer, format="JPEG", quality=92)
        else:
            image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        messages = [
            {
                "role": "user",
                "content": str(prompt or "Describe the image in detail in English."),
                "images": [encoded],
            }
        ]
        content = str(
            ollama_client.chat_image(
                messages,
                model=self.model_id,
                options={
                    "num_predict": self.max_tokens,
                    "temperature": 0.1,
                },
                keep_alive=self.keep_alive,
            )
            or ""
        ).strip()
        if not content or self._is_error_content(content):
            return {
                "summary": content or "Vision response is empty",
                "model": self.model_id,
                "status": "error",
            }
        return {
            "summary": content,
            "model": self.model_id,
            "prompt": prompt,
            "status": "success",
        }
