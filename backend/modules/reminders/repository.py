"""§3.9-quinquies — storage layer for user reminders.

All datetimes are stored naive UTC (matching the rest of the schema).
Never raises out of public methods used by the loop: callers in the
initiative loop wrap calls themselves, but list/mark helpers also degrade
gracefully so a storage hiccup cannot kill the loop thread.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from models.models import UserReminder
from modules.database.core import SessionLocal

VALID_STATUSES = ("pending", "fired", "cancelled", "failed")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _row_to_dict(row: UserReminder) -> Dict[str, Any]:
    try:
        meta = json.loads(row.meta or "{}")
    except Exception:
        meta = {}
    return {
        "id": row.id,
        "character_id": row.character_id,
        "user_uuid": row.user_uuid,
        "text": row.text,
        "due_at": row.due_at.isoformat() + "Z" if row.due_at else None,
        "recurrence": row.recurrence,
        "channel": row.channel,
        "status": row.status,
        "source": row.source,
        "source_message_id": row.source_message_id,
        "fired_at": row.fired_at.isoformat() + "Z" if row.fired_at else None,
        "meta": meta,
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
    }


class RemindersRepository:
    def create(
        self,
        *,
        character_id: str,
        text: str,
        due_at: datetime,
        user_uuid: Optional[str] = None,
        recurrence: str = "none",
        channel: str = "main_chat",
        source: str = "chat",
        source_message_id: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        row = UserReminder(
            id=str(uuid.uuid4()),
            character_id=character_id,
            user_uuid=user_uuid,
            text=str(text or "").strip(),
            due_at=_to_naive_utc(due_at),
            recurrence=recurrence or "none",
            channel=channel or "main_chat",
            status="pending",
            source=source or "chat",
            source_message_id=source_message_id,
            meta=json.dumps(meta or {}, ensure_ascii=False),
            created_at=_utc_now(),
        )
        with SessionLocal() as session:
            session.add(row)
            session.commit()
            session.refresh(row)
            return _row_to_dict(row)

    def get(self, reminder_id: str) -> Optional[Dict[str, Any]]:
        with SessionLocal() as session:
            row = session.get(UserReminder, reminder_id)
            return _row_to_dict(row) if row else None

    def list(
        self,
        *,
        character_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        with SessionLocal() as session:
            query = session.query(UserReminder)
            if character_id:
                query = query.filter(UserReminder.character_id == character_id)
            if status:
                query = query.filter(UserReminder.status == status)
            total = query.count()
            rows = (
                query.order_by(UserReminder.due_at.asc())
                .offset(max(0, int(offset or 0)))
                .limit(max(1, min(int(limit or 100), 500)))
                .all()
            )
            return {"items": [_row_to_dict(r) for r in rows], "total": total}

    def list_due(self, *, now: Optional[datetime] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """Pending rows whose due_at has passed, oldest first."""
        moment = _to_naive_utc(now) if now else _utc_now()
        try:
            with SessionLocal() as session:
                rows = (
                    session.query(UserReminder)
                    .filter(
                        UserReminder.status == "pending",
                        UserReminder.due_at <= moment,
                    )
                    .order_by(UserReminder.due_at.asc())
                    .limit(max(1, int(limit or 20)))
                    .all()
                )
                return [_row_to_dict(r) for r in rows]
        except Exception:
            return []

    def mark(
        self,
        reminder_id: str,
        *,
        status: str,
        meta_update: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if status not in VALID_STATUSES:
            return None
        try:
            with SessionLocal() as session:
                row = session.get(UserReminder, reminder_id)
                if row is None:
                    return None
                row.status = status
                if status == "fired":
                    row.fired_at = _utc_now()
                if meta_update:
                    try:
                        meta = json.loads(row.meta or "{}")
                    except Exception:
                        meta = {}
                    meta.update(meta_update)
                    row.meta = json.dumps(meta, ensure_ascii=False)
                session.commit()
                session.refresh(row)
                return _row_to_dict(row)
        except Exception:
            return None

    def update(
        self,
        reminder_id: str,
        *,
        text: Optional[str] = None,
        due_at: Optional[datetime] = None,
    ) -> Optional[Dict[str, Any]]:
        with SessionLocal() as session:
            row = session.get(UserReminder, reminder_id)
            if row is None:
                return None
            if text is not None and str(text).strip():
                row.text = str(text).strip()
            if due_at is not None:
                row.due_at = _to_naive_utc(due_at)
                # Editing the schedule revives cancelled/failed rows.
                if row.status in ("cancelled", "failed"):
                    row.status = "pending"
            session.commit()
            session.refresh(row)
            return _row_to_dict(row)

    def count_active(self, *, character_id: str) -> int:
        try:
            with SessionLocal() as session:
                return (
                    session.query(UserReminder)
                    .filter(
                        UserReminder.character_id == character_id,
                        UserReminder.status == "pending",
                    )
                    .count()
                )
        except Exception:
            return 0


reminders_repository = RemindersRepository()
