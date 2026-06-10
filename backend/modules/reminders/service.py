"""§3.9-quinquies Tasks/Reminders — capture and delivery.

Two public entry points:

  * ``maybe_capture_reminder(user_message)`` — called by the decision layer
    after the analyzer. Cheap keyword gate first; only when the message looks
    like a reminder request does it spend a service-LLM call on structured
    extraction. Never raises; returns a small ack dict (or None) that the
    decision layer folds into generation context so the companion can
    acknowledge the reminder naturally.

  * ``fire_due_reminders()`` — called from the initiative loop once a minute.
    Marks each due row fired BEFORE delivery (no double-fire on crash), asks
    the generation LLM for one short in-character line (canned «⏰ …» text on
    any failure), persists it to history as an assistant message and
    broadcasts it to main_chat over the websocket manager.

Quiet hours are intentionally ignored: «разбуди в 7» means wake me at 7.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry

from .repository import reminders_repository

# --------------------------------------------------------------------------
# Capture
# --------------------------------------------------------------------------

# Cheap gate: only these patterns warrant an LLM extraction call.
_REMINDER_GATE = re.compile(
    r"(напомн|разбуди|разбудишь|не\s+забудь\s+напомнить|поставь\s+(напоминание|будильник)|"
    r"remind\s+me|wake\s+me|set\s+(a\s+)?(reminder|alarm))",
    re.IGNORECASE,
)

_MAX_ACTIVE_DEFAULT = 50


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_user_timezone(user_uuid: Optional[str]) -> str:
    if not user_uuid:
        return "UTC"
    try:
        from models.models import User
        from modules.database.core import SessionLocal

        with SessionLocal() as session:
            user = session.query(User).filter(User.uuid == user_uuid).first()
            tz = getattr(getattr(user, "settings", None), "timezone_name", None)
            if isinstance(tz, str) and tz.strip():
                return tz.strip()
    except Exception:
        pass
    return "UTC"


def _parse_llm_json(raw: str) -> Optional[Dict[str, Any]]:
    text = str(raw or "").strip()
    if not text:
        return None
    # Models sometimes wrap JSON in code fences or prepend prose.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _local_to_utc(due_local_str: str, tz_name: str) -> Optional[datetime]:
    raw = str(due_local_str or "").strip()
    if not raw:
        return None
    try:
        naive_local = datetime.fromisoformat(raw)
    except ValueError:
        return None
    try:
        tz = ZoneInfo(tz_name or "UTC")
    except Exception:
        tz = timezone.utc
    if naive_local.tzinfo is None:
        localized = naive_local.replace(tzinfo=tz)
    else:
        localized = naive_local
    return localized.astimezone(timezone.utc)


def maybe_capture_reminder(
    user_message: Dict[str, Any],
    *,
    character_id: str,
    character_name: str,
) -> Optional[Dict[str, Any]]:
    """Detect and persist a reminder request from a chat message.

    Returns an ack dict {text, due_at_local, reminder_id} for generation
    context, or None when the message is not a reminder request (or the
    feature is disabled / anything failed).
    """
    try:
        if not bool(config_service.get_config_value("reminders.enabled", True)):
            return None

        content = str(user_message.get("content") or "").strip()
        if not content or not _REMINDER_GATE.search(content):
            return None

        user_uuid = user_message.get("actor_user_uuid") or None
        max_active = int(
            config_service.get_config_value("reminders.max_active", _MAX_ACTIVE_DEFAULT)
            or _MAX_ACTIVE_DEFAULT
        )
        if reminders_repository.count_active(character_id=character_id) >= max_active:
            log_audit_entry(
                "reminder_capture_limit_reached",
                "[Reminders] Active reminders limit reached, capture skipped.",
                AuditStatus.WARNING,
                details={"character_id": character_id, "max_active": max_active},
            )
            return None

        from constants.prompts import REMINDER_EXTRACTION_PROMPT
        from modules.generative.manager import generation_manager
        from modules.generative.types import GenerateRequest
        from modules.system.user import resolve_user_language

        tz_name = _resolve_user_timezone(user_uuid)
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz, tz_name = timezone.utc, "UTC"
        now_local = datetime.now(tz)
        language = resolve_user_language(
            user_uuid=user_uuid, character_id=character_id, fallback="en-US"
        )

        system_prompt = REMINDER_EXTRACTION_PROMPT.format(
            now_local=now_local.strftime("%Y-%m-%dT%H:%M (%A)"),
            timezone_name=tz_name,
            language=language,
        )
        result = generation_manager.generate(
            GenerateRequest(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content},
                ],
                # __think=False: reasoning models must not burn the token
                # budget on <think> — we need the strict JSON itself.
                options={"temperature": 0.0, "num_predict": 400, "__think": False},
                metadata={"mode": "reminder_extraction"},
            )
        )
        raw_content = str(getattr(result, "content", "") or "")
        payload = _parse_llm_json(raw_content)
        if payload is None:
            # Some providers still route everything into reasoning — try it
            # before giving up.
            payload = _parse_llm_json(str(getattr(result, "reasoning", "") or ""))
        if not payload or not bool(payload.get("is_reminder")):
            log_audit_entry(
                "reminder_capture_not_a_reminder",
                "[Reminders] Gate matched but extractor said no.",
                AuditStatus.INFO,
                details={
                    "message_id": user_message.get("id"),
                    "raw_content": raw_content[:500],
                    "raw_reasoning": str(getattr(result, "reasoning", "") or "")[:300],
                    "parsed": payload,
                },
            )
            return None

        due_utc = _local_to_utc(str(payload.get("due_at_local") or ""), tz_name)
        if due_utc is None:
            log_audit_entry(
                "reminder_capture_bad_due",
                "[Reminders] Extractor returned unparseable due_at_local.",
                AuditStatus.WARNING,
                details={
                    "message_id": user_message.get("id"),
                    "due_at_local": payload.get("due_at_local"),
                },
            )
            return None
        # Clock-skew tolerance: anything more than a minute in the past is a
        # bad extraction, not a "fire immediately" request.
        if due_utc < _utc_now() - timedelta(minutes=1):
            log_audit_entry(
                "reminder_capture_due_in_past",
                "[Reminders] Extracted due moment is in the past, skipped.",
                AuditStatus.WARNING,
                details={
                    "message_id": user_message.get("id"),
                    "due_at_utc": due_utc.isoformat(),
                },
            )
            return None

        reminder_text = str(payload.get("text") or "").strip() or content[:200]
        row = reminders_repository.create(
            character_id=character_id,
            user_uuid=user_uuid,
            text=reminder_text,
            due_at=due_utc,
            source="chat",
            source_message_id=user_message.get("id"),
            meta={
                "timezone": tz_name,
                "language": language,
                "due_at_local": payload.get("due_at_local"),
                "character_name": character_name,
            },
        )
        log_audit_entry(
            "reminder_captured",
            "[Reminders] Reminder captured from chat.",
            AuditStatus.SUCCESS,
            details={
                "reminder_id": row.get("id"),
                "due_at": row.get("due_at"),
                "text": reminder_text,
                "message_id": user_message.get("id"),
            },
        )
        return {
            "reminder_id": row.get("id"),
            "text": reminder_text,
            "due_at_local": str(payload.get("due_at_local") or ""),
            "timezone": tz_name,
        }
    except Exception as exc:
        log_audit_entry(
            "reminder_capture_failed",
            "[Reminders] Capture failed (non-fatal).",
            AuditStatus.WARNING,
            details={"error": str(exc), "message_id": user_message.get("id")},
        )
        return None


# --------------------------------------------------------------------------
# Delivery
# --------------------------------------------------------------------------


def _compose_delivery_text(reminder: Dict[str, Any]) -> str:
    """One short in-character line via the generation LLM; canned fallback."""
    meta = reminder.get("meta") or {}
    fallback = f"⏰ Напоминание: {reminder.get('text')}"
    try:
        from constants.prompts import REMINDER_DELIVERY_PROMPT
        from modules.generative.manager import generation_manager
        from modules.generative.types import GenerateRequest

        tz_name = str(meta.get("timezone") or "UTC")
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc
        prompt = REMINDER_DELIVERY_PROMPT.format(
            character_name=str(meta.get("character_name") or "Assistant"),
            reminder_text=str(reminder.get("text") or ""),
            requested_at=str(reminder.get("created_at") or ""),
            now_local=datetime.now(tz).strftime("%Y-%m-%d %H:%M"),
            language=str(meta.get("language") or "en-US"),
        )
        result = generation_manager.generate(
            GenerateRequest(
                messages=[{"role": "system", "content": prompt}],
                options={"temperature": 0.6, "num_predict": 220, "__think": False},
                metadata={"mode": "reminder_delivery"},
            )
        )
        text = str(getattr(result, "content", "") or "").strip()
        return text if text else fallback
    except Exception:
        return fallback


def _broadcast_assistant_message(payload: Dict[str, Any]) -> bool:
    """Schedule a WS broadcast onto the uvicorn loop from this worker thread."""
    try:
        import asyncio

        from core.event_loop_registry import get_main_loop
        from core.websocket_manager import manager

        loop = get_main_loop()
        if loop is None:
            return False
        future = asyncio.run_coroutine_threadsafe(
            manager.send_message(json.dumps(payload, ensure_ascii=False)), loop
        )
        future.result(timeout=5)
        return True
    except Exception:
        return False


def _deliver_main_chat(reminder: Dict[str, Any]) -> bool:
    from modules.database import service as database_service

    meta = reminder.get("meta") or {}
    character_name = str(meta.get("character_name") or "").strip()
    if not character_name:
        from modules.system.service import get_active_character_name

        character_name = get_active_character_name(default="default_waifu")

    content = _compose_delivery_text(reminder)
    now = datetime.now(timezone.utc)
    runtime_meta = {
        "source": "reminders",
        "event": "reminder_fired",
        "reminder": {
            "id": reminder.get("id"),
            "text": reminder.get("text"),
            "due_at": reminder.get("due_at"),
        },
    }
    row = database_service.add_message_to_history(
        character_name=character_name,
        role="assistant",
        content=content,
        timestamp=now,
        tags=["reminder"],
        runtime_meta=runtime_meta,
    )
    message_id = getattr(row, "id", None)
    delivered_ws = _broadcast_assistant_message(
        {
            "type": "message",
            "id": message_id,
            "role": "assistant",
            "content": content,
            "timestamp": now.isoformat(),
            "source": "reminders",
        }
    )
    log_audit_entry(
        "reminder_delivered",
        "[Reminders] Reminder delivered to main_chat.",
        AuditStatus.SUCCESS,
        details={
            "reminder_id": reminder.get("id"),
            "message_id": message_id,
            "ws_broadcast": delivered_ws,
        },
    )
    return True


def fire_due_reminders(*, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Poll due reminders and deliver them. Called from the initiative loop.

    Never raises. Returns {"fired": n, "failed": n} for the loop's audit
    entry. Rows are marked fired BEFORE delivery so a crash cannot cause a
    notification storm on restart; a delivery error flips the row to failed.
    """
    summary = {"fired": 0, "failed": 0}
    try:
        if not bool(config_service.get_config_value("reminders.enabled", True)):
            return summary
        due: List[Dict[str, Any]] = reminders_repository.list_due(now=now)
        for reminder in due:
            marked = reminders_repository.mark(str(reminder.get("id")), status="fired")
            if marked is None:
                continue  # raced with cancel/edit — skip
            try:
                _deliver_main_chat(reminder)
                summary["fired"] += 1
            except Exception as exc:
                summary["failed"] += 1
                reminders_repository.mark(
                    str(reminder.get("id")),
                    status="failed",
                    meta_update={"delivery_error": str(exc)},
                )
                log_audit_entry(
                    "reminder_delivery_failed",
                    "[Reminders] Delivery failed.",
                    AuditStatus.WARNING,
                    details={"reminder_id": reminder.get("id"), "error": str(exc)},
                )
    except Exception as exc:
        log_audit_entry(
            "reminder_fire_pass_failed",
            "[Reminders] Fire pass failed (non-fatal).",
            AuditStatus.WARNING,
            details={"error": str(exc)},
        )
    return summary
