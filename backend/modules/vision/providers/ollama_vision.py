from __future__ import annotations

import base64
import io
from typing import Any, Dict, Optional

from PIL import Image

from constants.prompts import VISION_FALLBACK_PROMPT
from constants.visual import VISION_MODEL_NOT_SELECTED
from modules.ollama import client as ollama_client
from modules.system.logger import AuditStatus, log_audit_entry


class OllamaVisionProvider:
    """Vision provider backed by Ollama /api/chat multimodal models.

    Whether the model can see is what Ollama declares in the model metadata. No
    test image is sent to find out: a model is not run to
    check what it can do.
    """

    def __init__(self, provider_config: Optional[Dict[str, Any]] = None):
        cfg = provider_config or {}
        # Only the model picked in the vision settings.
        self.model_id = str(cfg.get("model") or cfg.get("model_id") or "").strip()
        self.max_tokens = int(cfg.get("max_tokens", 512) or 512)
        self.keep_alive = cfg.get("keep_alive", None)
        image_format = str(cfg.get("image_format") or "PNG").strip().upper()
        self.image_format = image_format if image_format in {"PNG", "JPEG"} else "PNG"

        # Why the model is unavailable; the vision status routes read it.
        self._last_probe_error: str = ""
        # What Ollama's model metadata declares (vision, thinking, tools, ...).
        self._capabilities: list[str] = []
        self._thinks: bool = False

    def _note_capabilities(self, metadata_support: Dict[str, Any]) -> None:
        self._capabilities = [str(item).strip().lower() for item in (metadata_support.get("capabilities") or [])]
        self._thinks = "thinking" in self._capabilities

    def _request_options(self, **options: Any) -> Dict[str, Any]:
        # A description needs no reasoning. Left to reason, a thinking model
        # spends the whole token budget there and answers nothing.
        if self._thinks:
            options["__think"] = False
        return options

    @staticmethod
    def _empty_answer_reason(result: Dict[str, Any]) -> str:
        """Why an answer is unusable, read from Ollama's own fields; "" when it is fine."""
        if result.get("error"):
            return str(result["error"])
        if str(result.get("content") or "").strip():
            return ""
        if str(result.get("thinking") or "").strip() and result.get("done_reason") == "length":
            return "reasoning used the whole token budget before any answer"
        if result.get("done_reason") == "length":
            return "the token limit cut the answer before any text"
        return "the model returned an empty answer"

    def _check_vision_support(self) -> bool:
        if not self.model_id:
            self._last_probe_error = VISION_MODEL_NOT_SELECTED
            return False
        metadata_support = ollama_client.model_supports_vision(self.model_id)
        self._note_capabilities(metadata_support)
        if metadata_support.get("supported"):
            self._last_probe_error = ""
            return True
        self._last_probe_error = str(metadata_support.get("reason") or "model metadata does not declare vision support")
        log_audit_entry(
            "vision_ollama_not_declared",
            "[OllamaVisionProvider] The model's metadata does not declare vision; model marked unavailable.",
            AuditStatus.WARNING,
            details={
                "model_id": self.model_id,
                "error": self._last_probe_error,
                "capabilities": self._capabilities,
            },
        )
        return False

    def is_ready(self) -> bool:
        if not ollama_client.is_available():
            self._last_probe_error = "ollama is unavailable"
            return False
        return self._check_vision_support()

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
                "content": str(prompt or VISION_FALLBACK_PROMPT),
                "images": [encoded],
            }
        ]
        result = ollama_client.chat_image_response(
            messages,
            model=self.model_id,
            options=self._request_options(num_predict=self.max_tokens, temperature=0.1),
            keep_alive=self.keep_alive,
        )
        reason = self._empty_answer_reason(result)
        if reason:
            return {
                "summary": f"[ERROR] {reason}" if result.get("error") else f"Vision response is empty: {reason}",
                "model": self.model_id,
                "status": "error",
            }
        content = str(result.get("content") or "").strip()
        return {
            "summary": content,
            "model": self.model_id,
            "prompt": prompt,
            "status": "success",
        }
