"""Vision provider backed by llama-server's multimodal endpoint.

Follows the same duck-typed contract used by AppleVisionProvider /
OllamaVisionProvider — no shared base class, just is_ready() +
describe_image(image, prompt).

When llama-server is launched with ``--mmproj <path>`` it accepts
OpenAI-style chat messages whose ``content`` is a list mixing text and
``image_url`` parts (with base64 data URLs). This adapter packages the
PIL image into that shape and forwards via ``modules.llama_cpp.client``.

DB config: ``vision.vision_modules.llama_cpp_vision``. ``enabled`` defaults
to false so the provider is dormant until the user picks it via
``vision.active_provider`` or flips the flag.
"""

from __future__ import annotations

import base64
import io
from typing import Any, Dict, Optional

from PIL import Image

from modules.llama_cpp import client as llama_client
from modules.system.logger import AuditStatus, log_audit_entry


_DEFAULT_BASE_URL = "http://127.0.0.1:8080"


class LlamaCppVisionProvider:
    """llama.cpp multimodal adapter."""

    def __init__(self, provider_config: Optional[Dict[str, Any]] = None):
        cfg = provider_config or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.base_url = str(cfg.get("base_url") or _DEFAULT_BASE_URL).rstrip("/")
        self.model_id = str(cfg.get("model") or cfg.get("model_id") or "").strip()
        self.max_tokens = int(cfg.get("max_tokens", 512) or 512)
        self.request_timeout = float(cfg.get("request_timeout", 120) or 120)
        self.ping_timeout = float(cfg.get("ping_timeout", 3.0) or 3.0)
        image_format = str(cfg.get("image_format") or "PNG").strip().upper()
        self.image_format = image_format if image_format in {"PNG", "JPEG"} else "PNG"

        self._last_error: str = ""

    # ------------------------------------------------------------------
    # readiness
    # ------------------------------------------------------------------

    def is_ready(self) -> bool:
        if not self.enabled:
            self._last_error = "llama.cpp vision disabled"
            return False
        try:
            ok = llama_client.ping(base_url=self.base_url, timeout=self.ping_timeout)
        except Exception as exc:
            self._last_error = f"ping failed: {exc}"
            return False
        if not ok:
            self._last_error = f"llama-server not reachable at {self.base_url}"
        return bool(ok)

    # ------------------------------------------------------------------
    # describe
    # ------------------------------------------------------------------

    def describe_image(self, image: Image.Image, prompt: str) -> Dict[str, Any]:
        if not self.is_ready():
            return {
                "summary": f"Visual module not available: {self._last_error or 'llama.cpp vision unavailable'}",
                "model": self.model_id,
                "status": "not_ready",
            }

        encoded = self._encode_image(image)
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": str(prompt or "Describe the image in detail in English.")},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/{self.image_format.lower()};base64,{encoded}",
                        },
                    },
                ],
            }
        ]
        sampler = {
            "max_tokens": self.max_tokens,
            "temperature": 0.1,
        }
        try:
            response = llama_client.chat_completion(
                base_url=self.base_url,
                messages=messages,
                model=self.model_id or None,
                sampler=sampler,
                timeout=self.request_timeout,
                purpose="vision",
            )
        except Exception as exc:
            log_audit_entry(
                "vision_llama_cpp_error",
                "[LlamaCppVisionProvider] Multimodal request failed.",
                AuditStatus.ERROR,
                details={"base_url": self.base_url, "error": str(exc)},
            )
            return {
                "summary": f"Vision request failed: {exc}",
                "model": self.model_id,
                "status": "error",
            }

        choices = response.get("choices") or []
        first = choices[0] if isinstance(choices, list) and choices else {}
        content = (
            (first.get("message") if isinstance(first, dict) else {}) or {}
        ).get("content", "")
        content = str(content or "").strip()

        if not content:
            return {
                "summary": "Vision response is empty",
                "model": self.model_id,
                "status": "error",
            }

        return {
            "summary": content,
            "model": self.model_id,
            "prompt": prompt,
            "status": "success",
        }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _encode_image(self, image: Image.Image) -> str:
        if image.mode != "RGB":
            image = image.convert("RGB")
        buffer = io.BytesIO()
        if self.image_format == "JPEG":
            image.save(buffer, format="JPEG", quality=92)
        else:
            image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")
