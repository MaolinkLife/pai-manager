"""Public surface of the language guard.

Contract:
  * check_language NEVER raises — broken detector / config / inputs all
    surface as skipped=True with skip_reason / error filled in.
  * A skipped result is NOT a failure. Callers only act on ok=False.
  * No external state, no LLM call — pure CPU.
"""

from __future__ import annotations

from typing import Any, Dict

from modules.system import config as config_service

from .detector import detect_dominant_script, is_script_compatible, locale_prefix
from .types import LanguageCheckResult


_DEFAULT_MIN_DOMINANCE = 0.7
_DEFAULT_MIN_OUTPUT_CHARS = 40


def get_language_guard_settings() -> Dict[str, Any]:
    """Read DB-config and normalise. Always returns a dict with the keys the
    guard needs, even if the config section is missing entirely."""
    cfg = config_service.get_config_value("language_guard", {}) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    enabled = bool(cfg.get("enabled", False))
    try:
        min_dominance = float(cfg.get("min_dominance", _DEFAULT_MIN_DOMINANCE))
    except (TypeError, ValueError):
        min_dominance = _DEFAULT_MIN_DOMINANCE
    try:
        min_output_chars = int(cfg.get("min_output_chars", _DEFAULT_MIN_OUTPUT_CHARS))
    except (TypeError, ValueError):
        min_output_chars = _DEFAULT_MIN_OUTPUT_CHARS
    return {
        "enabled": enabled,
        "min_dominance": max(0.0, min(min_dominance, 1.0)),
        "min_output_chars": max(0, min_output_chars),
    }


def check_language(
    output: str,
    expected_language: str,
    *,
    min_dominance: float | None = None,
    min_output_chars: int | None = None,
) -> LanguageCheckResult:
    """Compare the dominant script of `output` against `expected_language`.

    The function always returns a `LanguageCheckResult`. Never raises.
    """
    settings = get_language_guard_settings()
    if not settings["enabled"]:
        return LanguageCheckResult(
            expected=expected_language,
            ok=True,
            skipped=True,
            skip_reason="disabled",
        )

    expected = str(expected_language or "").strip()
    if not expected or not locale_prefix(expected):
        return LanguageCheckResult(
            expected=expected,
            ok=True,
            skipped=True,
            skip_reason="no_expected_language",
        )

    text = str(output or "")
    threshold_chars = (
        min_output_chars
        if min_output_chars is not None
        else settings["min_output_chars"]
    )
    if len(text) < threshold_chars:
        return LanguageCheckResult(
            expected=expected,
            ok=True,
            skipped=True,
            skip_reason="output_too_short",
        )

    try:
        script, dominance, counted = detect_dominant_script(text)
    except Exception as exc:
        return LanguageCheckResult(
            expected=expected,
            ok=True,
            skipped=True,
            skip_reason="detector_error",
            error=str(exc),
        )

    if counted == 0:
        return LanguageCheckResult(
            expected=expected,
            detected="",
            dominance=0.0,
            ok=True,
            skipped=True,
            skip_reason="no_letters",
        )

    threshold = (
        min_dominance if min_dominance is not None else settings["min_dominance"]
    )
    if dominance < threshold:
        # The output is too mixed to make a confident verdict — treat as
        # legitimate mixed-language (e.g. RU prose with English tech terms).
        return LanguageCheckResult(
            expected=expected,
            detected=script,
            dominance=dominance,
            ok=True,
            skipped=True,
            skip_reason="below_dominance_threshold",
            extra={"counted_letters": counted, "threshold": threshold},
        )

    ok = is_script_compatible(script, expected)
    return LanguageCheckResult(
        expected=expected,
        detected=script,
        dominance=dominance,
        ok=ok,
        extra={"counted_letters": counted, "threshold": threshold},
    )
