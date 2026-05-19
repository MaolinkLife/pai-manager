"""Ollama-based analyzer provider."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

from constants.prompts import COGNITIVE_ANALYSIS_PROMPT
from constants.settings import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE
from modules.ollama import client as ollama_client
from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry

from .base import AnalyzerProvider


class OllamaAnalyzerProvider(AnalyzerProvider):
    name = "ollama"

    @staticmethod
    def _as_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return bool(value)

    def _get_settings(self) -> Dict[str, Any]:
        cfg = config_service.get_config_value("analyzer.providers.ollama", {}) or {}
        return {
            "model": cfg.get("model") or config_service.get_config_value("api.model", "llama3.2"),
            "temperature": float(cfg.get("temperature", DEFAULT_TEMPERATURE)),
            "max_tokens": int(cfg.get("max_tokens", DEFAULT_MAX_TOKENS)),
            "thinking": self._as_bool(cfg.get("thinking", cfg.get("think")), False),
        }

    def is_available(self) -> bool:
        return True

    def release_resources(self) -> None:
        settings = self._get_settings()
        ollama_client.release_model(model=settings.get("model"))

    async def analyze(
        self, content: str, context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        settings = self._get_settings()

        try:
            log_audit_entry(
                "analyzer_ollama_start",
                "[Analyzer] Starting analysis.",
                AuditStatus.INFO,
                details={"model": settings["model"], "thinking": settings["thinking"]},
            )
            result = await asyncio.to_thread(
                self._call_ollama,
                content,
                context,
                settings,
            )
            log_audit_entry(
                "analyzer_ollama_success",
                "[Analyzer] Analysis completed successfully.",
                AuditStatus.SUCCESS,
            )
            return result
        except Exception as exc:  # pragma: no cover
            log_audit_entry(
                "analyzer_ollama_error",
                "[Analyzer] Error during analysis.",
                AuditStatus.ERROR,
                details={"error": str(exc), "error_type": type(exc).__name__},
            )
            return None

    @staticmethod
    def _call_ollama(
        content: str,
        context: Dict[str, Any],
        settings: Dict[str, Any],
    ) -> Dict[str, Any]:
        analyzer_prompt = str(
            config_service.get_config_value(
                "analyzer.system_prompt", COGNITIVE_ANALYSIS_PROMPT
            )
            or COGNITIVE_ANALYSIS_PROMPT
        ).strip()
        input_payload = {
            "inputText": content,
            "hasMedia": int((context or {}).get("media_count") or 0) > 0,
        }
        user_prompt_content = json.dumps(input_payload, ensure_ascii=False, indent=2)
        history = [
            {"role": "system", "content": analyzer_prompt},
            {"role": "user", "content": user_prompt_content},
        ]
        options = {
            "temperature": settings["temperature"],
            "max_tokens": settings["max_tokens"],
            "__think": settings["thinking"],
        }
        response = ollama_client.chat(
            history,
            options,
            model=settings["model"],
        )
        assistant_content = (
            response.get("message", {}).get("content", "")
            if isinstance(response, dict)
            else ""
        )
        if not assistant_content.strip():
            raise ValueError("Ollama returned empty response.")
        return json.loads(assistant_content)

