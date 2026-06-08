"""LLM-as-judge validator: scores how well an output follows its instructions.

Uses the existing generation_manager (i.e. the active chat provider) — there is
no separate service-LLM dispatch in pai-manager yet. When `validator.enabled`
is false the caller gets ``ValidationResult(skipped=True)`` back; the caller
decides whether "skipped" counts as pass.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry
from modules.validator.types import ValidationError, ValidationResult


_DEFAULT_THRESHOLD = 0.7
_DEFAULT_MAX_TOKENS = 256
_DEFAULT_TEMPERATURE = 0.0  # deterministic-leaning for grading


def _is_enabled() -> bool:
    return bool(config_service.get_config_value("validator.enabled", False))


def _read_settings() -> Dict[str, Any]:
    return {
        "max_tokens": int(
            config_service.get_config_value("validator.max_tokens", _DEFAULT_MAX_TOKENS)
            or _DEFAULT_MAX_TOKENS
        ),
        "temperature": float(
            config_service.get_config_value("validator.temperature", _DEFAULT_TEMPERATURE)
            or _DEFAULT_TEMPERATURE
        ),
        "instruction_char_limit": int(
            config_service.get_config_value("validator.instruction_char_limit", 4000)
            or 4000
        ),
        "output_char_limit": int(
            config_service.get_config_value("validator.output_char_limit", 4000)
            or 4000
        ),
    }


def _build_payload(
    *,
    instructions: str,
    output: str,
    instruction_limit: int,
    output_limit: int,
) -> str:
    """Compose the user-side prompt. Truncates long inputs because the
    validator is supposed to be cheap — full novel-length context is not
    its job."""
    trimmed_instr = (instructions or "").strip()
    if len(trimmed_instr) > instruction_limit:
        trimmed_instr = trimmed_instr[:instruction_limit] + " […truncated]"

    trimmed_out = (output or "").strip()
    if len(trimmed_out) > output_limit:
        trimmed_out = trimmed_out[:output_limit] + " […truncated]"

    return (
        "INSTRUCTIONS:\n"
        f"{trimmed_instr}\n\n"
        "OUTPUT:\n"
        f"{trimmed_out}"
    )


def _parse_response(raw: str) -> Dict[str, Any]:
    """Tolerate fenced output and slightly malformed JSON. Raises
    ValidationError if nothing recoverable is found."""
    text = (raw or "").strip()
    if text.startswith("```"):
        # Strip fence wrapper, optionally with ``` json header.
        text = text.split("```", 1)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.split("```", 1)[0].strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # Try to recover the object portion if the model wrapped JSON in prose.
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValidationError(f"validator returned non-JSON: {text[:200]!r}")
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValidationError(f"validator JSON recovery failed: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValidationError(f"validator returned non-object JSON: {payload!r}")

    return payload


def _coerce_compliance(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, score))


def _coerce_violations(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            out.append(text[:400])
    return out


def validate_output(
    *,
    output: str,
    instructions: str,
    context: Optional[Dict[str, Any]] = None,
) -> ValidationResult:
    """Score how well ``output`` follows ``instructions``.

    ``instructions`` is the same string the Instructor built for the LLM:
    system prompt + hard directives + active rules. The validator does NOT
    reconstruct it — caller passes the actual text to keep the validator
    free of pipeline coupling.

    On any error (LLM unreachable, malformed JSON, etc.) returns
    ``ValidationResult(skipped=True, error=...)`` rather than raising,
    so the caller never has to wrap this in try/except. Production rule:
    a broken validator must not break generation.
    """
    if not _is_enabled():
        return ValidationResult(skipped=True, skip_reason="disabled")

    if not (output or "").strip():
        # Empty output is a generation failure, not a validation failure —
        # don't waste an LLM call on it.
        return ValidationResult(skipped=True, skip_reason="empty_output")

    try:
        # Lazy imports — avoid pulling generative module at validator import time.
        from constants.prompts import VALIDATOR_COMPLIANCE_PROMPT
        from modules.generative.manager import (
            NoProviderResolved,
            generation_manager,
        )
        from modules.generative.types import GenerateRequest
    except Exception as exc:
        log_audit_entry(
            "validator_import_failed",
            "[Validator] Required modules unavailable.",
            AuditStatus.WARNING,
            details={"error": str(exc)},
        )
        return ValidationResult(skipped=True, skip_reason="import_error", error=str(exc))

    settings = _read_settings()
    user_payload = _build_payload(
        instructions=instructions,
        output=output,
        instruction_limit=settings["instruction_char_limit"],
        output_limit=settings["output_char_limit"],
    )

    try:
        result = generation_manager.generate(
            GenerateRequest(
                messages=[
                    {"role": "system", "content": VALIDATOR_COMPLIANCE_PROMPT},
                    {"role": "user", "content": user_payload},
                ],
                options={
                    "temperature": settings["temperature"],
                    "num_predict": settings["max_tokens"],
                    "max_tokens": settings["max_tokens"],
                    "__think": False,
                },
                metadata={"mode": "validator"},
            )
        )
    except NoProviderResolved as exc:
        log_audit_entry(
            "validator_no_provider",
            "[Validator] No provider available; skipping.",
            AuditStatus.WARNING,
            details={"error": str(exc)},
        )
        return ValidationResult(skipped=True, skip_reason="no_provider", error=str(exc))
    except Exception as exc:
        log_audit_entry(
            "validator_generate_failed",
            "[Validator] Generation error during validation.",
            AuditStatus.WARNING,
            details={"error": str(exc)},
        )
        return ValidationResult(skipped=True, skip_reason="generate_error", error=str(exc))

    raw_text = str(getattr(result, "content", "") or "").strip()
    if not raw_text:
        return ValidationResult(skipped=True, skip_reason="empty_response")

    try:
        payload = _parse_response(raw_text)
    except ValidationError as exc:
        log_audit_entry(
            "validator_parse_failed",
            "[Validator] Could not parse JSON response; skipping.",
            AuditStatus.WARNING,
            details={"error": str(exc), "raw_preview": raw_text[:240]},
        )
        return ValidationResult(skipped=True, skip_reason="parse_error", error=str(exc))

    return ValidationResult(
        compliance=_coerce_compliance(payload.get("compliance")),
        violations=_coerce_violations(payload.get("violations")),
        skipped=False,
        raw=payload,
    )


def get_compliance_threshold() -> float:
    """Configurable cutoff used by callers to decide acceptable vs failing.
    Default 0.7 matches the concept doc."""
    try:
        value = float(
            config_service.get_config_value("validator.threshold", _DEFAULT_THRESHOLD)
            or _DEFAULT_THRESHOLD
        )
    except (TypeError, ValueError):
        value = _DEFAULT_THRESHOLD
    return max(0.0, min(1.0, value))
