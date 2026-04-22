import json
from typing import Sequence

from sqlalchemy.orm import Session

from models.models import Message
from modules.database.core import SessionLocal
from modules.system.logger import AuditStatus, log_audit_entry
from utils.crypto_utils import decrypt, encrypt
from utils.time_utils import format_user_datetime


def add_message(
    user_id: str,
    role: str,
    content: str,
    dialog_id: str = None,
    volatile: bool = False,
    tags: Sequence[str] | None = None,
):
    session: Session = SessionLocal()
    try:
        msg = Message(
            user_id=user_id,
            role=role,
            content=encrypt(content),
            dialog_id=dialog_id,
            volatile=volatile,
            tags=json.dumps(list(tags or []), ensure_ascii=False),
        )
        session.add(msg)
        session.commit()
        session.refresh(msg)

        log_audit_entry(
            event_type="Message.Insert",
            msg="Message added to DB",
            status=AuditStatus.SUCCESS,
            details={
                "id": msg.id,
                "role": role,
                "user_id": user_id,
                "volatile": volatile,
            },
        )

        return {
            "id": msg.id,
            "role": msg.role,
            "content": decrypt(msg.content),
            "timestamp": format_user_datetime(msg.timestamp),
            "tags": json.loads(getattr(msg, "tags", "[]") or "[]"),
        }

    finally:
        session.close()


def get_messages(user_id: str, limit: int = 20):
    session: Session = SessionLocal()
    try:
        messages = (
            session.query(Message)
            .filter_by(user_id=user_id)
            .order_by(Message.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": m.id,
                "role": m.role,
                "content": decrypt(m.content),
                "timestamp": format_user_datetime(m.timestamp),
                "tags": json.loads(getattr(m, "tags", "[]") or "[]"),
            }
            for m in reversed(messages)
        ]
    finally:
        session.close()
