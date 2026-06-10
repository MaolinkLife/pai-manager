"""LLM-as-judge confidence estimator.

Uses generation_manager (same provider as the chat itself — pai-manager has
no separate service-LLM dispatcher). When ``confidence.enabled`` is false
the caller gets ``ConfidenceResult(skipped=True)`` back and treats it as
"no signal".
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry

from .types import ConfidenceResult


_DEFAULT_THRESHOLD = 0.5
_DEFAULT_MAX_TOKENS = 64
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_USER_LIMIT = 2000
_DEFAULT_OUTPUT_LIMIT = 4000


def _is_enabled() -> bool:
    return bool(config_service.get_config_value("confidence.enabled", False))


def get_confidence_threshold() -> float:
    raw = config_service.get_config_value("confidence.threshold", _DEFAULT_THRESHOLD)
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return _DEFAULT_THRESHOLD


def _read_settings() -> Dict[str, Any]:
    return {
        "max_tokens": int(
            config_service.get_config_value("confidence.max_tokens", _DEFAULT_MAX_TOKENS)
            or _DEFAULT_MAX_TOKENS
        ),
        "temperature": float(
            config_service.get_config_value("confidence.temperature", _DEFAULT_TEMPERATURE)
            or _DEFAULT_TEMPERATURE
        ),
        "user_char_limit": int(
            config_service.get_config_value("confidence.user_char_limit", _DEFAULT_USER_LIMIT)
            or _DEFAULT_USER_LIMIT
        ),
        "output_char_limit": int(
            config_service.get_config_value("confidence.output_char_limit", _DEFAULT_OUTPUT_LIMIT)
            or _DEFAULT_OUTPUT_LIMIT
        ),
    }


def _build_payload(*, user_message: str, output: str, user_limit: int, output_limit: int) -> str:
    user_trim = (user_message or "").strip()
    if len(user_trim) > user_limit:
        user_trim = user_trim[:user_limit] + " […truncated]"
    out_trim = (output or "").strip()
    if len(out_trim) > output_limit:
        out_trim = out_trim[:output_limit] + " […truncated]"
    return (
        "USER MESSAGE:\n"
        f"{user_trim}\n\n"
        "OUTPUT:\n"
        f"{out_trim}"
    )


def _parse_response(raw: str) -> Optional[float]:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = text.split("```", 1)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.split("```", 1)[0].strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None

    if not isinstance(payload, dict):
        return None
    value = payload.get("confidence")
    if value is None:
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, score))


def estimate_confidence(
    *,
    user_message: str,
    assistant_output: str,
    context: Optional[Dict[str, Any]] = None,
) -> ConfidenceResult:
    """Score how confident PAI should be in this output.

    Never raises. A broken estimator surfaces as skipped=True with skip_reason
    set — generation must not break because confidence cannot be scored.
    """
    if not _is_enabled():
        return ConfidenceResult(skipped=True, skip_reason="disabled")

    if not (assistant_output or "").strip():
        return ConfidenceResult(skipped=True, skip_reason="empty_output")

    if not (user_message or "").strip():
        return ConfidenceResult(skipped=True, skip_reason="empty_user_message")

    try:
        from constants.prompts import CONFIDENCE_ESTIMATION_PROMPT
        from modules.generative.manager import (
            NoProviderResolved,
            generation_manager,
        )
        from modules.generative.types import GenerateRequest
    except Exception as exc:
        log_audit_entry(
            "confidence_import_failed",
            "[Confidence] Required modules unavailable.",
            AuditStatus.WARNING,
            details={"error": str(exc)},
        )
        return ConfidenceResult(skipped=True, skip_reason="import_error", error=str(exc))

    settings = _read_settings()
    payload = _build_payload(
        user_message=user_message,
        output=assistant_output,
        user_limit=settings["user_char_limit"],
        output_limit=settings["output_char_limit"],
    )

    try:
        result = generation_manager.generate(
            GenerateRequest(
                messages=[
                    {"role": "system", "content": CONFIDENCE_ESTIMATION_PROMPT},
                    {"role": "user", "content": payload},
                ],
                options={
                    "temperature": settings["temperature"],
                    "num_predict": settings["max_tokens"],
                },
                metadata={"mode": "confidence_estimation"},
            )
        )
    except NoProviderResolved as exc:
        return ConfidenceResult(skipped=True, skip_reason="no_provider", error=str(exc))
    except Exception as exc:
        log_audit_entry(
            "confidence_provider_error",
            "[Confidence] Provider failed.",
            AuditStatus.WARNING,
            details={"error": str(exc)},
        )
        return ConfidenceResult(skipped=True, skip_reason="provider_error", error=str(exc))

    raw = str(getattr(result, "content", "") or "").strip()
    if not raw:
        raw = str(getattr(result, "reasoning", "") or "").strip()

    score = _parse_response(raw)
    if score is None:
        return ConfidenceResult(
            skipped=True,
            skip_reason="parse_error",
            raw=raw,
        )

    return ConfidenceResult(score=score, raw=raw)
