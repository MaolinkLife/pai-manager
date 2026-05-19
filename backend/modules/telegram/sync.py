from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from models.models import (
    Character,
    History,
    TelegramChat,
    TelegramMessage,
    TelegramSyncJob,
    TelegramUser,
)
from modules.database.core import SessionLocal


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dump_json(payload: dict[str, Any] | None) -> str:
    return json.dumps(payload or {}, ensure_ascii=False, default=str)


def _telegram_user_uuid(telegram_user_id: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"telegram:user:{int(telegram_user_id)}"))


@dataclass(slots=True)
class TelegramSyncMessage:
    character_name: str
    telegram_chat_id: int
    telegram_message_id: int
    chat_kind: str = "unknown"
    chat_title: str = ""
    chat_username: str = ""
    sender_telegram_user_id: Optional[int] = None
    sender_name: str = ""
    sender_username: str = ""
    is_owner_chat: bool = False
    is_owner_sender: bool = False
    role: str = "user"
    event: str = "incoming_message"
    text: str = ""
    message_date: Optional[datetime] = None
    edit_date: Optional[datetime] = None
    history_id: Optional[str] = None
    sync_state: str = "active"
    meta: dict[str, Any] | None = None


class TelegramSyncService:
    def upsert_message(self, message: TelegramSyncMessage) -> Optional[TelegramMessage]:
        if not message.character_name or int(message.telegram_chat_id or 0) == 0:
            return None
        if int(message.telegram_message_id or 0) <= 0:
            return None

        session: Session = SessionLocal()
        try:
            character = session.query(Character).filter_by(name=message.character_name).first()
            if not character:
                return None

            chat = self._upsert_chat(session, message)
            sender = self._upsert_user(session, message)
            role = str(message.role or "user").strip().lower()
            if role not in {"user", "assistant"}:
                role = "user"
            event = str(message.event or "incoming_message").strip().lower() or "incoming_message"

            row = (
                session.query(TelegramMessage)
                .filter(
                    TelegramMessage.character_id == character.id,
                    TelegramMessage.telegram_chat_id == int(message.telegram_chat_id),
                    TelegramMessage.telegram_message_id == int(message.telegram_message_id),
                    TelegramMessage.role == role,
                    TelegramMessage.event == event,
                )
                .first()
            )
            if row is None:
                row = TelegramMessage(
                    id=str(uuid.uuid4()),
                    character_id=character.id,
                    telegram_chat_id=int(message.telegram_chat_id),
                    telegram_message_id=int(message.telegram_message_id),
                    role=role,
                    event=event,
                    created_at=_now(),
                )
                session.add(row)

            row.history_id = message.history_id or row.history_id
            row.chat_id = chat.id
            row.sender_user_id = sender.id if sender else None
            row.text = str(message.text or "")
            row.message_date = self._normalize_dt(message.message_date) or row.message_date
            row.edit_date = self._normalize_dt(message.edit_date)
            row.deleted_at = None if message.sync_state != "deleted" else (row.deleted_at or _now())
            row.sync_state = str(message.sync_state or "active").strip() or "active"
            row.meta = _dump_json(message.meta)
            row.updated_at = _now()

            if row.history_id and row.text:
                history = session.query(History).filter_by(id=row.history_id).first()
                if history and history.content != row.text:
                    history.content = row.text
                    history.timestamp = row.message_date or history.timestamp

            chat.last_synced_message_id = max(
                int(chat.last_synced_message_id or 0),
                int(message.telegram_message_id),
            )
            chat.last_synced_at = _now()
            session.commit()
            session.refresh(row)
            return row
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def mark_deleted(
        self,
        *,
        character_name: str,
        telegram_message_ids: list[int],
        telegram_chat_id: int | None = None,
        delete_history: bool = False,
    ) -> int:
        ids = [int(item) for item in telegram_message_ids or [] if int(item or 0) > 0]
        if not ids:
            return 0
        session: Session = SessionLocal()
        try:
            character = session.query(Character).filter_by(name=character_name).first()
            if not character:
                return 0
            query = session.query(TelegramMessage).filter(
                TelegramMessage.character_id == character.id,
                TelegramMessage.telegram_message_id.in_(ids),
                TelegramMessage.sync_state != "deleted",
            )
            if telegram_chat_id is not None:
                query = query.filter(TelegramMessage.telegram_chat_id == int(telegram_chat_id))
            rows = query.all()
            for row in rows:
                row.sync_state = "deleted"
                row.deleted_at = _now()
                row.updated_at = _now()
                if delete_history and row.history_id:
                    history = session.query(History).filter_by(id=row.history_id).first()
                    if history:
                        session.delete(history)
            session.commit()
            return len(rows)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def create_job(
        self,
        *,
        job_type: str,
        character_name: str | None = None,
        telegram_chat_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        session: Session = SessionLocal()
        try:
            character_id = None
            if character_name:
                character = session.query(Character).filter_by(name=character_name).first()
                character_id = character.id if character else None
            job = TelegramSyncJob(
                id=str(uuid.uuid4()),
                job_type=str(job_type or "telegram_sync").strip() or "telegram_sync",
                status="pending",
                character_id=character_id,
                telegram_chat_id=int(telegram_chat_id) if telegram_chat_id is not None else None,
                payload=_dump_json(payload),
                created_at=_now(),
                updated_at=_now(),
            )
            session.add(job)
            session.commit()
            return job.id
        finally:
            session.close()

    def update_job(
        self,
        job_id: str,
        *,
        status: str,
        error: str | None = None,
        cursor_message_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if not job_id:
            return
        session: Session = SessionLocal()
        try:
            job = session.query(TelegramSyncJob).filter_by(id=job_id).first()
            if not job:
                return
            now = _now()
            job.status = str(status or job.status)
            if status == "running" and not job.started_at:
                job.started_at = now
            if status in {"completed", "failed", "cancelled"}:
                job.completed_at = now
            if cursor_message_id is not None:
                job.cursor_message_id = int(cursor_message_id)
            if payload is not None:
                job.payload = _dump_json(payload)
            job.error = error
            job.updated_at = now
            session.commit()
        finally:
            session.close()

    def _upsert_chat(self, session: Session, message: TelegramSyncMessage) -> TelegramChat:
        chat = session.query(TelegramChat).filter_by(telegram_chat_id=int(message.telegram_chat_id)).first()
        if chat is None:
            chat = TelegramChat(
                id=str(uuid.uuid4()),
                telegram_chat_id=int(message.telegram_chat_id),
                created_at=_now(),
            )
            session.add(chat)
        chat.chat_kind = str(message.chat_kind or "unknown").strip().lower() or "unknown"
        chat.title = str(message.chat_title or "").strip() or None
        chat.username = str(message.chat_username or "").strip() or None
        chat.is_owner_chat = bool(message.is_owner_chat)
        chat.updated_at = _now()
        return chat

    def _upsert_user(self, session: Session, message: TelegramSyncMessage) -> Optional[TelegramUser]:
        sender_id = message.sender_telegram_user_id
        if sender_id is None:
            return None
        try:
            sender_id = int(sender_id)
        except Exception:
            return None
        if sender_id == 0:
            return None
        user = session.query(TelegramUser).filter_by(telegram_user_id=sender_id).first()
        if user is None:
            user = TelegramUser(
                id=str(uuid.uuid4()),
                telegram_user_id=sender_id,
                telegram_user_uuid=_telegram_user_uuid(sender_id),
                created_at=_now(),
            )
            session.add(user)
        user.username = str(message.sender_username or "").strip() or None
        user.display_name = str(message.sender_name or "").strip() or None
        user.is_owner = bool(message.is_owner_sender)
        user.trust_level = 2 if user.is_owner else int(user.trust_level or 0)
        user.last_seen_at = self._normalize_dt(message.message_date) or _now()
        user.updated_at = _now()
        return user

    @staticmethod
    def _normalize_dt(value: Any) -> Optional[datetime]:
        if not isinstance(value, datetime):
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


telegram_sync_service = TelegramSyncService()
