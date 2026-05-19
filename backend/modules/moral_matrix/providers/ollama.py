"""Ollama-backed MoralMatrix provider."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

from constants.prompts import MORAL_MATRIX_PROVIDER_PROMPT
from constants.settings import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE
from modules.ollama import client as ollama_client
from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry

from .base import MoralMatrixProvider, parse_provider_json


class OllamaMoralProvider(MoralMatrixProvider):
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
        cfg = config_service.get_config_value("moral.providers.ollama", {}) or {}
        return {
            "model": cfg.get("model") or config_service.get_config_value("api.model", "llama3.2"),
            "temperature": float(cfg.get("temperature", DEFAULT_TEMPERATURE)),
            "max_tokens": int(cfg.get("max_tokens", min(DEFAULT_MAX_TOKENS, 512))),
            "thinking": self._as_bool(cfg.get("thinking", cfg.get("think")), False),
        }

    def release_resources(self) -> None:
        settings = self._get_settings()
        ollama_client.release_model(model=settings.get("model"))

    async def run(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        settings = self._get_settings()
        try:
            log_audit_entry(
                "moral_matrix_provider_ollama_start",
                "[MoralMatrix] Provider start.",
                AuditStatus.INFO,
                details={"model": settings["model"], "thinking": settings["thinking"]},
            )
            result = await asyncio.to_thread(
                self._call_ollama,
                payload,
                settings,
            )
            if result:
                log_audit_entry(
                    "moral_matrix_provider_ollama_success",
                    "[MoralMatrix] Provider completed.",
                    AuditStatus.SUCCESS,
                )
            return result
        except Exception as exc:  # pragma: no cover
            log_audit_entry(
                "moral_matrix_provider_ollama_error",
                "[MoralMatrix] Provider error.",
                AuditStatus.ERROR,
                details={"error": str(exc), "error_type": type(exc).__name__},
            )
            return None

    @staticmethod
    def _call_ollama(
        payload: Dict[str, Any], settings: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        moral_prompt = str(
            config_service.get_config_value(
                "moral.system_prompt", MORAL_MATRIX_PROVIDER_PROMPT
            )
            or MORAL_MATRIX_PROVIDER_PROMPT
        ).strip()
        conversation = [
            {"role": "system", "content": moral_prompt},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, indent=2),
            },
        ]
        options = {
            "temperature": settings["temperature"],
            "max_tokens": settings["max_tokens"],
            "__think": settings["thinking"],
        }
        response = ollama_client.chat(
            conversation,
            options,
            model=settings["model"],
        )
        assistant_content = (
            response.get("message", {}).get("content", "")
            if isinstance(response, dict)
            else ""
        )
        return parse_provider_json(OllamaMoralProvider.name, assistant_content)

