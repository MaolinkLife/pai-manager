import json
import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy.orm import Session, joinedload

from models.models import History, Reasoning
from modules.database.core import SessionLocal
from modules.system.logger import AuditStatus, log_audit_entry
from modules.storage.service import (
    delete_media_files,
    save_media_for_message,
    serialize_media_entries,
)
from utils.time_utils import format_user_datetime, to_user_tz_iso


def add_history(
    character_id: str,
    role: str,
    content: str,
    timestamp: Optional[datetime] = None,
    session: Optional[Session] = None,
    media_items: Optional[list] = None,
    tags: Optional[Sequence[str]] = None,
    runtime_meta: Optional[dict] = None,
    parent_message_id: Optional[str] = None,
    variant_group_id: Optional[str] = None,
    variant_index: Optional[int] = None,
    active_variant: bool = True,
):
    own_session = False
    if session is None:
        session = SessionLocal()
        own_session = True

    try:
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        if role == "assistant" and variant_group_id and active_variant:
            (
                session.query(History)
                .filter(
                    History.character_id == character_id,
                    History.role == "assistant",
                    History.variant_group_id == variant_group_id,
                )
                .update({"active_variant": False}, synchronize_session=False)
            )

        entry = History(
            id=str(uuid.uuid4()),
            character_id=character_id,
            role=role,
            content=content,
            timestamp=timestamp,
            tags=json.dumps(list(tags or []), ensure_ascii=False),
            runtime_meta=json.dumps(runtime_meta or {}, ensure_ascii=False),
            parent_message_id=parent_message_id,
            variant_group_id=variant_group_id,
            variant_index=int(variant_index or 1),
            active_variant=bool(active_variant),
        )
        session.add(entry)
        session.commit()
        session.refresh(entry)

        media_count_in = len(media_items) if media_items else 0
        log_audit_entry(
            "history_media_received",
            "[History] Incoming media payload.",
            AuditStatus.INFO,
            details={
                "message_id": entry.id,
                "role": role,
                "media_count": media_count_in,
            },
        )

        media_payload = []
        if media_items:
            storage_entries = save_media_for_message(entry.id, media_items)
            media_payload = serialize_media_entries(storage_entries)

        log_audit_entry(
            "history_media_saved",
            "[History] Saved message with media payload.",
            AuditStatus.INFO,
            details={
                "message_id": entry.id,
                "role": role,
                "media_count": len(media_payload),
            },
        )

        entry.media_payload = media_payload
        return entry
    finally:
        if own_session:
            session.close()


def update_history_runtime_meta(
    message_id: str, runtime_meta: dict, session: Optional[Session] = None
) -> bool:
    own_session = False
    if session is None:
        session = SessionLocal()
        own_session = True

    try:
        message = session.query(History).filter_by(id=message_id).first()
        if not message:
            return False
        message.runtime_meta = json.dumps(runtime_meta or {}, ensure_ascii=False)
        session.commit()
        return True
    except Exception:
        session.rollback()
        return False
    finally:
        if own_session:
            session.close()


def add_reasoning_entry(
    message_id: str,
    content: str,
    session: Optional[Session] = None,
):
    if not content:
        return None

    own_session = False
    if session is None:
        session = SessionLocal()
        own_session = True

    try:
        existing = session.query(Reasoning).filter_by(message_id=message_id).first()
        if existing:
            existing.content = content
            session.commit()
            session.refresh(existing)
            return existing

        entry = Reasoning(message_id=message_id, content=content)
        session.add(entry)
        session.commit()
        session.refresh(entry)

        return entry
    finally:
        if own_session:
            session.close()


def append_to_history_message(
    message_id: str,
    content_delta: str,
    *,
    reasoning_delta: Optional[str] = None,
    media_items: Optional[list] = None,
    runtime_meta: Optional[dict] = None,
):
    session: Session = SessionLocal()
    try:
        message = (
            session.query(History)
            .options(joinedload(History.reasoning), joinedload(History.media))
            .filter_by(id=message_id)
            .first()
        )
        if not message:
            raise ValueError("Message not found.")
        if message.role != "assistant":
            raise ValueError("Only assistant messages can be continued.")

        delta = str(content_delta or "")
        if delta:
            message.content = (message.content or "") + delta

        if runtime_meta is not None:
            message.runtime_meta = json.dumps(runtime_meta or {}, ensure_ascii=False)

        combined_reasoning = ""
        existing_reasoning = getattr(message, "reasoning", None)
        if existing_reasoning and existing_reasoning.content:
            combined_reasoning = existing_reasoning.content.strip()
        if reasoning_delta:
            combined_reasoning = "\n".join(
                item.strip()
                for item in [combined_reasoning, str(reasoning_delta or "").strip()]
                if item.strip()
            )
        if combined_reasoning:
            if existing_reasoning:
                existing_reasoning.content = combined_reasoning
            else:
                session.add(Reasoning(message_id=message.id, content=combined_reasoning))

        session.commit()
        session.refresh(message)

        media_payload = serialize_media_entries(getattr(message, "media", []) or [])
        if media_items:
            storage_entries = save_media_for_message(message.id, media_items)
            media_payload = serialize_media_entries(storage_entries)

        message.media_payload = media_payload
        return message
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def activate_history_variant(message_id: str) -> dict:
    session: Session = SessionLocal()
    try:
        message = (
            session.query(History)
            .options(joinedload(History.reasoning), joinedload(History.media))
            .filter_by(id=message_id)
            .first()
        )
        if not message:
            raise ValueError("Message not found.")
        if message.role != "assistant":
            raise ValueError("Only assistant variants can be activated.")
        group_id = str(getattr(message, "variant_group_id", "") or "").strip()
        if not group_id:
            group_id = message.parent_message_id or message.id
            message.variant_group_id = group_id
            message.variant_index = int(getattr(message, "variant_index", 1) or 1)

        (
            session.query(History)
            .filter(
                History.character_id == message.character_id,
                History.role == "assistant",
                History.variant_group_id == group_id,
            )
            .update({"active_variant": False}, synchronize_session=False)
        )
        message.active_variant = True
        session.commit()
        session.refresh(message)
        siblings = (
            session.query(History)
            .filter(
                History.character_id == message.character_id,
                History.role == "assistant",
                History.variant_group_id == group_id,
            )
            .order_by(History.variant_index.asc(), History.timestamp.asc())
            .all()
        )
        return {
            "id": message.id,
            "role": message.role,
            "content": (
                f"<think>\n{message.reasoning.content.strip()}\n</think>\n\n{message.content}"
                if getattr(message, "reasoning", None) and (message.reasoning.content or "").strip()
                else message.content
            ),
            "timestamp": to_user_tz_iso(message.timestamp),
            "media": serialize_media_entries(getattr(message, "media", []) or []),
            "parent_message_id": getattr(message, "parent_message_id", None),
            "variant_group_id": getattr(message, "variant_group_id", None),
            "variant_index": getattr(message, "variant_index", None) or 1,
            "active_variant": bool(getattr(message, "active_variant", True)),
            "variants": {
                "group_id": group_id,
                "count": len(siblings),
                "active_id": message.id,
                "active_index": int(getattr(message, "variant_index", 1) or 1),
                "items": [
                    {
                        "id": item.id,
                        "index": int(getattr(item, "variant_index", 1) or 1),
                        "active": item.id == message.id,
                    }
                    for item in siblings
                ],
            },
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_reasoning_by_message_id(message_id: str) -> Optional[str]:
    session: Session = SessionLocal()
    try:
        entry = session.query(Reasoning).filter_by(message_id=message_id).first()
        return entry.content if entry else None
    finally:
        session.close()


def get_history(character_id: str, limit: int = 20, offset: int = 0):
    session: Session = SessionLocal()
    try:
        return (
            session.query(History)
            .options(joinedload(History.reasoning), joinedload(History.media))
            .filter(
                History.character_id == character_id,
                ((History.role != "assistant") | (History.active_variant.is_(True))),
            )
            .order_by(History.timestamp.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
    finally:
        session.close()


def get_history_since(character_id: str, start_time):
    if isinstance(start_time, str):
        try:
            start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except Exception:
            start_time = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
    elif not isinstance(start_time, datetime):
        start_time = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    session: Session = SessionLocal()
    try:
        return (
            session.query(History)
            .options(joinedload(History.reasoning), joinedload(History.media))
            .filter(
                History.character_id == character_id,
                History.timestamp >= start_time,
                ((History.role != "assistant") | (History.active_variant.is_(True))),
            )
            .order_by(History.timestamp.asc())
            .all()
        )
    finally:
        session.close()


def delete_message(message_id: str) -> bool:
    session: Session = SessionLocal()
    try:
        message = (
            session.query(History)
            .options(joinedload(History.reasoning), joinedload(History.media))
            .filter_by(id=message_id)
            .first()
        )
        if not message:
            return False

        delete_media_files(message.media)
        session.delete(message)
        session.commit()
        return True
    except Exception:
        session.rollback()
        return False
    finally:
        session.close()


def delete_message_chain(user_message_id: str) -> int:
    session: Session = SessionLocal()
    try:
        user_msg = (
            session.query(History)
            .options(joinedload(History.reasoning), joinedload(History.media))
            .filter_by(id=user_message_id)
            .first()
        )
        if not user_msg or user_msg.role != "user":
            return 0

        assistant_msg = (
            session.query(History)
            .options(joinedload(History.reasoning), joinedload(History.media))
            .filter(
                History.character_id == user_msg.character_id,
                History.timestamp > user_msg.timestamp,
                History.role == "assistant",
            )
            .order_by(History.timestamp.asc())
            .first()
        )

        count = 0
        delete_media_files(user_msg.media)
        session.delete(user_msg)
        count += 1

        if assistant_msg:
            delete_media_files(assistant_msg.media)
            session.delete(assistant_msg)
            count += 1

        session.commit()
        return count
    except Exception:
        session.rollback()
        return 0
    finally:
        session.close()


def get_message_by_id(message_id: str):
    session: Session = SessionLocal()
    try:
        message = (
            session.query(History)
            .options(joinedload(History.media))
            .filter_by(id=message_id)
            .first()
        )
        if not message:
            return None

        return {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "timestamp": format_user_datetime(message.timestamp),
            "character_id": message.character_id,
            "media": serialize_media_entries(message.media),
        }
    finally:
        session.close()


def get_full_history(character_id: str):
    session: Session = SessionLocal()
    try:
        messages = (
            session.query(History)
            .filter_by(character_id=character_id)
            .order_by(History.timestamp.asc())
            .all()
        )

        return [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "timestamp": format_user_datetime(msg.timestamp),
            }
            for msg in messages
        ]
    finally:
        session.close()


def get_last_user_message_time(character_id: str):
    session: Session = SessionLocal()
    try:
        last_user_msg = (
            session.query(History)
            .filter_by(character_id=character_id, role="user")
            .order_by(History.timestamp.desc())
            .first()
        )

        return last_user_msg.timestamp if last_user_msg else None
    finally:
        session.close()


def get_last_messages(character_id: str, limit: int = 10):
    session: Session = SessionLocal()
    try:
        messages = (
            session.query(History)
            .filter(
                History.character_id == character_id,
                ((History.role != "assistant") | (History.active_variant.is_(True))),
            )
            .order_by(History.timestamp.desc())
            .limit(limit)
            .all()
        )

        return [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "timestamp": format_user_datetime(msg.timestamp),
            }
            for msg in reversed(messages)
        ]
    finally:
        session.close()


def get_messages_by_ids(message_ids: Sequence[str]):
    if not message_ids:
        return []
    session: Session = SessionLocal()
    try:
        return (
            session.query(History)
            .filter(History.id.in_(message_ids))
            .order_by(History.timestamp.asc())
            .all()
        )
    finally:
        session.close()


def delete_telegram_history_entries(
    character_id: str,
    *,
    chat_id: Optional[int],
    telegram_message_ids: Sequence[int],
) -> int:
    ids = {int(item) for item in (telegram_message_ids or []) if isinstance(item, int) or str(item).strip().isdigit()}
    if not ids:
        return 0

    session: Session = SessionLocal()
    try:
        rows = (
            session.query(History)
            .options(joinedload(History.reasoning), joinedload(History.media))
            .filter(History.character_id == character_id)
            .all()
        )
        to_delete: list[History] = []
        for row in rows:
            runtime_meta_raw = getattr(row, "runtime_meta", "{}") or "{}"
            try:
                runtime_meta = json.loads(runtime_meta_raw)
            except Exception:
                continue
            if not isinstance(runtime_meta, dict):
                continue
            transport = runtime_meta.get("transport")
            if not isinstance(transport, dict):
                continue
            if str(transport.get("name") or "").strip().lower() != "telegram":
                continue
            try:
                row_chat_id = int(transport.get("chat_id"))
                row_message_id = int(transport.get("message_id"))
            except Exception:
                continue
            if chat_id is not None and row_chat_id != int(chat_id):
                continue
            if row_message_id not in ids:
                continue
            to_delete.append(row)

        if chat_id is None and to_delete:
            chats_by_message_id: dict[int, set[int]] = {}
            for row in to_delete:
                try:
                    runtime_meta = json.loads(getattr(row, "runtime_meta", "{}") or "{}")
                    transport = runtime_meta.get("transport") if isinstance(runtime_meta, dict) else {}
                    row_chat_id = int((transport or {}).get("chat_id"))
                    row_message_id = int((transport or {}).get("message_id"))
                except Exception:
                    continue
                chats_by_message_id.setdefault(row_message_id, set()).add(row_chat_id)
            unambiguous_message_ids = {
                message_id
                for message_id, chat_ids in chats_by_message_id.items()
                if len(chat_ids) == 1
            }
            to_delete = [
                row
                for row in to_delete
                if int(
                    (
                        json.loads(getattr(row, "runtime_meta", "{}") or "{}").get("transport")
                        or {}
                    ).get("message_id")
                )
                in unambiguous_message_ids
            ]

        if not to_delete:
            return 0

        delete_messages_from_database(session, to_delete)
        return len(to_delete)
    finally:
        session.close()


def prepare_reroll_payload(message_id: str) -> dict:
    session: Session = SessionLocal()
    try:
        assistant_msg = get_message_from_database(
            session, filters={"id": message_id}, expected_role="assistant"
        )

        user_msg = get_last_user_message_before(
            session,
            character_id=assistant_msg.character_id,
            before_timestamp=assistant_msg.timestamp,
        )

        variant_info = prepare_assistant_variant_reroll(
            session,
            assistant_msg=assistant_msg,
            user_msg=user_msg,
        )

        payload = {
            "id": user_msg.id,
            "role": "user",
            "content": user_msg.content,
            "timestamp": to_user_tz_iso(
                user_msg.timestamp if hasattr(user_msg, "timestamp") else None
            ),
            "media": serialize_media_entries(getattr(user_msg, "media", []) or []),
            "variant_parent_message_id": user_msg.id,
            "variant_group_id": variant_info["variant_group_id"],
            "variant_index": variant_info["next_variant_index"],
            "reroll_target_message_id": assistant_msg.id,
        }

        return payload
    finally:
        session.close()


def prepare_continue_payload(message_id: str) -> dict:
    session: Session = SessionLocal()
    try:
        assistant_msg = get_message_from_database(
            session, filters={"id": message_id}, expected_role="assistant"
        )
        user_msg = get_last_user_message_before(
            session,
            character_id=assistant_msg.character_id,
            before_timestamp=assistant_msg.timestamp,
        )
        history = build_history_up_to_assistant_message(
            session,
            character_id=assistant_msg.character_id,
            assistant_msg=assistant_msg,
            limit=32,
        )

        return {
            "id": str(uuid.uuid4()),
            "role": "user",
            "content": (
                "Продолжи предыдущий ответ с того места, где он остановился. "
                "Не повторяй уже сказанное, не начинай заново и сохрани тот же стиль речи."
            ),
            "display_content": "",
            "suppress_user_echo": True,
            "append_to_message_id": assistant_msg.id,
            "preserve_history": True,
            "history": history,
            "timestamp": to_user_tz_iso(None),
            "media": serialize_media_entries(getattr(user_msg, "media", []) or []),
        }
    finally:
        session.close()


def prepare_edit_payload(message_id: str, new_content: str) -> dict:
    session: Session = SessionLocal()
    try:
        user_msg = get_message_from_database(
            session, filters={"id": message_id}, expected_role="user"
        )
        updated_text = (new_content or "").strip()
        if not updated_text:
            raise ValueError("new_content is empty")

        assistant_msg = (
            session.query(History)
            .filter(
                History.character_id == user_msg.character_id,
                History.timestamp > user_msg.timestamp,
                History.role == "assistant",
            )
            .order_by(History.timestamp.asc())
            .first()
        )

        payload = {
            "id": user_msg.id,
            "role": "user",
            "content": updated_text,
            "timestamp": to_user_tz_iso(
                user_msg.timestamp if hasattr(user_msg, "timestamp") else None
            ),
            "media": serialize_media_entries(getattr(user_msg, "media", []) or []),
        }

        to_delete = [user_msg]
        if assistant_msg:
            to_delete.append(assistant_msg)
        delete_messages_from_database(session, to_delete)
        return payload
    finally:
        session.close()


def get_message_from_database(session, filters: dict, expected_role: str = None):
    query = session.query(History).filter_by(**filters)
    result = query.first()

    if not result:
        raise ValueError("Message not found.")

    if expected_role and result.role != expected_role:
        raise ValueError(
            f"Message found, but role '{result.role}' does not match expected '{expected_role}'."
        )

    return result


def get_last_user_message_before(session, character_id, before_timestamp):
    result = (
        session.query(History)
        .filter(
            History.character_id == character_id,
            History.timestamp < before_timestamp,
            History.role == "user",
        )
        .order_by(History.timestamp.desc())
        .first()
    )

    if not result:
        raise ValueError("No matching user message found.")

    return result


def delete_messages_from_database(session, messages: list):
    try:
        for msg in messages or []:
            delete_media_files(getattr(msg, "media", []))
            session.delete(msg)
        session.commit()
    except Exception:
        session.rollback()
        raise


def build_history_up_to_user_message(session, character_id, user_msg, limit=32):
    user_timestamp = user_msg.timestamp

    history_before_user = (
        session.query(History)
        .filter(History.character_id == character_id, History.timestamp < user_timestamp)
        .order_by(History.timestamp.desc())
        .limit(limit)
        .all()
    )

    history = [
        {
            "role": msg.role,
            "content": msg.content,
            "timestamp": msg.timestamp.isoformat(),
        }
        for msg in reversed(history_before_user)
    ]

    history.append(
        {
            "role": "user",
            "content": user_msg.content,
            "timestamp": user_timestamp.isoformat(),
        }
    )

    return history


def build_history_up_to_assistant_message(session, character_id, assistant_msg, limit=32):
    assistant_timestamp = assistant_msg.timestamp

    history_before_assistant = (
        session.query(History)
        .filter(
            History.character_id == character_id,
            History.timestamp <= assistant_timestamp,
        )
        .order_by(History.timestamp.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": msg.id,
            "role": msg.role,
            "content": msg.content,
            "timestamp": msg.timestamp.isoformat(),
        }
        for msg in reversed(history_before_assistant)
    ]


def prepare_assistant_variant_reroll(session, *, assistant_msg, user_msg) -> dict:
    group_id = (
        str(getattr(assistant_msg, "variant_group_id", "") or "").strip()
        or user_msg.id
    )
    if not getattr(assistant_msg, "parent_message_id", None):
        assistant_msg.parent_message_id = user_msg.id
    if not getattr(assistant_msg, "variant_group_id", None):
        assistant_msg.variant_group_id = group_id
    if not getattr(assistant_msg, "variant_index", None):
        assistant_msg.variant_index = 1
    if getattr(assistant_msg, "active_variant", None) is None:
        assistant_msg.active_variant = True

    siblings = (
        session.query(History)
        .filter(
            History.character_id == assistant_msg.character_id,
            History.role == "assistant",
            History.variant_group_id == group_id,
        )
        .all()
    )
    max_index = max(
        [int(getattr(item, "variant_index", 1) or 1) for item in siblings] or [1]
    )
    session.commit()
    return {"variant_group_id": group_id, "next_variant_index": max_index + 1}


async def reroll_assistant_message(message_id: str) -> dict:
    # Lazy imports to avoid circular import between memory/history <-> decision_layer.
    from core.decision_layer import decision_layer
    from modules.generative import conversation

    session: Session = SessionLocal()
    try:
        assistant_msg = get_message_from_database(
            session, filters={"id": message_id}, expected_role="assistant"
        )

        user_msg = get_last_user_message_before(
            session,
            character_id=assistant_msg.character_id,
            before_timestamp=assistant_msg.timestamp,
        )

        # Keep original user message in DB; reroll must only replace assistant response.
        delete_messages_from_database(session, [assistant_msg])

        history = build_history_up_to_user_message(
            session, character_id=user_msg.character_id, user_msg=user_msg, limit=32
        )

        last_user = history[-1] if history else None
        if not last_user or last_user.get("role") != "user":
            raise ValueError("Unable to locate user message for reroll")

        user_message = dict(last_user)
        user_message.setdefault("history", history[:-1])

        decision_context = await decision_layer.process_message(user_message, None)
        decision_context.pop("raw_media", None)
        new_response = await conversation.generate_standard(
            decision_context,
            history,
            user_message,
            return_full=True,
        )

        return {
            "role": "assistant",
            "content": new_response["content"],
            "timestamp": (
                new_response["timestamp"].isoformat()
                if hasattr(new_response["timestamp"], "isoformat")
                else str(new_response["timestamp"])
            ),
            "id": new_response["id"],
        }
    finally:
        session.close()


def get_lorebook_entries(character_name: str):
    return []
