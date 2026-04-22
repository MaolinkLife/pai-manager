import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models.models import Character, ConversationStateLog
from modules.database.core import SessionLocal


def add_log(
    character_name: str,
    conversation_state: Dict[str, Any],
    *,
    message_id: Optional[str] = None,
    source: str = "memory_module",
    session: Optional[Session] = None,
) -> Optional[ConversationStateLog]:
    if not character_name or not isinstance(conversation_state, dict):
        return None

    own_session = False
    if session is None:
        session = SessionLocal()
        own_session = True

    try:
        character = session.query(Character).filter_by(name=character_name).first()
        if not character:
            return None

        last_message_at = _parse_timestamp(conversation_state.get("last_message_at"))
        raw_hours = conversation_state.get("hours_since_last_message")
        try:
            hours_since_last_message = (
                float(raw_hours) if raw_hours is not None else None
            )
        except (TypeError, ValueError):
            hours_since_last_message = None

        row = ConversationStateLog(
            id=str(uuid.uuid4()),
            character_id=character.id,
            message_id=(message_id or "").strip() or None,
            source=(source or "memory_module").strip(),
            last_message_at=last_message_at,
            hours_since_last_message=hours_since_last_message,
            inactivity_bucket=str(
                conversation_state.get("inactivity_bucket") or "unknown"
            ),
            last_topic=str(conversation_state.get("last_topic") or ""),
            recent_tone_summary=str(
                conversation_state.get("recent_tone_summary") or "neutral"
            ),
            payload=json.dumps(conversation_state, ensure_ascii=False),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row
    except Exception:
        session.rollback()
        return None
    finally:
        if own_session:
            session.close()


def get_recent_logs(character_name: str, limit: int = 20) -> List[Dict[str, Any]]:
    if not character_name:
        return []
    try:
        limit = max(0, int(limit))
    except (TypeError, ValueError):
        limit = 20

    session: Session = SessionLocal()
    try:
        character = session.query(Character).filter_by(name=character_name).first()
        if not character:
            return []

        rows = (
            session.query(ConversationStateLog)
            .filter(ConversationStateLog.character_id == character.id)
            .order_by(ConversationStateLog.created_at.desc())
            .limit(limit)
            .all()
        )
        payload: List[Dict[str, Any]] = []
        for row in rows:
            try:
                parsed = json.loads(row.payload or "{}")
            except Exception:
                parsed = {}
            payload.append(
                {
                    "id": row.id,
                    "message_id": row.message_id,
                    "source": row.source,
                    "last_message_at": (
                        row.last_message_at.isoformat() if row.last_message_at else None
                    ),
                    "hours_since_last_message": row.hours_since_last_message,
                    "inactivity_bucket": row.inactivity_bucket,
                    "last_topic": row.last_topic,
                    "recent_tone_summary": row.recent_tone_summary,
                    "payload": parsed,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
            )
        return payload
    finally:
        session.close()


def _parse_timestamp(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
