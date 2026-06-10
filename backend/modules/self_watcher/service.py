"""Self-Watcher service surface.

Two entry points:
  * check_expectation()         — per-turn, sync, never-raises.
  * record_nightly_reflection() — once a day from loop_initiative.
"""

from __future__ import annotations

import json
from datetime import date as date_cls, datetime, timezone
from typing import Any, Dict, List, Optional

from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry

from .classifier import classify_valence, score_mismatch
from .repository import self_watcher_repository
from .types import ExpectationCheckResult


_DEFAULT_THRESHOLD = 0.5
_DEFAULT_LOOKBACK = 7
_DEFAULT_MAX_CLUSTER = 20
_DEFAULT_LLM_MAX_TOKENS = 220
_DEFAULT_LLM_TEMP = 0.5


def _settings() -> Dict[str, Any]:
    cfg = config_service.get_config_value("self_watcher", {}) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "mismatch_threshold": float(
            cfg.get("mismatch_threshold", _DEFAULT_THRESHOLD) or _DEFAULT_THRESHOLD
        ),
        "nightly_reflection_enabled": bool(cfg.get("nightly_reflection_enabled", True)),
        "lookback_days": int(cfg.get("lookback_days", _DEFAULT_LOOKBACK) or _DEFAULT_LOOKBACK),
        "max_events_in_cluster": int(
            cfg.get("max_events_in_cluster", _DEFAULT_MAX_CLUSTER) or _DEFAULT_MAX_CLUSTER
        ),
        "llm_max_tokens": int(
            cfg.get("llm_max_tokens", _DEFAULT_LLM_MAX_TOKENS) or _DEFAULT_LLM_MAX_TOKENS
        ),
        "llm_temperature": float(
            cfg.get("llm_temperature", _DEFAULT_LLM_TEMP) or _DEFAULT_LLM_TEMP
        ),
    }


def check_expectation(
    *,
    character_id: str,
    prev_assistant_meta: Optional[Dict[str, Any]],
    prev_assistant_message_id: Optional[str],
    current_user_tone: Optional[str],
    current_user_intensity: float = 0.5,
    triggering_user_message_id: Optional[str] = None,
) -> ExpectationCheckResult:
    """Compare PAI's previous prediction to user's actual reaction.

    `prev_assistant_meta` is the runtime_meta dict from the previous
    assistant History row — that's where we stored
    `pai_predicted_emotion` / `pai_predicted_valence` when the turn
    completed. If those keys are missing, we skip silently.

    Never raises. Returns ``ExpectationCheckResult`` regardless of outcome.
    """
    settings = _settings()
    if not settings["enabled"]:
        return ExpectationCheckResult(skipped=True, skip_reason="disabled")

    if not character_id:
        return ExpectationCheckResult(skipped=True, skip_reason="no_character")

    if not isinstance(prev_assistant_meta, dict) or not prev_assistant_meta:
        return ExpectationCheckResult(skipped=True, skip_reason="no_previous_prediction")

    predicted_emotion = str(prev_assistant_meta.get("pai_predicted_emotion") or "").strip()
    predicted_valence = str(prev_assistant_meta.get("pai_predicted_valence") or "").strip()
    if not predicted_emotion:
        return ExpectationCheckResult(skipped=True, skip_reason="no_previous_prediction")

    try:
        predicted_intensity = float(prev_assistant_meta.get("pai_predicted_intensity") or 0.5)
    except (TypeError, ValueError):
        predicted_intensity = 0.5
    if not predicted_valence:
        predicted_valence = classify_valence(predicted_emotion)

    tone_text = str(current_user_tone or "").strip()
    if not tone_text:
        return ExpectationCheckResult(skipped=True, skip_reason="no_user_tone")

    actual_valence = classify_valence(tone_text)
    try:
        actual_intensity = float(current_user_intensity or 0.5)
    except (TypeError, ValueError):
        actual_intensity = 0.5

    score = score_mismatch(
        predicted_valence=predicted_valence,
        actual_valence=actual_valence,
        predicted_intensity=predicted_intensity,
        actual_intensity=actual_intensity,
    )

    if score < settings["mismatch_threshold"]:
        return ExpectationCheckResult(
            skipped=True,
            skip_reason="below_threshold",
            mismatch_score=score,
            pai_predicted_emotion=predicted_emotion,
            pai_predicted_valence=predicted_valence,
            user_actual_tone=tone_text,
            user_actual_valence=actual_valence,
        )

    note = (
        f"predicted={predicted_emotion}/{predicted_valence} "
        f"actual={tone_text}/{actual_valence} "
        f"score={score:.3f}"
    )
    entry_id = self_watcher_repository.insert(
        character_id=character_id,
        prev_assistant_message_id=prev_assistant_message_id,
        triggering_user_message_id=triggering_user_message_id,
        pai_predicted_emotion=predicted_emotion,
        pai_predicted_valence=predicted_valence,
        user_actual_tone=tone_text,
        user_actual_valence=actual_valence,
        mismatch_score=score,
        notes=note,
    )

    if entry_id is None:
        return ExpectationCheckResult(
            skipped=True,
            skip_reason="db_write_failed",
            mismatch_score=score,
            pai_predicted_emotion=predicted_emotion,
            pai_predicted_valence=predicted_valence,
            user_actual_tone=tone_text,
            user_actual_valence=actual_valence,
        )

    log_audit_entry(
        "self_watcher_mismatch",
        f"[SelfWatcher] expectation mismatch score={score:.2f}",
        AuditStatus.INFO,
        details={
            "event_id": entry_id,
            "predicted_emotion": predicted_emotion,
            "predicted_valence": predicted_valence,
            "actual_tone": tone_text,
            "actual_valence": actual_valence,
            "score": score,
        },
    )

    return ExpectationCheckResult(
        recorded=True,
        event_id=entry_id,
        mismatch_score=score,
        pai_predicted_emotion=predicted_emotion,
        pai_predicted_valence=predicted_valence,
        user_actual_tone=tone_text,
        user_actual_valence=actual_valence,
    )


def record_nightly_reflection(
    *,
    character_id: str,
    day: date_cls,
) -> Optional[str]:
    """Aggregate recent expectation_events into a short first-person
    reflection via LLM. Returns the reflection text or None if skipped.

    The caller (loop_initiative) is expected to write the returned text
    into ``daily_activity_diary.payload.self_reflection`` — we don't touch
    the diary table from here to keep the surface small.

    Never raises.
    """
    settings = _settings()
    if not settings["enabled"] or not settings["nightly_reflection_enabled"]:
        return None
    if not character_id:
        return None

    events = self_watcher_repository.list_recent(
        character_id=character_id,
        lookback_days=settings["lookback_days"],
        limit=settings["max_events_in_cluster"],
    )
    if not events:
        return None

    try:
        from constants.prompts import SELF_WATCHER_REFLECTION_PROMPT
        from modules.generative.manager import (
            NoProviderResolved,
            generation_manager,
        )
        from modules.generative.types import GenerateRequest
        from modules.system.user import resolve_user_language
    except Exception as exc:
        log_audit_entry(
            "self_watcher_reflection_import_failed",
            "[SelfWatcher] Required modules unavailable for nightly reflection.",
            AuditStatus.WARNING,
            details={"error": str(exc)},
        )
        return None

    language = resolve_user_language(character_id=character_id, fallback="en-US")
    cluster_lines: List[str] = []
    for row in events:
        cluster_lines.append(
            f"- predicted {row.get('pai_predicted_emotion')!r}"
            f" ({row.get('pai_predicted_valence')}); "
            f"actual {row.get('user_actual_tone')!r}"
            f" ({row.get('user_actual_valence')}); "
            f"score {float(row.get('mismatch_score') or 0.0):.2f}"
        )
    cluster_blob = "\n".join(cluster_lines)

    user_payload = (
        f"Language: {language}\n"
        f"Day: {day.isoformat()}\n"
        f"Recent expectation mismatches ({len(events)} events):\n"
        f"{cluster_blob}"
    )

    system_prompt = SELF_WATCHER_REFLECTION_PROMPT.format(language=language)
    try:
        result = generation_manager.generate(
            GenerateRequest(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_payload},
                ],
                options={
                    "temperature": settings["llm_temperature"],
                    "num_predict": settings["llm_max_tokens"],
                },
                metadata={"mode": "self_watcher_reflection"},
            )
        )
    except NoProviderResolved as exc:
        log_audit_entry(
            "self_watcher_reflection_no_provider",
            "[SelfWatcher] Provider unavailable for reflection.",
            AuditStatus.WARNING,
            details={"error": str(exc)},
        )
        return None
    except Exception as exc:
        log_audit_entry(
            "self_watcher_reflection_provider_error",
            "[SelfWatcher] Provider failed for reflection.",
            AuditStatus.WARNING,
            details={"error": str(exc)},
        )
        return None

    text_out = str(getattr(result, "content", "") or "").strip()
    if not text_out:
        text_out = str(getattr(result, "reasoning", "") or "").strip()
    if not text_out:
        return None
    # Strip obvious leading prefixes the model may add even after the prompt.
    for prefix in ("Reflection:", "Self-reflection:", "PAI:", "Лим:", "Reflexion:"):
        if text_out.lower().startswith(prefix.lower()):
            text_out = text_out[len(prefix):].strip()
    return text_out[:2000]
