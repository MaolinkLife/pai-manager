"""High-level generation pipeline that orchestrates DecisionLayer and providers."""

from __future__ import annotations

import asyncio
import ast
import base64
import json
import re
import uuid
import time
from datetime import datetime, timezone
import hashlib
from io import BytesIO
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Tuple

from PIL import Image

from modules.generative import NoProviderResolved, generation_manager
from modules.generative.types import GenerateRequest, GenerateStreamChunk
from modules.generative.output_normalizer import StreamingOutputNormalizer, normalize_output_text
from modules.system.service import get_active_character_name
from core.decision_layer import decision_layer
from modules.database import service as database_service
from modules.synthesis.media_pipeline import MediaPipelineRequest, media_generation_pipeline
from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry
from modules.vision import VisualModule
from core import tool_event_bus
from modules.tts.state import VoiceStage, voice_state
from utils.time_utils import to_user_tz_iso

THINK_PATTERN = re.compile(r"<think>(.*?)</think>", re.IGNORECASE | re.DOTALL)
STREAM_REASONING_CHAR_BUDGET = 12000
STORED_REASONING_CHAR_LIMIT = 16000
WHITESPACE_TOKEN_PATTERN = re.compile(r"\S+\s*")
ANSWER_SIGNAL_PATTERN = re.compile(r"\w", re.UNICODE)
STREAM_PROVIDER_IDLE_NOTICE_SEC = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sanitize_media_items(media: Iterable[dict] | None) -> List[dict]:
    sanitized: List[dict] = []
    if not media:
        return sanitized
    for item in media:
        if not isinstance(item, dict):
            continue
        cleaned = {
            key: value
            for key, value in item.items()
            if key.lower() not in {"data", "base64"}
        }
        data_field = item.get("data") or item.get("base64")
        if data_field is not None and "size" not in cleaned:
            cleaned["size"] = len(data_field)
        sanitized.append(cleaned)
    return sanitized


def _extract_media_payload(message: Dict[str, Any] | Iterable[dict]) -> List[dict]:
    if isinstance(message, dict):
        media_items = message.get("media")
    else:
        media_items = message
    if not media_items:
        return []

    prepared: List[dict] = []
    for idx, item in enumerate(media_items):
        if not isinstance(item, dict):
            continue
        data = item.get("data") or item.get("base64")
        if not data:
            continue
        prepared.append(
            {
                "data": data,
                "mimeType": item.get("mimeType")
                or item.get("mime_type")
                or item.get("contentType")
                or item.get("type")
                or "",
                "category": item.get("category") or item.get("mediaType") or "other",
                "name": item.get("name")
                or item.get("filename")
                or f"attachment_{idx + 1}",
                "description": item.get("description") or "",
            }
        )
    return prepared


def _sanitize_history(history: list, *, drop_media: bool) -> list:
    sanitized: list = []
    for message in history or []:
        base = {k: v for k, v in message.items() if k != "timestamp"}
        media = base.get("media")
        if media:
            if drop_media:
                base.pop("media", None)
            else:
                base["media"] = _sanitize_media_items(media)
        sanitized.append(base)
    return sanitized


def build_chat_request(history: list) -> list:
    sanitized = _sanitize_history(history, drop_media=True)
    return [msg for msg in sanitized if msg.get("role") != "system"]


def _should_pass_media_to_main_ollama_model() -> bool:
    if str(config_service.get_config_value("api.active_provider", "") or "").strip() != "ollama":
        return False
    active_vision = str(config_service.get_config_value("vision.active_provider", "") or "").strip()
    if active_vision not in {"ollama_vision", "llava"}:
        return False
    return bool(
        config_service.get_config_value(
            f"vision.vision_modules.{active_vision}.use_main_model_context",
            False,
        )
    )


def _image_payloads_for_ollama(media_items: Iterable[dict] | None) -> List[str]:
    images: List[str] = []
    for item in media_items or []:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or item.get("mediaType") or "").lower()
        mime_type = str(item.get("mimeType") or item.get("mime_type") or "").lower()
        if category != "image" and not mime_type.startswith("image/"):
            continue
        data = str(item.get("data") or item.get("base64") or "").strip()
        if not data:
            continue
        if "," in data and data.lower().startswith("data:image"):
            data = data.split(",", 1)[1].strip()
        if data:
            images.append(data)
    return images


def _attach_images_to_last_user_message(chat_history: list, media_items: Iterable[dict] | None) -> int:
    images = _image_payloads_for_ollama(media_items)
    if not images:
        return 0
    for message in reversed(chat_history):
        if isinstance(message, dict) and message.get("role") == "user":
            message["images"] = images
            return len(images)
    return 0


def split_reasoning(raw: str) -> tuple[str, str]:
    if not raw:
        return "", ""

    match = THINK_PATTERN.search(raw)
    if not match:
        return raw.strip(), ""

    reasoning = match.group(1).strip()
    cleaned = THINK_PATTERN.sub("", raw).strip()
    return cleaned, reasoning


def _trim_reasoning_for_storage(reasoning: str, limit: int = STORED_REASONING_CHAR_LIMIT) -> str:
    text = str(reasoning or "").strip()
    return text


def _stream_delta(previous: str, incoming: str) -> tuple[str, str]:
    """
    Normalize provider stream payloads to deltas.
    Some backends send accumulated reasoning snapshots instead of incremental chunks.
    """
    prev = str(previous or "")
    current = str(incoming or "")
    if not current:
        return "", prev
    if not prev:
        return current, current
    if current.startswith(prev):
        return current[len(prev) :], current
    if prev.endswith(current):
        return "", prev

    max_overlap = min(len(prev), len(current))
    for size in range(max_overlap, 0, -1):
        if prev[-size:] == current[:size]:
            delta = current[size:]
            return delta, prev + delta
    return current, prev + current


def _take_ui_reasoning_delta(text: str, already_emitted: int) -> tuple[str, int, bool]:
    if not text:
        return "", already_emitted, False
    return text, already_emitted + len(text), False


def strip_reasoning_from_chunk(chunk: str, in_reasoning: bool) -> tuple[str, str, bool]:
    if not chunk:
        return "", "", in_reasoning

    speech_parts: list[str] = []
    reasoning_parts: list[str] = []
    lower_chunk = chunk.lower()
    idx = 0
    while idx < len(chunk):
        if in_reasoning:
            end_idx = lower_chunk.find("</think>", idx)
            if end_idx == -1:
                reasoning_parts.append(chunk[idx:])
                return "".join(speech_parts), "".join(reasoning_parts), True
            reasoning_parts.append(chunk[idx:end_idx])
            idx = end_idx + len("</think>")
            in_reasoning = False
        else:
            start_idx = lower_chunk.find("<think>", idx)
            if start_idx == -1:
                speech_parts.append(chunk[idx:])
                break
            speech_parts.append(chunk[idx:start_idx])
            idx = start_idx + len("<think>")
            in_reasoning = True

    return "".join(speech_parts), "".join(reasoning_parts), in_reasoning


def _has_answer_signal(text: str) -> bool:
    return bool(text and ANSWER_SIGNAL_PATTERN.search(text))


def _truncate_by_token_budget(text: str, remaining_tokens: int) -> tuple[str, int]:
    """
    Token-like limiter for visible answer chunks.
    Uses whitespace-delimited segments as a safe approximation.
    """
    if not text or remaining_tokens <= 0:
        return "", 0
    segments = WHITESPACE_TOKEN_PATTERN.findall(text)
    if not segments:
        return "", 0
    if len(segments) <= remaining_tokens:
        return text, len(segments)
    truncated = "".join(segments[:remaining_tokens]).rstrip()
    return truncated, remaining_tokens


def _extract_provider_errors(exc: Exception) -> List[Dict[str, str]]:
    try:
        data = ast.literal_eval(str(exc))
    except (ValueError, SyntaxError):
        return []

    if isinstance(data, dict):
        data = [data]

    errors: List[Dict[str, str]] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                provider = str(item.get("provider", "unknown"))
                reason = item.get("reason")
                if reason is None:
                    reason = ""
                errors.append({"provider": provider, "reason": str(reason)})
    return errors


def _generate_tags_for_text(
    text: str,
    extra: Iterable[str] | None = None,
    *,
    limit: int = 8,
) -> List[str]:
    tags: List[str] = []
    seen = set()
    for candidate in extra or []:
        normalized = str(candidate).strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        tags.append(normalized)
        if len(tags) >= limit:
            return tags
    for match in re.findall(r"[\w\-]{4,}", text.lower()):
        if match in seen:
            continue
        seen.add(match)
        tags.append(match)
        if len(tags) >= limit:
            break
    return tags


def _build_validator_instructions(decision_context: Dict[str, Any]) -> str:
    """Compose the instruction text the validator scores against.

    Order matters — validator weights hard directives more than the system
    prompt, so we concatenate in that priority and let the prompt truncation
    inside the validator clip at the configured char limit.
    """
    system_prompt = str(decision_context.get("system_prompt", "") or "").strip()
    moral_state = decision_context.get("moral_state") or {}
    hard_directives = moral_state.get("hard_directives") if isinstance(moral_state, dict) else None
    directives_block = ""
    if isinstance(hard_directives, list) and hard_directives:
        directives_block = "HARD DIRECTIVES (MUST follow):\n" + "\n".join(
            f"- {str(item).strip()}" for item in hard_directives if str(item).strip()
        )

    pieces = [p for p in (directives_block, system_prompt) if p]
    return "\n\n".join(pieces)


def _maybe_run_validator(
    *,
    decision_context: Dict[str, Any],
    last_user_message: Dict[str, Any],
    assistant_content: str,
    provider: Any,
    metadata: Dict[str, Any] | None,
) -> Dict[str, Any]:
    """Run the LLM-as-judge validator over the assistant output.

    Returns a small dict embedded into the audit trail; an empty dict when
    validator is disabled / skipped. On compliance < threshold a DebugVault
    entry is written. Never raises — broken validator must not break
    generation, see modules/validator/service contract.
    """
    try:
        from modules.validator import validate_output
        from modules.validator.service import get_compliance_threshold
        from modules.debug_vault import write_vault_entry
        from modules.system.service import get_active_character_name
        from modules.system import character as character_service
    except Exception as exc:
        log_audit_entry(
            "validator_integration_import_failed",
            "[Conversation] Validator integration import failed.",
            AuditStatus.WARNING,
            details={"error": str(exc)},
        )
        return {}

    instructions = _build_validator_instructions(decision_context)
    if not instructions:
        # Nothing concrete to validate — skip without an LLM call.
        return {"skipped": True, "skip_reason": "empty_instructions"}

    result = validate_output(
        output=assistant_content,
        instructions=instructions,
    )
    if result.skipped:
        return result.to_dict()

    threshold = get_compliance_threshold()
    summary_payload = result.to_dict()
    summary_payload["threshold"] = threshold
    summary_payload["acceptable"] = result.is_acceptable(threshold)

    if result.is_acceptable(threshold):
        log_audit_entry(
            "validator_pass",
            f"[Validator] compliance {result.compliance:.2f} ≥ {threshold:.2f}",
            AuditStatus.INFO,
            details=summary_payload,
        )
        return summary_payload

    # Below threshold → DebugVault. We still return the result; caller proceeds
    # with the existing output. Auto-reroll arrives in a separate commit.
    try:
        char_name = get_active_character_name(default="default")
        character = character_service.get_or_create_character(char_name) if char_name else None
        character_id = getattr(character, "id", None)
    except Exception:
        character_id = None

    try:
        vault_id = write_vault_entry(
            kind="validation_failed",
            severity="warning",
            summary=(
                f"Validator compliance {result.compliance:.2f} < {threshold:.2f} "
                f"({len(result.violations)} violation(s))"
            ),
            character_id=character_id,
            context={
                "user_message": (last_user_message or {}).get("content", "")[:2000],
                "user_message_id": (last_user_message or {}).get("id"),
                "instructions_preview": instructions[:1000],
            },
            output=assistant_content[:50_000],
            violations=result.violations,
            runtime_meta={
                "provider": provider,
                "model_meta": metadata or {},
                "compliance": round(float(result.compliance), 4),
                "threshold": threshold,
            },
        )
        summary_payload["vault_entry_id"] = vault_id
    except Exception as exc:
        log_audit_entry(
            "validator_vault_write_failed",
            "[Validator] Could not record DebugVault entry for low-compliance output.",
            AuditStatus.WARNING,
            details={"error": str(exc), **summary_payload},
        )

    return summary_payload


def _maybe_run_language_guard(
    *,
    last_user_message: Dict[str, Any],
    assistant_content: str,
    provider: Any,
    metadata: Dict[str, Any] | None,
) -> Dict[str, Any]:
    """Compare dominant unicode script of the assistant output with User.language.

    Never raises. Mirrors the Validator contract: skipped/ok results are
    audit-only; a confirmed mismatch lands in DebugVault as a curated entry.
    Auto-reroll is a follow-up commit — for now we record and proceed.
    """
    try:
        from modules.language_guard import check_language
        from modules.system.user import resolve_user_language
        from modules.system.service import get_active_character_name
        from modules.system import character as character_service
    except Exception as exc:
        log_audit_entry(
            "language_guard_import_failed",
            "[Conversation] Language guard import failed.",
            AuditStatus.WARNING,
            details={"error": str(exc)},
        )
        return {}

    actor_user_uuid = None
    if isinstance(last_user_message, dict):
        actor_user_uuid = (
            last_user_message.get("user_uuid")
            or last_user_message.get("actor_user_uuid")
        )

    character_id = None
    try:
        char_name = get_active_character_name(default="default")
        character = character_service.get_or_create_character(char_name) if char_name else None
        character_id = getattr(character, "id", None)
    except Exception:
        character_id = None

    try:
        expected = resolve_user_language(
            user_uuid=actor_user_uuid,
            character_id=character_id,
        )
    except Exception:
        expected = ""

    result = check_language(assistant_content, expected)
    payload = result.to_dict()
    if result.skipped:
        return payload

    if result.ok:
        log_audit_entry(
            "language_guard_pass",
            f"[LanguageGuard] {result.detected} dominance {result.dominance:.2f}",
            AuditStatus.INFO,
            details=payload,
        )
        return payload

    # mismatch → DebugVault
    try:
        from modules.debug_vault import write_vault_entry
    except Exception as exc:
        log_audit_entry(
            "language_guard_vault_import_failed",
            "[LanguageGuard] DebugVault import failed.",
            AuditStatus.WARNING,
            details={"error": str(exc), **payload},
        )
        return payload

    try:
        vault_id = write_vault_entry(
            kind="language_mismatch",
            severity="warning",
            summary=(
                f"Output script '{result.detected}' does not match expected "
                f"language '{result.expected}' (dominance {result.dominance:.2f})"
            ),
            character_id=character_id,
            context={
                "user_message": (last_user_message or {}).get("content", "")[:2000],
                "user_message_id": (last_user_message or {}).get("id"),
                "expected_language": result.expected,
            },
            output=assistant_content[:50_000],
            violations=[
                f"detected_script={result.detected}",
                f"expected_language={result.expected}",
                f"dominance={result.dominance:.4f}",
            ],
            runtime_meta={
                "provider": provider,
                "model_meta": metadata or {},
                "detected": result.detected,
                "expected": result.expected,
                "dominance": round(float(result.dominance), 4),
            },
        )
        payload["vault_entry_id"] = vault_id
    except Exception as exc:
        log_audit_entry(
            "language_guard_vault_write_failed",
            "[LanguageGuard] Could not record DebugVault entry for language mismatch.",
            AuditStatus.WARNING,
            details={"error": str(exc), **payload},
        )

    return payload


def _maybe_run_confidence(
    *,
    last_user_message: Dict[str, Any],
    assistant_content: str,
) -> Dict[str, Any]:
    """Score how confident PAI should be in this output.

    Never raises. Low confidence is a SIGNAL (audit WARNING + runtime_meta
    update) — NOT an anomaly, so DebugVault is NOT written. The score
    flows into History.runtime_meta.confidence for downstream consumers
    (Factuality check §3.9, low-confidence UI hint Phase 10).
    """
    try:
        from modules.confidence import estimate_confidence, get_confidence_threshold
    except Exception as exc:
        log_audit_entry(
            "confidence_import_failed",
            "[Conversation] Confidence module import failed.",
            AuditStatus.WARNING,
            details={"error": str(exc)},
        )
        return {}

    user_text = ""
    if isinstance(last_user_message, dict):
        user_text = str(last_user_message.get("content") or "").strip()

    result = estimate_confidence(
        user_message=user_text,
        assistant_output=assistant_content,
    )
    payload = result.to_dict()

    if result.skipped:
        return payload

    threshold = get_confidence_threshold()
    payload["threshold"] = round(float(threshold), 4)
    payload["low"] = result.is_low(threshold)

    if result.is_low(threshold):
        log_audit_entry(
            "confidence_low",
            f"[Confidence] {result.score:.2f} < {threshold:.2f}",
            AuditStatus.WARNING,
            details={
                "score": payload["score"],
                "threshold": payload["threshold"],
                "user_message_id": (last_user_message or {}).get("id"),
            },
        )
    else:
        log_audit_entry(
            "confidence_pass",
            f"[Confidence] {result.score:.2f} ≥ {threshold:.2f}",
            AuditStatus.INFO,
            details={"score": payload["score"], "threshold": payload["threshold"]},
        )

    return payload


def _extract_predicted_emotion_meta(decision_context: Dict[str, Any]) -> Dict[str, Any]:
    """Pull PAI's predicted emotion + valence from the current moral_state.

    Returns a dict ready to be merged onto the assistant message's
    runtime_meta. Empty dict when moral_state is missing or empty.
    """
    moral_state = decision_context.get("moral_state") if isinstance(decision_context, dict) else None
    if not isinstance(moral_state, dict) or not moral_state:
        return {}

    emotion = str(moral_state.get("current_emotion") or "").strip()
    if not emotion:
        return {}
    try:
        intensity = float(moral_state.get("emotion_intensity") or 0.0)
    except (TypeError, ValueError):
        intensity = 0.0

    from modules.self_watcher import classify_valence

    return {
        "pai_predicted_emotion": emotion,
        "pai_predicted_valence": classify_valence(emotion),
        "pai_predicted_intensity": round(max(0.0, min(intensity, 1.0)), 4),
    }


def _maybe_run_self_watcher(
    *,
    decision_context: Dict[str, Any],
    last_user_message: Dict[str, Any],
    history: list,
) -> Dict[str, Any]:
    """Compare PAI's prediction on the previous turn with the user's
    current reaction. Records an expectation_events row on mismatch.

    Never raises. Self-Watcher is observation-only and must not break
    the generation pipeline.
    """
    try:
        from modules.self_watcher import check_expectation
        from modules.system.service import get_active_character_name
        from modules.system import character as character_service
    except Exception as exc:
        log_audit_entry(
            "self_watcher_import_failed",
            "[Conversation] Self-Watcher import failed.",
            AuditStatus.WARNING,
            details={"error": str(exc)},
        )
        return {}

    # Pull the previous assistant message from history. ``history`` here
    # is the sanitized list passed to the LLM — assistant turns carry
    # their runtime_meta in the stored DB row, NOT in this list, so we
    # have to fetch the row by id.
    prev_assistant_meta: Dict[str, Any] = {}
    prev_assistant_message_id: Optional[str] = None
    try:
        for item in reversed(history or []):
            if isinstance(item, dict) and item.get("role") == "assistant":
                msg_id = str(item.get("id") or "").strip()
                if not msg_id:
                    continue
                row = database_service.get_message_by_id(msg_id)
                if not isinstance(row, dict):
                    continue
                meta = row.get("runtime_meta")
                if isinstance(meta, dict) and meta:
                    prev_assistant_meta = meta
                    prev_assistant_message_id = msg_id
                break
    except Exception:
        prev_assistant_meta = {}
        prev_assistant_message_id = None

    if not prev_assistant_meta:
        return {"skipped": True, "skip_reason": "no_previous_prediction"}

    analysis = decision_context.get("analysis") if isinstance(decision_context, dict) else None
    tone_primary = ""
    tone_intensity = 0.5
    if isinstance(analysis, dict):
        understanding = analysis.get("understanding") or {}
        if isinstance(understanding, dict):
            tone = understanding.get("emotional_tone") or {}
            if isinstance(tone, dict):
                tone_primary = str(tone.get("primary") or "").strip()
                try:
                    tone_intensity = float(tone.get("intensity") or 0.5)
                except (TypeError, ValueError):
                    tone_intensity = 0.5

    if not tone_primary:
        return {"skipped": True, "skip_reason": "no_user_tone"}

    try:
        char_name = get_active_character_name(default="default")
        character = character_service.get_or_create_character(char_name) if char_name else None
        character_id = getattr(character, "id", None) or ""
    except Exception:
        character_id = ""

    triggering_message_id = None
    if isinstance(last_user_message, dict):
        triggering_message_id = str(last_user_message.get("id") or "").strip() or None

    result = check_expectation(
        character_id=character_id,
        prev_assistant_meta=prev_assistant_meta,
        prev_assistant_message_id=prev_assistant_message_id,
        current_user_tone=tone_primary,
        current_user_intensity=tone_intensity,
        triggering_user_message_id=triggering_message_id,
    )
    return result.to_dict()


def _maybe_run_factuality(
    *,
    assistant_content: str,
    confidence_payload: Dict[str, Any] | None,
) -> Dict[str, Any]:
    """Run the factuality gate (§3.9) over the assistant output.

    Never raises. The gate is normally piped through §3.8 confidence
    (low-confidence outputs are the ones worth checking). Result lives in
    runtime_meta.factuality only — does NOT rewrite the output.
    """
    try:
        from modules.factuality import check_factuality
    except Exception as exc:
        log_audit_entry(
            "factuality_import_failed",
            "[Conversation] Factuality module import failed.",
            AuditStatus.WARNING,
            details={"error": str(exc)},
        )
        return {}

    confidence_low = False
    if isinstance(confidence_payload, dict):
        confidence_low = bool(confidence_payload.get("low"))

    result = check_factuality(
        output=assistant_content,
        confidence_low=confidence_low,
    )
    payload = result.to_dict()

    if result.skipped:
        return payload

    if not result.supported:
        log_audit_entry(
            "factuality_unverified",
            f"[Factuality] {len(result.claims)} claim(s) unverified against local memory.",
            AuditStatus.WARNING,
            details={
                "claims": result.claims,
                "sources_found": result.sources_found,
            },
        )
    else:
        log_audit_entry(
            "factuality_supported",
            f"[Factuality] {result.sources_found} corroborating source(s) found.",
            AuditStatus.INFO,
            details={
                "claims": result.claims,
                "sources_found": result.sources_found,
            },
        )

    return payload


def _build_generation_options() -> dict:
    exclude = ["name", "description"]
    full_settings = config_service.get_config_value("generate_settings", {})
    return {k: v for k, v in full_settings.items() if k not in exclude}


def _dl_console_log(message: str, details: Optional[Dict[str, Any]] = None) -> None:
    prefix = "[Decision Layer]"
    if not details:
        print(f"{prefix}: {message}")
        return
    try:
        payload = json.dumps(details, ensure_ascii=False, default=str)
    except Exception:
        payload = str(details)
    if len(payload) > 1800:
        payload = payload[:1800].rstrip() + "..."
    print(f"{prefix}: {message} | {payload}")


def _build_main_chat_image_prompt(
    *,
    user_message: Optional[Dict[str, Any]],
    decision_context: Dict[str, Any],
    memory_context: Dict[str, Any],
) -> str:
    image_decision = decision_context.get("image_generation") or {}
    analysis = decision_context.get("analysis") or {}
    moral_state = decision_context.get("moral_state") or {}
    visual_context = decision_context.get("visual_context") or {}
    cfg = config_service.get_config_value("synthesis.prompting", {}) or {}
    appearance = ""
    try:
        from modules.visual_profile_store import visual_profile_store_service

        visual_profile = visual_profile_store_service.load_profile()
        appearance = str(
            visual_profile.appearance_textarea
            or visual_profile.character_name
            or ""
        ).strip()
    except Exception:
        visual_profile = cfg.get("visual_profile") if isinstance(cfg, dict) else {}
        if isinstance(visual_profile, dict):
            appearance = str(
                visual_profile.get("appearance_textarea")
                or visual_profile.get("character_name")
                or ""
            ).strip()
    fallback_appearance = str((cfg or {}).get("appearance_prompt") or "").strip() if isinstance(cfg, dict) else ""
    user_text = str((user_message or {}).get("content") or "").strip()
    recent_topic = str(((memory_context or {}).get("conversation_state") or {}).get("last_topic") or "").strip()
    history = (memory_context or {}).get("recent_history") or []
    history_preview = []
    for item in history[-6:]:
        if isinstance(item, dict):
            history_preview.append(
                {
                    "role": item.get("role"),
                    "content": str(item.get("content") or "")[:260],
                    "timestamp": item.get("timestamp"),
                }
            )
    visual_summary = ""
    if isinstance(visual_context, dict):
        attachments = (visual_context.get("attachments") or {}).get("items") or []
        screen = visual_context.get("screen") or {}
        visual_parts = []
        for attachment in attachments[:3]:
            if isinstance(attachment, dict) and attachment.get("description"):
                visual_parts.append(str(attachment.get("description")))
        if isinstance(screen, dict) and screen.get("description"):
            visual_parts.append(str(screen.get("description")))
        visual_summary = "\n".join(visual_parts)

    prompt_payload = {
        "user_message": user_text,
        "recent_history": history_preview,
        "recent_topic": recent_topic,
        "analyzer_image_decision": image_decision,
        "themes": ((analysis.get("input_analysis") or {}).get("dominant_themes") or [])[:8],
        "emotion": moral_state.get("current_emotion") or moral_state.get("summary"),
        "visual_context": visual_summary,
        "character_appearance": appearance or fallback_appearance,
    }

    system_prompt = (
        "You write prompts for an image generator inside a character chat system. "
        "Create one concise, visually concrete prompt for the image the character should attach now. "
        "Use current conversation context, visual context if present, and the character appearance anchor if present. "
        "If context is weak, create a natural in-character casual image. "
        "Avoid text, captions, watermarks, UI, logos. "
        "Return ONLY valid JSON with fields: prompt, negative_prompt."
    )
    try:
        result = generation_manager.generate(
            GenerateRequest(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(prompt_payload, ensure_ascii=False, indent=2),
                    },
                ],
                options={"temperature": 0.75, "max_tokens": 700},
                metadata={"mode": "main_chat_image_prompt"},
            )
        )
        raw = (result.content or "").strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE | re.DOTALL).strip()
        parsed = json.loads(raw)
        prompt = str(parsed.get("prompt") or "").strip()
        negative = str(parsed.get("negative_prompt") or "").strip()
        if prompt:
            usage = _extract_usage_metadata(result.raw)
            return json.dumps(
                {
                    "prompt": prompt,
                    "negative_prompt": negative,
                    "provider": result.provider,
                    "usage": usage,
                },
                ensure_ascii=False,
            )
    except Exception as exc:
        _dl_console_log(
            "LLM-промпт для картинки не получен, использую fallback.",
            {"error": str(exc)},
        )

    parts = [
        "Generate an in-character image for the main chat reply.",
        "It should feel like a natural attachment sent by the assistant, not a poster or UI screenshot.",
    ]
    if appearance or fallback_appearance:
        parts.append(f"Character appearance/style anchor: {appearance or fallback_appearance}")
    if user_text:
        parts.append(f"User message context: {user_text[:700]}")
    if recent_topic:
        parts.append(f"Recent topic: {recent_topic}")
    if visual_summary:
        parts.append(f"Visual context: {visual_summary[:700]}")
    style_hint = str((image_decision or {}).get("style_hint") or "").strip()
    if style_hint:
        parts.append(f"Analyzer style hint: {style_hint}")
    parts.append("Avoid text, watermarks, captions, logos, and UI elements in the image.")
    return json.dumps({"prompt": "\n".join(parts), "negative_prompt": ""}, ensure_ascii=False)


async def _prepare_main_chat_image_context(
    *,
    decision_context: Dict[str, Any],
    last_user_message: Optional[Dict[str, Any]],
    memory_context: Dict[str, Any],
    trace_hook: Optional[Callable[[dict], Awaitable[None]]] = None,
) -> List[dict]:
    image_decision = decision_context.get("image_generation") or {}
    if not isinstance(image_decision, dict) or not image_decision.get("enabled"):
        _dl_console_log(
            "Генерация картинки для ответа не выполняется.",
            {"reason": (image_decision or {}).get("reason", "disabled")},
        )
        return []

    prompt_started = time.perf_counter()
    await _emit_runtime_trace(
        trace_hook,
        "image_prompt",
        "start",
        details={"reason": image_decision.get("reason"), "source": image_decision.get("source")},
    )
    _dl_console_log("Запрашиваю промпт для генерации картинки через LLM.")
    prompt_payload = _build_main_chat_image_prompt(
        user_message=last_user_message,
        decision_context=decision_context,
        memory_context=memory_context,
    )
    try:
        parsed_prompt = json.loads(prompt_payload)
    except Exception:
        parsed_prompt = {"prompt": prompt_payload, "negative_prompt": ""}
    prompt = str(parsed_prompt.get("prompt") or prompt_payload).strip()
    generated_negative = str(parsed_prompt.get("negative_prompt") or "").strip()
    prompt_usage = parsed_prompt.get("usage") if isinstance(parsed_prompt.get("usage"), dict) else {}
    prompt_provider = str(parsed_prompt.get("provider") or "")
    _dl_console_log("Промпт для генерации картинки получен.", {"prompt": prompt[:700]})
    await _emit_runtime_trace(
        trace_hook,
        "image_prompt",
        "end",
        started_at=prompt_started,
        details={
            "provider": prompt_provider,
            "usage": prompt_usage,
            "prompt_length": len(prompt),
        },
    )

    image_cfg = config_service.get_config_value("telegram.image", {}) or {}
    synthesis_provider = str(
        config_service.get_config_value("synthesis.active_provider", "") or ""
    ).strip().lower()
    if synthesis_provider == "sd_webui":
        synthesis_provider = "stable_diffusion_webui"
    if synthesis_provider not in {"core", "comfyui", "stable_diffusion_webui", "diffusers"}:
        synthesis_provider = "auto"

    if synthesis_provider == "comfyui":
        comfy_cfg = config_service.get_config_value("synthesis.comfyui", {}) or {}
        model_id = None
        width = max(64, int(comfy_cfg.get("width", 1024) or 1024))
        height = max(64, int(comfy_cfg.get("height", 1024) or 1024))
        steps = max(1, int(comfy_cfg.get("steps", 30) or 30))
        guidance = float(comfy_cfg.get("cfg", 7.0) or 7.0)
        sampler = str(comfy_cfg.get("sampler") or "").strip() or None
        scheduler = str(comfy_cfg.get("scheduler") or "").strip() or None
        comfyui_checkpoint = str(comfy_cfg.get("default_model") or "").strip() or None
        configured_negative = str(
            config_service.get_config_value("synthesis.prompting.default_negative_prompt", "")
            or image_cfg.get("negative_prompt")
            or ""
        ).strip()
    elif synthesis_provider in {"core", "diffusers"}:
        diffusers_cfg = config_service.get_config_value("synthesis.diffusers", {}) or {}
        model_id = str(diffusers_cfg.get("default_model") or image_cfg.get("default_model") or "").strip() or None
        width = max(64, int(diffusers_cfg.get("width") or image_cfg.get("width", 1024) or 1024))
        height = max(64, int(diffusers_cfg.get("height") or image_cfg.get("height", 1024) or 1024))
        steps = max(1, int(diffusers_cfg.get("steps") or image_cfg.get("num_inference_steps", 30) or 30))
        guidance = float(diffusers_cfg.get("cfg") if diffusers_cfg.get("cfg") is not None else image_cfg.get("guidance_scale", 7.0) or 7.0)
        sampler = str(diffusers_cfg.get("sampler") or "").strip() or None
        scheduler = str(diffusers_cfg.get("scheduler") or "").strip() or None
        comfyui_checkpoint = None
        configured_negative = str(image_cfg.get("negative_prompt") or "").strip()
    else:
        model_id = str(image_cfg.get("default_model") or "").strip() or None
        width = max(64, int(image_cfg.get("width", 1024) or 1024))
        height = max(64, int(image_cfg.get("height", 1024) or 1024))
        steps = max(1, int(image_cfg.get("num_inference_steps", 9) or 9))
        guidance = float(image_cfg.get("guidance_scale", 0.0) or 0.0)
        sampler = None
        scheduler = None
        comfyui_checkpoint = None
        configured_negative = str(image_cfg.get("negative_prompt") or "").strip()
    negative = ", ".join(
        part for part in [generated_negative, configured_negative] if part
    ) or None

    try:
        generation_started = time.perf_counter()
        await _emit_runtime_trace(
            trace_hook,
            "image_generation",
            "start",
            details={
                "provider": synthesis_provider,
                "model": model_id,
                "checkpoint": comfyui_checkpoint,
                "width": width,
                "height": height,
                "steps": steps,
                "check_enabled": bool(
                    (config_service.get_config_value("synthesis.prompting", {}) or {}).get("assess_enabled", True)
                ),
                "retry_enabled": bool(
                    (config_service.get_config_value("synthesis.prompting", {}) or {}).get("retry_enabled", True)
                ),
            },
        )
        _dl_console_log(
            "Отправляю запрос в модуль генерации изображения.",
            {
                "provider": synthesis_provider,
                "model": model_id,
                "checkpoint": comfyui_checkpoint,
                "width": width,
                "height": height,
                "steps": steps,
            },
        )
        result = await media_generation_pipeline.run_image(
            MediaPipelineRequest(
                mode="chat_auto",
                prompt=prompt,
                scenario_key="main_chat",
                negative_prompt=negative,
                image_provider="auto",
                image_model=model_id,
                width=width,
                height=height,
                num_inference_steps=steps,
                guidance_scale=guidance,
                sampler=sampler,
                scheduler=scheduler,
                comfyui_checkpoint=comfyui_checkpoint,
                use_prompt_builder=False,
                review_generated_image=False,
                use_visual_intent=True,
                source="main_chat",
                character_name=get_active_character_name(default="default"),
                metadata={"allow_scenario_controls": True},
            ),
            trace_hook=trace_hook,
        )
        await _emit_runtime_trace(
            trace_hook,
            "image_generation",
            "end",
            started_at=generation_started,
            details={
                "provider": getattr(result, "provider", None),
                "model": getattr(result, "model", None) or model_id or "z_image_turbo",
                "bytes": len(getattr(result, "image_bytes", b"") or b""),
                "mime": str(getattr(result, "mime_type", "") or "image/png"),
            },
        )
    except Exception as exc:
        await _emit_runtime_trace(
            trace_hook,
            "image_generation",
            "error",
            details={"error": str(exc)},
        )
        _dl_console_log("Генерация картинки завершилась ошибкой.", {"error": str(exc)})
        log_audit_entry(
            "main_chat_dl_image_generation_failed",
            "[DecisionLayer] Main chat image generation failed.",
            AuditStatus.WARNING,
            details={"error": str(exc)},
        )
        return []

    if not getattr(result, "image_bytes", b""):
        _dl_console_log("Генерация картинки вернула пустой результат.")
        return []

    mime_type = str(getattr(result, "mime_type", "") or "image/png")
    description = ""
    try:
        vision_started = time.perf_counter()
        await _emit_runtime_trace(trace_hook, "image_vision", "start")
        _dl_console_log("Передаю созданную картинку в Vision для описания.")
        with Image.open(BytesIO(result.image_bytes)) as image:
            visual_module = VisualModule()
            vision_result = await asyncio.to_thread(
                visual_module.describe_image,
                image.convert("RGB"),
                "Describe this generated image for the assistant before it writes the final reply. Be concise and factual.",
            )
        description = str((vision_result or {}).get("summary") or "").strip()
        if description:
            _dl_console_log("Vision описание картинки получено.", {"description": description[:700]})
        else:
            _dl_console_log("Vision вернул пустое описание картинки.")
        await _emit_runtime_trace(
            trace_hook,
            "image_vision",
            "end",
            started_at=vision_started,
            details={
                "description_length": len(description),
                "status": "described" if description else "empty",
            },
        )
    except Exception as exc:
        description = f"Generated image prompt: {prompt[:700]}"
        await _emit_runtime_trace(
            trace_hook,
            "image_vision",
            "error",
            details={"error": str(exc)},
        )
        _dl_console_log(
            "Vision описание картинки не получено, использую описание по промпту.",
            {"error": str(exc)},
        )

    media = {
        "id": str(uuid.uuid4()),
        "name": f"main_chat_image_{int(time.time())}.png",
        "mimeType": mime_type,
        "category": "image",
        "size": len(result.image_bytes),
        "description": description or prompt[:900],
        "data": result.image_base64,
    }
    decision_context["generated_image_context"] = {
        "prompt": prompt,
        "negative_prompt": negative or "",
        "description": description or media["description"],
        "model": getattr(result, "model", None),
        "mime": mime_type,
        "size": media["size"],
    }
    decision_context["system_prompt"] = (
        str(decision_context.get("system_prompt") or "")
        + "\n\nGenerated image prepared for this reply:\n"
        + f"- Prompt: {prompt[:1200]}\n"
        + f"- Vision description: {(description or media['description'])[:1200]}\n"
        + "Write the final reply as if this image is attached to your message. Do not claim details that contradict the vision description."
    )
    _dl_console_log(
        "Картинка для ответа создана и подготовлена для финального ответа.",
        {
            "bytes": media["size"],
            "mime": mime_type,
            "model": getattr(result, "model", None),
            "has_description": bool(description),
        },
    )
    return [media]


def _extract_usage_metadata(raw_chunk: Any) -> Dict[str, Any]:
    if not isinstance(raw_chunk, dict):
        return {}
    if isinstance(raw_chunk.get("usage"), dict):
        return dict(raw_chunk.get("usage") or {})
    keys = [
        "total_duration",
        "load_duration",
        "prompt_eval_count",
        "prompt_eval_duration",
        "eval_count",
        "eval_duration",
        "prompt_tokens",
        "response_tokens",
        "completion_tokens",
        "total_tokens",
        "completion_tokens_details",
    ]
    usage: Dict[str, Any] = {}
    for key in keys:
        if key in raw_chunk:
            usage[key] = raw_chunk.get(key)
    return usage


async def _emit_runtime_trace(
    trace_hook: Optional[Callable[[dict], Awaitable[None]]],
    stage: str,
    state: str,
    *,
    started_at: Optional[float] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    if trace_hook is None:
        return
    payload: Dict[str, Any] = {"stage": stage, "state": state}
    if started_at is not None:
        payload["elapsed_ms"] = round((time.perf_counter() - started_at) * 1000, 2)
    if details:
        payload["details"] = details
    await trace_hook(payload)


def _voice_streaming_available() -> bool:
    return config_service.get_config_value("voice.enabled", False) and config_service.get_config_value(
        "voice.streaming_tts", False
    )


def _emit_generation_tool_event(
    *,
    tool_name: str,
    content: str,
    status: str,
    runtime_meta: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        tool_event_bus.emit_tool_event(
            tool_name=tool_name,
            content=content,
            status=status,
            source="generation_pipeline",
            runtime_meta=runtime_meta or {},
            tags=["tool", "generation", status],
        )
    except Exception:
        # Tool event persistence should never break generation flow.
        pass


def _recover_empty_content_with_retries(
    *,
    chat_history: list,
    options: dict,
    assistant_reasoning: str,
    mode: str,
) -> tuple[str, str, str]:
    """
    Recovery when provider produced only reasoning and empty visible content.
    Does not try to parse visible text from reasoning directly.
    Makes up to 2 strict retry attempts, then returns empty content.
    Returns: (content, reasoning, provider)
    """
    attempts = 2
    prior_reasoning = (assistant_reasoning or "").strip()
    used_provider = ""

    for attempt in range(1, attempts + 1):
        recovery_instruction = (
            "Your previous response produced empty visible content. "
            "Return ONLY one short final user-facing reply. "
            "No reasoning, no analysis, no lists, no metadata."
        )

        retry_options = dict(options or {})
        retry_options["__think"] = False
        if attempt >= 2:
            try:
                base_predict = int(retry_options.get("num_predict", 2048) or 2048)
            except Exception:
                base_predict = 2048
            retry_options["num_predict"] = max(base_predict, min(base_predict + 512, 4096))

        recovery_messages = _build_empty_content_recovery_messages(
            chat_history,
            recovery_instruction=recovery_instruction,
            previous_reasoning=prior_reasoning,
        )
        print(
            f"[Generator] Empty visible response; retrying generation "
            f"({mode}, attempt {attempt}/{attempts})."
        )
        log_audit_entry(
            "conversation_empty_content_recovery_attempt",
            "[Conversation] Empty visible response; retrying generation.",
            AuditStatus.WARNING,
            details={
                "mode": mode,
                "attempt": attempt,
                "attempts": attempts,
                "reasoning_length": len(prior_reasoning),
                "reasoning_reused": bool(prior_reasoning),
                "reasoning_role": "tool" if prior_reasoning else None,
            },
        )
        result = generation_manager.generate(
            GenerateRequest(
                messages=recovery_messages,
                options=retry_options,
                metadata={"mode": f"{mode}_empty_content_recovery", "attempt": attempt},
            )
        )
        used_provider = str(result.provider or used_provider or "")
        raw = (result.content or "").strip()
        recovered_reasoning = (result.reasoning or "").strip()
        if recovered_reasoning:
            recovered_content = raw
            prior_reasoning = recovered_reasoning
        else:
            recovered_content, parsed_reasoning = split_reasoning(raw)
            prior_reasoning = (parsed_reasoning or prior_reasoning).strip()

        if (recovered_content or "").strip():
            return (recovered_content or "").strip(), (prior_reasoning or "").strip(), used_provider

    log_audit_entry(
        "conversation_empty_content_recovery_exhausted",
        "[Conversation] Empty content recovery exhausted after retries.",
        AuditStatus.ERROR,
        details={"mode": mode, "attempts": attempts, "provider": used_provider},
    )
    return "", (prior_reasoning or "").strip(), used_provider


def _build_empty_content_recovery_messages(
    chat_history: list,
    *,
    recovery_instruction: str,
    previous_reasoning: str,
) -> list:
    messages = list(chat_history or [])
    reasoning = str(previous_reasoning or "").strip()
    if reasoning:
        messages.append(
            {
                "role": "tool",
                "name": "thinking",
                "content": (
                    "Previous assistant internal thinking. Use it only as context to produce "
                    "the missing final visible answer. Do not quote or continue this thinking.\n\n"
                    f"{reasoning}"
                ),
            }
        )
    messages.append({"role": "user", "content": recovery_instruction})
    return messages


async def _ensure_voice_ready() -> None:
    retries = 5
    while voice_state.stage() is VoiceStage.PREPARING and retries > 0:
        await asyncio.sleep(0.2)
        retries -= 1


# ---------------------------------------------------------------------------
# Standard generation
# ---------------------------------------------------------------------------
async def generate_standard(
    decision_context: Dict[str, Any],
    history: list,
    last_user_message: Dict[str, Any],
    *,
    emit_ws_fn: Optional[Callable[[dict], Awaitable[None]]] = None,
    trace_hook: Optional[Callable[[dict], Awaitable[None]]] = None,
    store: bool = True,
    return_full: bool = False,
) -> Dict[str, Any]:
    print("[Generator] Старт стандартной генерации.")
    sanitized_history = _sanitize_history(history, drop_media=True)
    log_audit_entry(
        event_type="conversation_standard_start",
        msg="[Conversation] Старт стандартной генерации",
        status=AuditStatus.INFO,
        details={
            "inputs": {"history": sanitized_history},
            "decision_keys": list(decision_context.keys()),
        },
    )

    if not last_user_message:
        raise ValueError("No user message found in history")

    system_prompt = decision_context.get("system_prompt", "")
    memory_context = decision_context.get("memory_context", {}) or {}
    memory_meta = decision_context.get("memory_meta", {}) or {}
    prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()[:12]
    print("[Generator] Системный промпт готов для стандартного режима.")

    user_media_for_storage = _extract_media_payload(last_user_message) or None
    user_media_for_emit = _sanitize_media_items(
        last_user_message.get("media") if last_user_message else None
    )
    log_audit_entry(
        "conversation_prompt_ready",
        "[Conversation] Сформирован системный промпт для стандартной генерации.",
        AuditStatus.INFO,
        details={
            "prompt_length": len(system_prompt),
            "prompt_hash": prompt_hash,
            "history_length": len(history),
        },
    )

    if emit_ws_fn and last_user_message:
        await emit_ws_fn(
            {
                "type": "message",
                "role": "user",
                "content": last_user_message.get("content", ""),
                "id": last_user_message.get("id"),
                "timestamp": last_user_message.get("timestamp"),
                "media": user_media_for_emit,
            }
        )
        await emit_ws_fn({"type": "system", "event": "typing_start"})
        log_audit_entry(
            "conversation_user_message_emitted_standard",
            "[Conversation] Пользовательское сообщение отправлено (standard).",
            AuditStatus.INFO,
            details={
                "message_id": last_user_message.get("id"),
                "has_media": bool(user_media_for_emit),
                "media_count": len(user_media_for_emit),
            },
        )
        print("[Generator] Пользовательское сообщение отправлено (standard).")

    assistant_media_payload = await _prepare_main_chat_image_context(
        decision_context=decision_context,
        last_user_message=last_user_message,
        memory_context=memory_context,
        trace_hook=trace_hook,
    )
    system_prompt = decision_context.get("system_prompt", system_prompt)

    chat_history = build_chat_request(history)
    chat_history.insert(0, {"role": "system", "content": system_prompt})
    direct_image_count = 0
    if _should_pass_media_to_main_ollama_model():
        direct_image_count = _attach_images_to_last_user_message(chat_history, user_media_for_storage)
        if direct_image_count:
            log_audit_entry(
                "conversation_standard_direct_ollama_images",
                "[Conversation] Image attachments attached to the main Ollama request.",
                AuditStatus.INFO,
                details={"count": direct_image_count},
            )

    request_payload = GenerateRequest(
        messages=chat_history,
        options=_build_generation_options(),
        metadata={"mode": "standard"},
    )
    request_snapshot = {
        "messages": chat_history,
        "options": request_payload.options,
        "metadata": request_payload.metadata,
    }
    log_audit_entry(
        "conversation_standard_request_built",
        "[Conversation] Сформирован запрос стандартной генерации.",
        AuditStatus.INFO,
        details=request_snapshot,
    )
    print("[Generator] Запрос к провайдерам подготовлен (standard).")

    try:
        generate_result = generation_manager.generate(request_payload)
        print("[Generator] Провайдер вернул результат (standard).")
    except NoProviderResolved as exc:
        print("[Generator] Провайдеры недоступны (standard).")
        provider_errors = _extract_provider_errors(exc)
        _emit_generation_tool_event(
            tool_name="generation.provider",
            status="error",
            content=(
                "[ERROR]: generation provider not available. "
                + (
                    "; ".join(
                        f"{item.get('provider')}: {item.get('reason')}"
                        for item in provider_errors
                    )
                    if provider_errors
                    else str(exc)
                )
            ),
            runtime_meta={
                "mode": "standard",
                "providers": provider_errors,
            },
        )
        log_audit_entry(
            event_type="generation_provider_failure",
            msg="[Generator] Не удалось подобрать провайдера",
            status=AuditStatus.ERROR,
            details={
                "errors": provider_errors
                if provider_errors
                else [{"provider": "unknown", "reason": str(exc)}],
                "request": request_snapshot,
            },
        )
        summary = "; ".join(
            f"{item['provider']}: {item['reason']}" for item in provider_errors
        )
        if emit_ws_fn:
            await emit_ws_fn({"type": "system", "event": "typing_end"})
            payload = {
                "type": "error",
                "message": "Generation provider not available",
            }
            if provider_errors:
                payload["details"] = provider_errors
            await emit_ws_fn(payload)
        raise RuntimeError(summary or "Generation provider not available") from exc

    assistant_raw = normalize_output_text((generate_result.content or "").strip())
    assistant_reasoning = (generate_result.reasoning or "").strip()
    if assistant_reasoning:
        assistant_content = assistant_raw
    else:
        assistant_content, assistant_reasoning = split_reasoning(assistant_raw)
    if not assistant_content:
        try:
            recovered_content, recovered_reasoning, recovered_provider = _recover_empty_content_with_retries(
                chat_history=chat_history,
                options=request_payload.options,
                assistant_reasoning=assistant_reasoning,
                mode="standard",
            )
            if recovered_content:
                assistant_content = normalize_output_text(recovered_content)
                assistant_reasoning = recovered_reasoning or assistant_reasoning
                if recovered_provider:
                    generate_result.provider = recovered_provider
                log_audit_entry(
                    "conversation_standard_empty_content_recovered",
                    "[Conversation] Empty content recovered by retry regeneration.",
                    AuditStatus.WARNING,
                    details={"provider": generate_result.provider},
                )
        except Exception as exc:
            log_audit_entry(
                "conversation_standard_empty_content_recovery_failed",
                "[Conversation] Empty content recovery failed.",
                AuditStatus.WARNING,
                details={"error": str(exc)},
            )
    log_audit_entry(
        "conversation_standard_result",
        "[Conversation] Результат стандартной генерации получен.",
        AuditStatus.SUCCESS,
        details={
            "provider": generate_result.provider,
            "assistant_content_length": len(assistant_content),
            "assistant_reasoning_length": len(assistant_reasoning or ""),
            "metadata": generate_result.metadata,
        },
    )
    print("[Generator] Обработан ответ провайдера (standard).")

    # Validator pass (§3.5). Opt-in via validator.enabled. On low-compliance
    # the output still flows downstream — we just record the anomaly in
    # DebugVault for later human review. Auto-reroll is intentionally NOT
    # part of this commit; it lands as a follow-up so the seam can be
    # observed under load before adding retry latency.
    validator_payload = _maybe_run_validator(
        decision_context=decision_context,
        last_user_message=last_user_message,
        assistant_content=assistant_content,
        provider=generate_result.provider,
        metadata=generate_result.metadata,
    )

    # Language guard (§3.5-bis). Opt-in via language_guard.enabled. No LLM
    # cost — pure CPU script-ratio counter. Auto-reroll is a follow-up.
    language_guard_payload = _maybe_run_language_guard(
        last_user_message=last_user_message,
        assistant_content=assistant_content,
        provider=generate_result.provider,
        metadata=generate_result.metadata,
    )

    # Confidence estimation (§3.8). Opt-in. One mini LLM call per sync
    # generation. Low confidence is a SIGNAL — written to History.runtime_meta
    # and surfaces as a WARNING audit log, but does NOT land in DebugVault.
    confidence_payload = _maybe_run_confidence(
        last_user_message=last_user_message,
        assistant_content=assistant_content,
    )

    # Factuality check (§3.9). Opt-in, CPU-only (no extra LLM call).
    # By default gated on confidence_low — runs only when §3.8 already
    # flagged the output. Looks each extracted claim up against PAI's
    # OWN memory (lorebook). Web/internet check belongs to §3.10 which
    # is OUT OF CORE.
    factuality_payload = _maybe_run_factuality(
        assistant_content=assistant_content,
        confidence_payload=confidence_payload,
    )

    # Self-Watcher (§3.7). Compares PAI's prediction on the previous
    # turn (stored in History.runtime_meta) with the user's actual
    # emotional tone on this turn (from analyzer). Records mismatches
    # for nightly diary reflection. Does NOT influence the current turn.
    self_watcher_payload = _maybe_run_self_watcher(
        decision_context=decision_context,
        last_user_message=last_user_message,
        history=history,
    )

    assistant_message_obj = None
    suppress_user_echo = bool(last_user_message.get("suppress_user_echo")) if last_user_message else False
    if store and assistant_content:
        memory_context_for_tags = memory_context
        extra_tags = list(memory_context_for_tags.get("short_term_themes") or [])
        user_display_content = last_user_message.get("display_content", last_user_message.get("content", ""))
        user_tags = _generate_tags_for_text(user_display_content, extra=extra_tags)
        existing_user = None
        message_id = str(last_user_message.get("id") or "").strip()
        if message_id:
            existing_user = database_service.get_message_by_id(message_id)
        if not existing_user and not suppress_user_echo:
            database_service.add_message_to_history(
                character_name=get_active_character_name(default="default"),
                role="user",
                content=user_display_content,
                timestamp=datetime.now(timezone.utc),
                media=user_media_for_storage,
                tags=user_tags,
            )

        assistant_tags = _generate_tags_for_text(
            assistant_content, extra=extra_tags + ["assistant"]
        )
        assistant_message_obj = database_service.add_message_to_history(
            character_name=get_active_character_name(default="default"),
            role="assistant",
            content=assistant_content,
            timestamp=datetime.now(timezone.utc),
            media=assistant_media_payload or None,
            tags=assistant_tags,
        )
        stored_media = getattr(assistant_message_obj, "media_payload", None)
        if stored_media:
            assistant_media_payload = stored_media
        if assistant_reasoning:
            database_service.add_reasoning_entry(
                assistant_message_obj.id,
                assistant_reasoning,
            )

        # Persist compliance metadata (§3.8 confidence, §3.9 factuality,
        # §3.7 self-watcher prediction) onto the message's runtime_meta
        # so the UI / downstream tools can read it without re-running
        # anything. merge=True keeps any upstream metadata intact.
        meta_update: Dict[str, Any] = {}
        if (
            confidence_payload
            and not confidence_payload.get("skipped")
            and "score" in confidence_payload
        ):
            meta_update["confidence"] = confidence_payload["score"]
            meta_update["confidence_threshold"] = confidence_payload.get("threshold")
            meta_update["confidence_low"] = confidence_payload.get("low", False)

        if (
            factuality_payload
            and not factuality_payload.get("skipped")
            and factuality_payload.get("checked")
        ):
            meta_update["factuality"] = {
                "supported": factuality_payload.get("supported"),
                "sources_found": factuality_payload.get("sources_found"),
                "claims": factuality_payload.get("claims", []),
            }

        # §3.7 — stamp PAI's prediction on THIS assistant message so the
        # NEXT turn's Self-Watcher pass has something to compare against.
        meta_update.update(_extract_predicted_emotion_meta(decision_context))

        if meta_update and getattr(assistant_message_obj, "id", None):
            try:
                database_service.update_history_runtime_meta(
                    assistant_message_obj.id, meta_update, merge=True
                )
            except Exception as exc:
                log_audit_entry(
                    "compliance_meta_persist_failed",
                    "[Compliance] Could not persist meta on runtime_meta.",
                    AuditStatus.WARNING,
                    details={"error": str(exc), "message_id": assistant_message_obj.id},
                )

    if emit_ws_fn and assistant_content:
        display_content = assistant_content
        if assistant_reasoning:
            display_content = f"<think>\n{assistant_reasoning}\n</think>\n\n{assistant_content}"
        await emit_ws_fn(
            {
                "type": "message",
                "role": "assistant",
                "content": display_content,
                "provider": generate_result.provider,
                "id": getattr(assistant_message_obj, "id", str(uuid.uuid4())),
                "timestamp": getattr(
                    assistant_message_obj, "timestamp", datetime.now(timezone.utc)
                ).isoformat(),
                "media": _sanitize_media_items(assistant_media_payload),
            }
        )
        await emit_ws_fn({"type": "system", "event": "typing_end"})
        log_audit_entry(
            "conversation_standard_emit_assistant",
            "[Conversation] Ответ ассистента отправлен (standard).",
            AuditStatus.INFO,
            details={
                "provider": generate_result.provider,
                "message_id": getattr(assistant_message_obj, "id", None),
            },
        )
        print("[Generator] Ответ ассистента отправлен (standard).")
    elif emit_ws_fn:
        await emit_ws_fn({"type": "system", "event": "typing_end"})

    decision_layer.handle_response(assistant_content)
    print("[Generator] Ответ передан в голосовой движок (standard).")

    if not return_full:
        log_audit_entry(
            "conversation_standard_complete",
            "[Conversation] Стандартная генерация завершена.",
            AuditStatus.INFO,
            details={
                "provider": generate_result.provider,
                "assistant_content": assistant_content,
                "assistant_reasoning": assistant_reasoning,
                "validator": validator_payload,
                "language_guard": language_guard_payload,
                "confidence": confidence_payload,
                "factuality": factuality_payload,
                "self_watcher": self_watcher_payload,
            },
        )
        print("[Generator] Стандартная генерация завершена.")
        return assistant_content

    timestamp_value = getattr(assistant_message_obj, "timestamp", None)
    if hasattr(timestamp_value, "isoformat"):
        timestamp_serialized = to_user_tz_iso(timestamp_value)
    elif timestamp_value is None:
        timestamp_serialized = None
    else:
        timestamp_serialized = str(timestamp_value)

    display_content = assistant_content
    if assistant_reasoning:
        display_content = f"<think>\n{assistant_reasoning}\n</think>\n\n{assistant_content}"
    result_payload = {
        "id": getattr(assistant_message_obj, "id", None),
        "content": display_content,
        "timestamp": timestamp_serialized,
        "raw": assistant_raw,
        "reasoning": assistant_reasoning,
        "provider": generate_result.provider,
        "memory_meta": memory_meta,
        "media": _sanitize_media_items(assistant_media_payload),
        "validator": validator_payload,
        "language_guard": language_guard_payload,
        "confidence": confidence_payload,
        "factuality": factuality_payload,
        "self_watcher": self_watcher_payload,
    }
    log_audit_entry(
        "conversation_standard_complete_full",
        "[Conversation] Полный результат стандартной генерации подготовлен.",
        AuditStatus.INFO,
        details=result_payload,
    )
    print("[Generator] Стандартная генерация завершена (full).")
    return result_payload


# ---------------------------------------------------------------------------
# Streaming generation
# ---------------------------------------------------------------------------
async def generate_stream(
    decision_context: Dict[str, Any],
    history: list,
    *,
    emit_fn: Callable[[dict], Awaitable[bool]],
    last_user_message: Optional[Dict[str, Any]] = None,
    raw_user_media: Optional[Iterable[dict]] = None,
    store: bool = True,
    run_id: Optional[str] = None,
    trace_hook: Optional[Callable[[dict], Awaitable[None]]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    request_options_patch: Optional[Dict[str, Any]] = None,
    skip_thinking_attempted: bool = False,
) -> None:
    if not history:
        return

    def _with_run(payload: Dict[str, Any]) -> Dict[str, Any]:
        if run_id:
            payload["run_id"] = run_id
        return payload

    system_prompt = decision_context.get("system_prompt", "")
    memory_context = decision_context.get("memory_context", {}) or {}

    if raw_user_media:
        user_media_for_storage = _extract_media_payload(raw_user_media)
    elif last_user_message:
        user_media_for_storage = _extract_media_payload(last_user_message)
    else:
        user_media_for_storage = None

    user_media_for_emit: List[dict] = []
    if last_user_message:
        user_media_for_emit = _sanitize_media_items(last_user_message.get("media"))
    append_to_message_id = (
        str(last_user_message.get("append_to_message_id") or "").strip()
        if last_user_message
        else ""
    )
    variant_parent_message_id = (
        str(last_user_message.get("variant_parent_message_id") or "").strip()
        if last_user_message
        else ""
    )
    variant_group_id = (
        str(last_user_message.get("variant_group_id") or "").strip()
        if last_user_message
        else ""
    )
    variant_index = None
    if last_user_message and last_user_message.get("variant_index") is not None:
        try:
            variant_index = int(last_user_message.get("variant_index"))
        except (TypeError, ValueError):
            variant_index = None

    prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()[:12]
    print("[Generator] Подготовлен системный промпт для потока.")
    log_audit_entry(
        "conversation_prompt_ready_stream",
        "[Conversation] Сформирован системный промпт для потоковой генерации.",
        AuditStatus.INFO,
        details={
            "prompt_length": len(system_prompt),
            "prompt_hash": prompt_hash,
            "history_length": len(history),
        },
    )

    assistant_media_payload = await _prepare_main_chat_image_context(
        decision_context=decision_context,
        last_user_message=last_user_message,
        memory_context=memory_context,
        trace_hook=trace_hook,
    )
    system_prompt = decision_context.get("system_prompt", system_prompt)

    chat_history = build_chat_request(history)
    chat_history.insert(0, {"role": "system", "content": system_prompt})
    direct_image_count = 0
    if _should_pass_media_to_main_ollama_model():
        direct_image_count = _attach_images_to_last_user_message(chat_history, user_media_for_storage)
        if direct_image_count:
            log_audit_entry(
                "conversation_stream_direct_ollama_images",
                "[Conversation] Image attachments attached to the main Ollama stream request.",
                AuditStatus.INFO,
                details={"count": direct_image_count},
            )

    request_payload = GenerateRequest(
        messages=chat_history,
        options=_build_generation_options(),
        metadata={"mode": "stream"},
    )
    if request_options_patch:
        request_payload.options.update(dict(request_options_patch))
    request_snapshot = {
        "messages": chat_history,
        "options": request_payload.options,
        "metadata": request_payload.metadata,
    }
    print("[Generator] Собрана заявка на потоковую генерацию.")

    stored_user_entry = None
    suppress_user_echo = bool(last_user_message.get("suppress_user_echo")) if last_user_message else False
    if store and last_user_message and not suppress_user_echo:
        extra_tags = list(memory_context.get("short_term_themes") or [])
        user_display_content = last_user_message.get("display_content", last_user_message.get("content", ""))
        user_tags = _generate_tags_for_text(user_display_content, extra=extra_tags)
        existing_user = None
        message_id = str(last_user_message.get("id") or "").strip()
        if message_id:
            existing_user = database_service.get_message_by_id(message_id)
        if not existing_user:
            stored_user_entry = database_service.add_message_to_history(
                character_name=get_active_character_name(default="default"),
                role="user",
                content=user_display_content,
                timestamp=datetime.now(timezone.utc),
                media=user_media_for_storage,
                tags=user_tags,
            )
    if stored_user_entry and last_user_message:
        stored_media = getattr(stored_user_entry, "media_payload", []) or []
        user_media_for_emit = stored_media
        last_user_message["media"] = stored_media
    elif last_user_message:
        user_media_for_emit = _sanitize_media_items(last_user_message.get("media"))
        last_user_message["media"] = user_media_for_emit
    if last_user_message and emit_fn is not None and not suppress_user_echo:
        await emit_fn(
            _with_run(
                {
                    "type": "message",
                    "role": "user",
                    "content": last_user_message.get("display_content", last_user_message.get("content", "")),
                    "id": last_user_message.get("id"),
                    "timestamp": last_user_message.get("timestamp"),
                    "media": user_media_for_emit,
                }
            )
        )
        await emit_fn(_with_run({"type": "system", "event": "typing_start"}))
        log_audit_entry(
            "conversation_user_message_emitted_stream",
            "[Conversation] Пользовательское сообщение отправлено в поток.",
            AuditStatus.INFO,
            details={
                "message_id": last_user_message.get("id"),
                "has_media": bool(last_user_message.get("media")),
                "media_count": len(last_user_message.get("media") or []),
            },
        )

    voice_enabled = _voice_streaming_available()
    if voice_enabled:
        await _ensure_voice_ready()
        if voice_state.stage() is not VoiceStage.READY:
            voice_enabled = False

    print("[Generator] Потоковая генерация запущена.")
    log_audit_entry(
        "conversation_stream_started",
        "[Conversation] Потоковая генерация начата.",
        AuditStatus.INFO,
        details={
            "request": request_snapshot,
            "voice_enabled": voice_enabled,
        },
    )

    raw_chunks: List[str] = []
    reasoning_chunks: List[str] = []
    speech_started = False
    streaming_in_reasoning = False
    ui_reasoning_open = False
    reasoning_started_at: Optional[float] = None
    reasoning_finished_at: Optional[float] = None
    answer_started_at: Optional[float] = None
    answer_finished_at: Optional[float] = None
    reasoning_trace_open = False
    answer_trace_open = False
    provider_used_stream: Optional[str] = None
    assistant_message_obj = None
    chunk_meta: List[Dict[str, Any]] = []
    final_chunk_raw: Dict[str, Any] = {}
    final_chunk_metadata: Dict[str, Any] = {}
    stopped = False
    output_soft_limit_tokens: Optional[int] = None
    output_soft_used_tokens = 0
    reasoning_budget_exceeded = False
    reasoning_emitted_chars = 0
    reasoning_ui_emitted_chars = 0
    reasoning_ui_truncated = False
    provider_reasoning_seen = ""
    skip_thinking_failed_emitted = False
    stream_output_normalizer = StreamingOutputNormalizer()

    stream_iterator = generation_manager.stream(request_payload).__aiter__()
    pending_stream_chunk: Optional[asyncio.Task] = None

    try:
        while True:
            if pending_stream_chunk is None:
                pending_stream_chunk = asyncio.create_task(stream_iterator.__anext__())
            done, _ = await asyncio.wait(
                {pending_stream_chunk},
                timeout=STREAM_PROVIDER_IDLE_NOTICE_SEC,
            )
            if not done:
                log_audit_entry(
                    "conversation_stream_provider_idle_wait",
                    "[Conversation] Waiting for next provider stream chunk.",
                    AuditStatus.WARNING,
                    details={
                        "provider": provider_used_stream,
                        "idle_notice_sec": STREAM_PROVIDER_IDLE_NOTICE_SEC,
                        "chunks_received": len(chunk_meta),
                        "reasoning_chars": reasoning_emitted_chars,
                        "answer_chars": sum(len(part) for part in raw_chunks),
                    },
                )
                await _emit_runtime_trace(
                    trace_hook,
                    "generation",
                    "start",
                    details={
                        "route": "stream_idle_wait",
                        "description_length": reasoning_emitted_chars,
                    },
                )
                continue

            try:
                chunk = pending_stream_chunk.result()
            except StopAsyncIteration:
                break
            finally:
                pending_stream_chunk = None

            if should_stop and should_stop():
                stopped = True
                break
            if provider_used_stream is None:
                provider_used_stream = chunk.provider

            if output_soft_limit_tokens is None and isinstance(chunk.metadata, dict):
                raw_limit = chunk.metadata.get("output_soft_limit_tokens")
                try:
                    parsed_limit = int(raw_limit) if raw_limit is not None else None
                except (TypeError, ValueError):
                    parsed_limit = None
                if parsed_limit and parsed_limit > 0:
                    output_soft_limit_tokens = parsed_limit

            raw_reasoning_part = chunk.reasoning if isinstance(chunk.reasoning, str) else ""
            reasoning_part, provider_reasoning_seen = _stream_delta(
                provider_reasoning_seen,
                raw_reasoning_part,
            )
            if reasoning_part:
                if skip_thinking_attempted and not skip_thinking_failed_emitted:
                    skip_thinking_failed_emitted = True
                    await emit_fn(
                        _with_run(
                            {
                                "type": "system",
                                "event": "skip_thinking_failed",
                                "message": "Пропуск размышления не удался: модель продолжила отдавать reasoning.",
                            }
                        )
                    )
                if reasoning_started_at is None:
                    reasoning_started_at = time.perf_counter()
                    reasoning_trace_open = True
                    await _emit_runtime_trace(
                        trace_hook,
                        "reasoning",
                        "start",
                        details={"source": "provider_field"},
                    )
                    await emit_fn(_with_run({"type": "system", "event": "thinking_start"}))
                reasoning_chunks.append(reasoning_part)
                reasoning_emitted_chars += len(reasoning_part)
                if (
                    reasoning_emitted_chars > STREAM_REASONING_CHAR_BUDGET
                    and answer_started_at is None
                ):
                    reasoning_budget_exceeded = True
                    log_audit_entry(
                        "conversation_stream_reasoning_budget_exceeded",
                        "[Conversation] Stream reasoning budget exceeded; interrupting runaway thinking.",
                        AuditStatus.WARNING,
                        details={
                            "budget_chars": STREAM_REASONING_CHAR_BUDGET,
                            "reasoning_chars": reasoning_emitted_chars,
                            "provider": provider_used_stream,
                        },
                    )
                    break
                ui_reasoning_part, reasoning_ui_emitted_chars, truncated_now = _take_ui_reasoning_delta(
                    reasoning_part,
                    reasoning_ui_emitted_chars,
                )
                reasoning_ui_truncated = reasoning_ui_truncated or truncated_now
                if ui_reasoning_part:
                    reasoning_prefix = "<think>" if not ui_reasoning_open else ""
                    if not await emit_fn(
                        _with_run(
                                    {
                                        "type": "message_chunk",
                                        "role": "assistant",
                                        "content": f"{reasoning_prefix}{ui_reasoning_part}",
                                        "provider": provider_used_stream,
                                        "id": append_to_message_id or None,
                                    }
                                )
                            ):
                        return
                    ui_reasoning_open = True

            content = chunk.content or ""
            if isinstance(content, str) and content:
                emitted_content = content
                if output_soft_limit_tokens and output_soft_limit_tokens > 0:
                    remaining_tokens = output_soft_limit_tokens - output_soft_used_tokens
                    emitted_content, consumed_tokens = _truncate_by_token_budget(
                        content,
                        remaining_tokens,
                    )
                    output_soft_used_tokens += consumed_tokens
                    if not emitted_content:
                        emitted_content = ""

                previous_in_reasoning = streaming_in_reasoning
                speech_chunk, reasoning_from_content, next_in_reasoning = strip_reasoning_from_chunk(
                    emitted_content,
                    streaming_in_reasoning,
                )
                lower_content = emitted_content.lower()
                content_opens_reasoning = "<think>" in lower_content or "<thinking" in lower_content
                content_closes_reasoning = "</think>" in lower_content or "</thinking>" in lower_content
                if (content_opens_reasoning or previous_in_reasoning or reasoning_from_content) and reasoning_started_at is None:
                    reasoning_started_at = time.perf_counter()
                    reasoning_trace_open = True
                    await _emit_runtime_trace(
                        trace_hook,
                        "reasoning",
                        "start",
                        details={"source": "think_block"},
                    )
                    await emit_fn(_with_run({"type": "system", "event": "thinking_start"}))
                if reasoning_from_content:
                    if skip_thinking_attempted and not skip_thinking_failed_emitted:
                        skip_thinking_failed_emitted = True
                        await emit_fn(
                            _with_run(
                                {
                                    "type": "system",
                                    "event": "skip_thinking_failed",
                                    "message": "Пропуск размышления не удался: модель продолжила отдавать think-блок.",
                                }
                            )
                        )
                    reasoning_chunks.append(reasoning_from_content)
                    reasoning_emitted_chars += len(reasoning_from_content)
                    ui_reasoning_part, reasoning_ui_emitted_chars, truncated_now = _take_ui_reasoning_delta(
                        reasoning_from_content,
                        reasoning_ui_emitted_chars,
                    )
                    reasoning_ui_truncated = reasoning_ui_truncated or truncated_now
                    if ui_reasoning_part:
                        reasoning_prefix = "<think>" if not ui_reasoning_open else ""
                        if not await emit_fn(
                            _with_run(
                                    {
                                        "type": "message_chunk",
                                        "role": "assistant",
                                        "content": f"{reasoning_prefix}{ui_reasoning_part}",
                                        "provider": provider_used_stream,
                                        "id": append_to_message_id or None,
                                    }
                                )
                            ):
                            return
                        ui_reasoning_open = True
                    if (
                        reasoning_emitted_chars > STREAM_REASONING_CHAR_BUDGET
                        and answer_started_at is None
                    ):
                        reasoning_budget_exceeded = True
                        log_audit_entry(
                            "conversation_stream_reasoning_budget_exceeded",
                            "[Conversation] Stream reasoning budget exceeded; interrupting runaway think block.",
                            AuditStatus.WARNING,
                            details={
                                "budget_chars": STREAM_REASONING_CHAR_BUDGET,
                                "reasoning_chars": reasoning_emitted_chars,
                                "provider": provider_used_stream,
                            },
                        )
                        break
                if (
                    reasoning_started_at is not None
                    and reasoning_finished_at is None
                    and (content_closes_reasoning or (previous_in_reasoning and not next_in_reasoning))
                ):
                    reasoning_finished_at = time.perf_counter()
                    if reasoning_trace_open:
                        await _emit_runtime_trace(
                            trace_hook,
                            "reasoning",
                            "end",
                            started_at=reasoning_started_at,
                            details={"source": "think_block"},
                        )
                        reasoning_trace_open = False
                    await emit_fn(_with_run({"type": "system", "event": "thinking_end"}))

                if _has_answer_signal(speech_chunk) and answer_started_at is None:
                    answer_started_at = time.perf_counter()
                    answer_trace_open = True
                    if reasoning_started_at is not None and reasoning_finished_at is None:
                        reasoning_finished_at = answer_started_at
                        if reasoning_trace_open:
                            await _emit_runtime_trace(
                                trace_hook,
                                "reasoning",
                                "end",
                                started_at=reasoning_started_at,
                                details={"source": "answer_started"},
                            )
                            reasoning_trace_open = False
                        await emit_fn(_with_run({"type": "system", "event": "thinking_end"}))
                    await _emit_runtime_trace(
                        trace_hook,
                        "answer",
                        "start",
                        details={"source": "visible_text"},
                    )
                    await emit_fn(_with_run({"type": "system", "event": "answer_start"}))

                if ui_reasoning_open and _has_answer_signal(speech_chunk):
                    if not await emit_fn(
                        _with_run(
                            {
                                "type": "message_chunk",
                                "role": "assistant",
                                "content": "</think>\n\n",
                                "provider": provider_used_stream,
                                "id": append_to_message_id or None,
                            }
                        )
                    ):
                        return
                    ui_reasoning_open = False
                chunk_meta.append(
                    {
                        "provider": chunk.provider,
                        "length": len(speech_chunk),
                        "done": chunk.done,
                        "has_reasoning": bool(chunk.reasoning),
                    }
                )
                streaming_in_reasoning = next_in_reasoning
                if speech_chunk:
                    speech_chunk = stream_output_normalizer.feed(speech_chunk)
                if speech_chunk:
                    if not await emit_fn(
                        _with_run(
                            {
                                "type": "message_chunk",
                                "role": "assistant",
                                "content": speech_chunk,
                                "provider": provider_used_stream,
                                "id": append_to_message_id or None,
                            }
                        )
                    ):
                        return

                    raw_chunks.append(speech_chunk)
                    if voice_enabled and speech_chunk.strip():
                        voice_state.on_stream_chunk(speech_chunk)
                        if not speech_started:
                            voice_state.on_stream_start()
                            speech_started = True
            if chunk.done:
                final_chunk_raw = chunk.raw if isinstance(chunk.raw, dict) else {}
                final_chunk_metadata = chunk.metadata or {}

        if ui_reasoning_open:
            if not await emit_fn(
                _with_run(
                    {
                    "type": "message_chunk",
                    "role": "assistant",
                    "content": "</think>\n\n",
                    "provider": provider_used_stream,
                    "id": append_to_message_id or None,
                }
            )
        ):
                return
            ui_reasoning_open = False
        if reasoning_started_at is not None and reasoning_finished_at is None:
            reasoning_finished_at = time.perf_counter()
            if reasoning_trace_open:
                await _emit_runtime_trace(
                    trace_hook,
                    "reasoning",
                    "end",
                    started_at=reasoning_started_at,
                    details={"source": "stream_finished"},
                )
                reasoning_trace_open = False
            await emit_fn(_with_run({"type": "system", "event": "thinking_end"}))
        if answer_started_at is not None and answer_finished_at is None:
            answer_finished_at = time.perf_counter()
            if answer_trace_open:
                await _emit_runtime_trace(
                    trace_hook,
                    "answer",
                    "end",
                    started_at=answer_started_at,
                    details={"source": "stream_finished"},
                )
                answer_trace_open = False

        if voice_enabled and speech_started:
            voice_state.on_stream_end()
        if should_stop and should_stop():
            stopped = True
    except NoProviderResolved as exc:
        print("[Generator] Провайдеры недоступны для потока.")
        provider_errors = _extract_provider_errors(exc)
        _emit_generation_tool_event(
            tool_name="generation.provider",
            status="error",
            content=(
                "[ERROR]: generation provider not available. "
                + (
                    "; ".join(
                        f"{item.get('provider')}: {item.get('reason')}"
                        for item in provider_errors
                    )
                    if provider_errors
                    else str(exc)
                )
            ),
            runtime_meta={
                "mode": "stream",
                "providers": provider_errors,
                "run_id": run_id,
            },
        )
        payload: Dict[str, Any] = {
            "type": "error",
            "message": "Generation provider not available",
        }
        if provider_errors:
            payload["details"] = provider_errors
        await emit_fn(_with_run(payload))
        await emit_fn(_with_run({"type": "system", "event": "typing_end"}))
        log_audit_entry(
            event_type="generation_provider_stream_failure",
            msg="[Generator] Потоковый провайдер недоступен",
            status=AuditStatus.ERROR,
            details={
                "errors": provider_errors
                if provider_errors
                else [{"provider": "unknown", "reason": str(exc)}],
                "request": request_snapshot,
            },
        )
        return
    finally:
        if pending_stream_chunk is not None and not pending_stream_chunk.done():
            pending_stream_chunk.cancel()

    assistant_raw = "".join(raw_chunks).strip()
    assistant_reasoning = _trim_reasoning_for_storage("".join(reasoning_chunks).strip())
    assistant_content, tagged_reasoning = split_reasoning(assistant_raw)
    assistant_content = stream_output_normalizer.normalize_final(assistant_content)
    if tagged_reasoning and tagged_reasoning not in assistant_reasoning:
        assistant_reasoning = _trim_reasoning_for_storage("\n".join(
            part for part in [assistant_reasoning, tagged_reasoning] if part
        ).strip())
    if not assistant_content:
        try:
            recovered_content, recovered_reasoning, recovered_provider = _recover_empty_content_with_retries(
                chat_history=chat_history,
                options=request_payload.options,
                assistant_reasoning=assistant_reasoning,
                mode="stream_response",
            )
            if recovered_content:
                assistant_content = stream_output_normalizer.normalize_final(recovered_content)
                assistant_reasoning = _trim_reasoning_for_storage(recovered_reasoning or assistant_reasoning)
                if recovered_provider:
                    provider_used_stream = recovered_provider
                log_audit_entry(
                    "conversation_stream_response_empty_content_recovered",
                    "[Conversation] Empty content recovered by retry regeneration.",
                    AuditStatus.WARNING,
                    details={
                        "provider": provider_used_stream,
                        "reasoning_budget_exceeded": reasoning_budget_exceeded,
                    },
                )
        except Exception as exc:
            log_audit_entry(
                "conversation_stream_response_empty_content_recovery_failed",
                "[Conversation] Empty content recovery failed.",
                AuditStatus.WARNING,
                details={"error": str(exc)},
            )
    reasoning_elapsed_ms = (
        round((reasoning_finished_at - reasoning_started_at) * 1000, 2)
        if reasoning_started_at is not None and reasoning_finished_at is not None
        else None
    )
    answer_elapsed_ms = (
        round((answer_finished_at - answer_started_at) * 1000, 2)
        if answer_started_at is not None and answer_finished_at is not None
        else None
    )
    print("[Generator] Потоковая генерация завершена.")
    log_audit_entry(
        "conversation_stream_completed",
        "[Conversation] Потоковая генерация завершена.",
        AuditStatus.SUCCESS,
        details={
            "provider": provider_used_stream,
            "chunks_received": len(chunk_meta),
            "chunk_details": chunk_meta,
            "assistant_response_length": len(assistant_content or ""),
            "assistant_reasoning_length": len(assistant_reasoning or ""),
            "reasoning_elapsed_ms": reasoning_elapsed_ms,
            "answer_elapsed_ms": answer_elapsed_ms,
        },
    )

    if assistant_content and not stopped:
        extra_tags = list(memory_context.get("short_term_themes") or [])
        assistant_tags = _generate_tags_for_text(
            assistant_content, extra=extra_tags + ["assistant"]
        )
        if append_to_message_id:
            assistant_message_obj = database_service.append_to_history_message(
                append_to_message_id,
                assistant_content,
                reasoning_delta=assistant_reasoning or None,
                media=assistant_media_payload or None,
            )
        else:
            assistant_message_obj = database_service.add_message_to_history(
                character_name=get_active_character_name(default="default"),
                role="assistant",
                content=assistant_content,
                timestamp=datetime.now(timezone.utc),
                media=assistant_media_payload or None,
                tags=assistant_tags,
                parent_message_id=variant_parent_message_id or None,
                variant_group_id=variant_group_id or None,
                variant_index=variant_index,
                active_variant=True,
            )
        stored_media = getattr(assistant_message_obj, "media_payload", None)
        if stored_media:
            assistant_media_payload = stored_media
        if assistant_reasoning and not append_to_message_id:
            database_service.add_reasoning_entry(
                assistant_message_obj.id,
                assistant_reasoning,
            )

    if not stopped:
        decision_layer.handle_response(assistant_content)
    assistant_timestamp = getattr(
        assistant_message_obj, "timestamp", datetime.now(timezone.utc)
    )
    assistant_message_id = getattr(assistant_message_obj, "id", str(uuid.uuid4()))
    stored_plain_content = getattr(assistant_message_obj, "content", None)
    if append_to_message_id and isinstance(stored_plain_content, str):
        display_plain_content = stored_plain_content
    else:
        display_plain_content = assistant_content
    stored_reasoning = (
        database_service.get_reasoning_by_message_id(assistant_message_id)
        if append_to_message_id and assistant_message_id
        else assistant_reasoning
    )
    display_content = display_plain_content
    display_reasoning = _trim_reasoning_for_storage(stored_reasoning or "")
    if display_reasoning:
        display_content = f"<think>\n{display_reasoning}\n</think>\n\n{display_plain_content}"

    final_message_payload = _with_run({
        "type": "message",
        "role": "assistant",
        "content": display_content,
        "provider": provider_used_stream,
        "id": assistant_message_id,
        "timestamp": to_user_tz_iso(assistant_timestamp),
        "media": _sanitize_media_items(assistant_media_payload),
        "parent_message_id": variant_parent_message_id or None,
        "variant_group_id": variant_group_id or None,
        "variant_index": variant_index,
        "active_variant": True,
    })
    await emit_fn(final_message_payload)
    log_audit_entry(
        "conversation_stream_emit_end",
        "[Conversation] Финальный ответ отправлен клиенту.",
        AuditStatus.INFO,
        details={
            "provider": provider_used_stream,
            "assistant_content": assistant_content,
            "assistant_reasoning_length": len(assistant_reasoning or ""),
            "assistant_reasoning_preview": (assistant_reasoning or "")[:1200],
            "message_id": assistant_message_id,
            "reasoning_ui_truncated": reasoning_ui_truncated,
        },
    )
    usage = _extract_usage_metadata(final_chunk_raw)
    model = final_chunk_metadata.get("model") if isinstance(final_chunk_metadata, dict) else None
    meta = final_chunk_metadata if isinstance(final_chunk_metadata, dict) else {}
    log_audit_entry(
        "conversation_stream_payload_debug",
        "[Conversation] Финальный payload потоковой генерации.",
        AuditStatus.INFO,
        details={
            "provider": provider_used_stream,
            "assistant_content": assistant_content,
            "assistant_reasoning_length": len(assistant_reasoning or ""),
            "assistant_reasoning_preview": (assistant_reasoning or "")[:1200],
            "usage": usage,
            "meta": meta,
            "final_chunk_raw": final_chunk_raw,
            "reasoning_elapsed_ms": reasoning_elapsed_ms,
            "answer_elapsed_ms": answer_elapsed_ms,
            "chunks_received": len(chunk_meta),
            "chunk_details": chunk_meta,
        },
    )
    await emit_fn(
        _with_run(
            {
                "type": "message_end",
                "provider": provider_used_stream,
                "content": display_content,
                "reasoning": display_reasoning,
                "id": assistant_message_id,
                "timestamp": to_user_tz_iso(assistant_timestamp),
                "usage": usage,
                "model": model,
                "stopped": stopped,
                "voice_playback_started": bool(voice_enabled and speech_started),
                "reasoning_elapsed_ms": reasoning_elapsed_ms,
                "answer_elapsed_ms": answer_elapsed_ms,
                "meta": meta,
            }
        )
    )
    await emit_fn(_with_run({"type": "system", "event": "typing_end"}))


def play_message(msg_id: str):
    print("[Generator] Воспроизведение сохранённого сообщения.")
    message = database_service.get_message_by_id(msg_id)
    if config_service.get_config_value("voice.enabled", False):
        decision_layer.handle_response(message.get("content", ""))
    return message
