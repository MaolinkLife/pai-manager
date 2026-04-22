from __future__ import annotations

import base64
import io
import time
from typing import Any, Dict, Optional

from PIL import Image

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
        self.max_tokens = int(cfg.get("max_tokens", 160) or 160)
        self.probe_enabled = bool(cfg.get("probe_enabled", True))
        self.probe_cache_seconds = max(5, int(cfg.get("probe_cache_seconds", 300) or 300))

        self._last_probe_at: float = 0.0
        self._last_probe_ok: Optional[bool] = None
        self._last_probe_error: str = ""

    def _build_probe_image_b64(self) -> str:
        # Tiny deterministic RGB sample for capability probe.
        image = Image.new("RGB", (16, 16), color=(122, 162, 255))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=80)
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def _probe_vision_support(self) -> bool:
        if not self.probe_enabled:
            return True
        now = time.time()
        if self._last_probe_ok is not None and (now - self._last_probe_at) < self.probe_cache_seconds:
            return bool(self._last_probe_ok)

        test_messages = [
            {
                "role": "user",
                "content": "Describe this test image in one short sentence.",
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
                        "num_predict": 24,
                        "temperature": 0.0,
                    },
                    keep_alive=0,
                )
                or ""
            ).strip()
            ok = bool(content) and not content.startswith("[ERROR]")
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
        image.save(buffer, format="JPEG", quality=92)
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
                keep_alive=0,
            )
            or ""
        ).strip()
        if not content or content.startswith("[ERROR]"):
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
