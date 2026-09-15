"""New human messages on their way to the history: data that travels, not history.

A new message of the main chat is written here the moment it arrives, before it
waits for the model, together with the id its history row will get. The turn
stores the message in the history as before, with the tags and image
descriptions the pipeline adds on the way. When the turn ends, however it ends,
a message the turn did not get to store is stored from here; then the row is
removed and the outcome is logged. Rows a restart left behind are handled the
same way at the next start, and nothing answers them automatically.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from models.models import QueuedTurn
from modules.database import service as database_service
from modules.database.core import SessionLocal
from modules.debug_vault.service import write_vault_entry
from modules.generative.conversation import _extract_media_payload, _generate_tags_for_text
from modules.system.logger import AuditStatus, log_audit_entry
from modules.system.service import get_active_character_name

COMPLETED = "completed"
STOPPED = "stopped"
FAILED = "failed"
INTERRUPTED = "interrupted"

_AUDIT_LEVELS = {
    COMPLETED: AuditStatus.SUCCESS,
    STOPPED: AuditStatus.INFO,
    FAILED: AuditStatus.ERROR,
    INTERRUPTED: AuditStatus.WARNING,
}
# Outcomes worth a look in the debug vault; a finished or stopped turn is no anomaly.
_VAULT_ENTRIES = {
    FAILED: ("error", "A chat turn failed; the message was kept."),
    INTERRUPTED: ("warning", "A chat turn was cut off by a restart; the message was kept."),
}


def accept(payload: dict, *, run_id: str, channel: str = "main_chat") -> tuple[str, str]:
    """Keep a new message; returns the row id and the id its history row will get."""
    turn_id = str(uuid.uuid4())
    history_message_id = str(uuid.uuid4())
    session = SessionLocal()
    try:
        session.add(
            QueuedTurn(
                id=turn_id,
                run_id=run_id,
                channel=channel,
                history_message_id=history_message_id,
                character_name=get_active_character_name(default="default"),
                actor_user_uuid=payload.get("actor_user_uuid"),
                content=str(payload.get("display_content", payload.get("content", "")) or ""),
                media=json.dumps(_extract_media_payload(payload), ensure_ascii=False),
                received_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
    finally:
        session.close()
    return turn_id, history_message_id


def finish(turn_id: str, status: str, *, error: Optional[str] = None) -> None:
    """End a turn: make sure its message is in the history, remove the row, log the outcome.

    Never raises: recording a turn must not break the chat. A message that could
    not be stored keeps its row, and the next start tries again.
    """
    session = SessionLocal()
    try:
        row = session.query(QueuedTurn).filter(QueuedTurn.id == turn_id).first()
        if row is None:
            return
        details = {
            "turn_id": turn_id,
            "run_id": row.run_id,
            "channel": row.channel,
            "history_message_id": row.history_message_id,
            "status": status,
            "error": error,
        }
        try:
            details["message_stored_from_queue"] = _store_if_missing(row)
        except Exception as exc:
            log_audit_entry(
                "turn_queue_store_failed",
                "[TurnQueue] The message could not be stored; its row stays for the next start.",
                AuditStatus.ERROR,
                details={**details, "store_error": str(exc)},
            )
            return
        session.delete(row)
        session.commit()
    except Exception as exc:
        session.rollback()
        log_audit_entry(
            "turn_queue_finish_failed",
            "[TurnQueue] The turn could not be finished.",
            AuditStatus.ERROR,
            details={"turn_id": turn_id, "status": status, "error": str(exc)},
        )
        return
    finally:
        session.close()

    log_audit_entry(
        "turn_queue_finished",
        f"[TurnQueue] Turn {status}.",
        _AUDIT_LEVELS.get(status, AuditStatus.INFO),
        details=details,
    )
    vault_entry = _VAULT_ENTRIES.get(status)
    if vault_entry:
        severity, summary = vault_entry
        write_vault_entry(
            kind=f"turn_{status}",
            summary=summary,
            severity=severity,
            context=details,
            output=error or "",
        )


def recover_interrupted() -> int:
    """At start: the turns a restart cut off. Their messages are kept; nothing answers them."""
    session = SessionLocal()
    try:
        turn_ids = [row_id for (row_id,) in session.query(QueuedTurn.id).order_by(QueuedTurn.received_at).all()]
    except Exception as exc:
        log_audit_entry(
            "turn_queue_recovery_failed",
            "[TurnQueue] The turns left by a restart could not be read.",
            AuditStatus.ERROR,
            details={"error": str(exc)},
        )
        return 0
    finally:
        session.close()
    for turn_id in turn_ids:
        finish(turn_id, INTERRUPTED)
    return len(turn_ids)


def _store_if_missing(row: QueuedTurn) -> bool:
    """Store the message unless its turn already did; True when stored here."""
    if database_service.get_message_by_id(row.history_message_id):
        return False
    received_at = row.received_at
    if received_at is not None and received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)
    database_service.add_message_to_history(
        character_name=row.character_name,
        role="user",
        content=row.content,
        timestamp=received_at,
        media=json.loads(row.media or "[]") or None,
        tags=_generate_tags_for_text(row.content),
        message_id=row.history_message_id,
    )
    return True
