"""llama.cpp-based analyzer provider.

Mirrors ``OllamaAnalyzerProvider``: sends the configured analyzer prompt plus
the user payload to llama-server's OpenAI-compatible ``/v1/chat/completions``
endpoint, expects a JSON object in the assistant response.

DB config lives at ``analyzer.providers.llama_cpp``. base_url and (optionally)
model can be overridden separately from the generative provider, so users can
point analyzer traffic at a smaller, faster llama-server instance if they
want.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

from constants.prompts import COGNITIVE_ANALYSIS_PROMPT
from constants.settings import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE
from modules.llama_cpp import client as llama_client
from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry

from .base import AnalyzerProvider


_DEFAULT_BASE_URL = "http://127.0.0.1:8080"


class LlamaCppAnalyzerProvider(AnalyzerProvider):
    name = "llama_cpp"

    def _get_settings(self) -> Dict[str, Any]:
        cfg = config_service.get_config_value("analyzer.providers.llama_cpp", {}) or {}
        if not isinstance(cfg, dict):
            cfg = {}
        return {
            "enabled": bool(cfg.get("enabled", False)),
            "base_url": str(cfg.get("base_url") or _DEFAULT_BASE_URL).rstrip("/"),
            "model": cfg.get("model") or None,
            "temperature": float(cfg.get("temperature", DEFAULT_TEMPERATURE)),
            "max_tokens": int(cfg.get("max_tokens", DEFAULT_MAX_TOKENS)),
            "timeout": float(cfg.get("request_timeout", 120.0)),
        }

    def is_available(self) -> bool:
        return bool(self._get_settings().get("enabled"))

    def release_resources(self) -> None:
        # llama-server is process-managed externally (or by the upcoming
        # embedded launcher); the per-call provider has no weights to drop.
        return None

    async def analyze(
        self, content: str, context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        settings = self._get_settings()
        if not settings.get("enabled"):
            return None

        try:
            log_audit_entry(
                "analyzer_llama_cpp_start",
                "[Analyzer] Starting analysis (llama.cpp).",
                AuditStatus.INFO,
                details={"model": settings.get("model"), "base_url": settings.get("base_url")},
            )
            result = await asyncio.to_thread(self._call_llama_cpp, content, context, settings)
            log_audit_entry(
                "analyzer_llama_cpp_success",
                "[Analyzer] Analysis completed (llama.cpp).",
                AuditStatus.SUCCESS,
            )
            return result
        except Exception as exc:
            log_audit_entry(
                "analyzer_llama_cpp_error",
                "[Analyzer] llama.cpp analyzer error.",
                AuditStatus.ERROR,
                details={"error": str(exc), "error_type": type(exc).__name__},
            )
            return None

    @staticmethod
    def _call_llama_cpp(
        content: str,
        context: Dict[str, Any],
        settings: Dict[str, Any],
    ) -> Dict[str, Any]:
        analyzer_prompt = str(
            config_service.get_config_value("analyzer.system_prompt", COGNITIVE_ANALYSIS_PROMPT)
            or COGNITIVE_ANALYSIS_PROMPT
        ).strip()
        input_payload = {
            "inputText": content,
            "hasMedia": int((context or {}).get("media_count") or 0) > 0,
        }
        user_prompt_content = json.dumps(input_payload, ensure_ascii=False, indent=2)
        messages = [
            {"role": "system", "content": analyzer_prompt},
            {"role": "user", "content": user_prompt_content},
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
            purpose="analyzer",
        )
        choices = response.get("choices") or []
        first = choices[0] if isinstance(choices, list) and choices else {}
        assistant_content = (
            (first.get("message") if isinstance(first, dict) else {}) or {}
        ).get("content", "")
        if not (isinstance(assistant_content, str) and assistant_content.strip()):
            raise ValueError("llama.cpp returned empty response.")
        return json.loads(assistant_content)
