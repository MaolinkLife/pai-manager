"""Base provider interfaces for MoralMatrix narrative/directive generation."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from modules.system.logger import AuditStatus, log_audit_entry


def parse_provider_json(provider_name: str, content: Any) -> Optional[Dict[str, Any]]:
    """Parse a model JSON response without letting malformed output break fallback."""
    text = str(content or "").strip()
    if not text:
        log_audit_entry(
            "moral_matrix_provider_empty_response",
            "[MoralMatrix] Provider returned empty response.",
            AuditStatus.WARNING,
            details={"provider": provider_name},
        )
        return None

    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                parsed = None
        else:
            parsed = None

        if parsed is None:
            log_audit_entry(
                "moral_matrix_provider_invalid_json",
                "[MoralMatrix] Provider returned non-JSON response.",
                AuditStatus.WARNING,
                details={
                    "provider": provider_name,
                    "error": str(exc),
                    "preview": text[:400],
                },
            )
            return None

    if not isinstance(parsed, dict):
        log_audit_entry(
            "moral_matrix_provider_invalid_payload",
            "[MoralMatrix] Provider returned unsupported JSON payload.",
            AuditStatus.WARNING,
            details={"provider": provider_name, "payload_type": type(parsed).__name__},
        )
        return None

    return parsed


class MoralMatrixProvider(ABC):
    """Base provider used to refine MoralMatrix evaluation via LLM or heuristics."""

    name: str = "base"

    def is_available(self) -> bool:
        return True

    @abstractmethod
    async def run(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Evaluate payload and return directive metadata."""

    def release_resources(self) -> None:
        return None
