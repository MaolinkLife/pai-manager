"""llama.cpp-backed MoralMatrix provider.

Same shape as ``OllamaMoralProvider`` — sends the configured moral prompt plus
the payload to llama-server's OpenAI chat endpoint and expects a JSON object
in the reply. ``parse_provider_json`` from ``base`` tolerates code fences and
stray prose around the JSON, so we get the same robustness as the Ollama
variant for free.

DB config: ``moral.providers.llama_cpp``. ``enabled`` defaults to false so this
provider is dormant until the user opts in via UI / set_config_value.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

from constants.prompts import MORAL_MATRIX_PROVIDER_PROMPT
from constants.settings import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE
from modules.llama_cpp import client as llama_client
from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry

from .base import MoralMatrixProvider, parse_provider_json


_DEFAULT_BASE_URL = "http://127.0.0.1:8080"


class LlamaCppMoralProvider(MoralMatrixProvider):
    name = "llama_cpp"

    def _get_settings(self) -> Dict[str, Any]:
        cfg = config_service.get_config_value("moral.providers.llama_cpp", {}) or {}
        if not isinstance(cfg, dict):
            cfg = {}
        return {
            "enabled": bool(cfg.get("enabled", False)),
            "base_url": str(cfg.get("base_url") or _DEFAULT_BASE_URL).rstrip("/"),
            "model": cfg.get("model") or None,
            "temperature": float(cfg.get("temperature", DEFAULT_TEMPERATURE)),
            "max_tokens": int(cfg.get("max_tokens", min(DEFAULT_MAX_TOKENS, 512))),
            "timeout": float(cfg.get("request_timeout", 120.0)),
        }

    def is_available(self) -> bool:
        return bool(self._get_settings().get("enabled"))

    def release_resources(self) -> None:
        return None

    async def run(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        settings = self._get_settings()
        if not settings.get("enabled"):
            return None

        try:
            log_audit_entry(
                "moral_matrix_provider_llama_cpp_start",
                "[MoralMatrix] Provider start (llama.cpp).",
                AuditStatus.INFO,
                details={"model": settings.get("model"), "base_url": settings.get("base_url")},
            )
            result = await asyncio.to_thread(self._call_llama_cpp, payload, settings)
            if result:
                log_audit_entry(
                    "moral_matrix_provider_llama_cpp_success",
                    "[MoralMatrix] Provider completed (llama.cpp).",
                    AuditStatus.SUCCESS,
                )
            return result
        except Exception as exc:
            log_audit_entry(
                "moral_matrix_provider_llama_cpp_error",
                "[MoralMatrix] Provider error (llama.cpp).",
                AuditStatus.ERROR,
                details={"error": str(exc), "error_type": type(exc).__name__},
            )
            return None

    @staticmethod
    def _call_llama_cpp(
        payload: Dict[str, Any], settings: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        moral_prompt = str(
            config_service.get_config_value(
                "moral.system_prompt", MORAL_MATRIX_PROVIDER_PROMPT
            )
            or MORAL_MATRIX_PROVIDER_PROMPT
        ).strip()
        messages = [
            {"role": "system", "content": moral_prompt},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, indent=2),
            },
        ]
        sampler = {
            "temperature": settings["temperature"],
            "max_tokens": settings["max_tokens"],
        }
        response = llama_client.chat_completion(
            base_url=settings["base_url"],
            messages=messages,
            model=settings.get("model"),
            sampler=sampler,
            timeout=settings["timeout"],
            purpose="moral_matrix",
        )
        choices = response.get("choices") or []
        first = choices[0] if isinstance(choices, list) and choices else {}
        assistant_content = (
            (first.get("message") if isinstance(first, dict) else {}) or {}
        ).get("content", "")
        return parse_provider_json(LlamaCppMoralProvider.name, assistant_content)
