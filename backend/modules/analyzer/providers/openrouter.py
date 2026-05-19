"""OpenRouter-based analyzer provider."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from openai import OpenAI

from constants.prompts import COGNITIVE_ANALYSIS_PROMPT
from constants.settings import (
    DEFAULT_HOST,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    OPENROUTER_BASE_URL,
    PROJECT_NAME,
)
from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry

from .base import AnalyzerProvider


class OpenRouterAnalyzerProvider(AnalyzerProvider):
    name = "openrouter"

    def _get_settings(self) -> Dict[str, Any]:
        cfg = config_service.get_config_value("analyzer.providers.openrouter", {}) or {}
        return {
            "api_key": cfg.get("api_key", ""),
            "model": cfg.get("model") or DEFAULT_MODEL,
            "temperature": float(cfg.get("temperature", DEFAULT_TEMPERATURE)),
            "max_tokens": int(cfg.get("max_tokens", DEFAULT_MAX_TOKENS)),
        }

    def is_available(self) -> bool:
        return bool(self._get_settings()["api_key"])

    async def analyze(
        self, content: str, context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        settings = self._get_settings()
        api_key = settings["api_key"]

        if not api_key:
            log_audit_entry(
                "analyzer_openrouter_skipped",
                "[Analyzer] Skipped: API key missing.",
                AuditStatus.INFO,
            )
            return None

        try:
            log_audit_entry(
                "analyzer_openrouter_start",
                "[Analyzer] Starting analysis.",
                AuditStatus.INFO,
                details={
                    "model": settings["model"],
                    "message_preview": content[:50],
                },
            )

            result = await asyncio.to_thread(
                self._call_openrouter,
                content,
                context,
                settings,
            )

            log_audit_entry(
                "analyzer_openrouter_success",
                "[Analyzer] Analysis completed successfully.",
                AuditStatus.SUCCESS,
            )
            return result

        except Exception as exc:  # pragma: no cover
            log_audit_entry(
                "analyzer_openrouter_error",
                "[Analyzer] Error during analysis.",
                AuditStatus.ERROR,
                details={"error": str(exc), "error_type": type(exc).__name__},
            )
            return None

    def _call_openrouter(
        self, content: str, context: Dict[str, Any], settings: Dict[str, Any]
    ) -> Dict[str, Any]:
        client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=settings["api_key"])

        payload = self._build_prompt(content, context)

        completion = client.chat.completions.create(
            extra_headers={
                "HTTP-Referer": DEFAULT_HOST,
                "X-Title": PROJECT_NAME,
            },
            model=settings["model"],
            messages=payload,
            temperature=settings["temperature"],
            max_tokens=settings["max_tokens"],
            response_format={"type": "json_object"},
        )

        response_content = completion.choices[0].message.content
        if not response_content or not response_content.strip():
            raise ValueError("OpenRouter API returned empty response.")

        return json.loads(response_content)

    @staticmethod
    def _build_prompt(content: str, context: Dict[str, Any]) -> List[Dict[str, str]]:
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
        return [
            {"role": "system", "content": analyzer_prompt},
            {"role": "user", "content": user_prompt_content},
        ]

