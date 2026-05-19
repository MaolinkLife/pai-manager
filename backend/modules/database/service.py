from datetime import datetime, timezone
import json

from modules.database.core import create_database as create_sqlite_database
from modules.memory import history as history_service
from modules.memory import message as message_service
from modules.memory import conversation_state_log as conversation_state_log_service
from modules.storage.service import serialize_media_entries
from modules.system import character as character_service
from modules.system import user as user_service
from modules.system.service import get_active_character_name
from modules.system.logger import log_error
from utils.time_utils import to_user_tz_iso

db_type = "sqlite"  # later: postgres, etc.


def create_database():
    if db_type == "sqlite":
        return create_sqlite_database()
    raise ValueError(f"Unknown database type: {db_type}")


def get_or_create_user(name: str, trust_level: int = 0):
    return user_service.get_or_create_user(name, trust_level)


def get_owner():
    return user_service.get_owner()


def get_or_create_character(name: str):
    return character_service.get_or_create_character(name)


def add_message(
    user_id: str, role: str, content: str, dialog_id: str = None, volatile: bool = False
):
    return message_service.add_message(user_id, role, content, dialog_id, volatile)


def get_messages(user_id: str, limit: int = 20):
    return message_service.get_messages(user_id, limit)


def add_message_to_history(
    character_name: str,
    role: str,
    content: str,
    timestamp: datetime = None,
    media: list | None = None,
    tags: list | None = None,
    runtime_meta: dict | None = None,
    parent_message_id: str | None = None,
    variant_group_id: str | None = None,
    variant_index: int | None = None,
    active_variant: bool = True,
):
    if isinstance(timestamp, str):
        try:
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except Exception as exc:
            log_error(f"[Error parsing timestamp]: {exc}")
            timestamp = datetime.now(timezone.utc)

    char = character_service.get_character(character_name)
    if not char:
        raise ValueError(f"Character '{character_name}' was not found")

    return history_service.add_history(
        char.id,
        role,
        content,
        timestamp,
        media_items=media,
        tags=tags,
        runtime_meta=runtime_meta,
        parent_message_id=parent_message_id,
        variant_group_id=variant_group_id,
        variant_index=variant_index,
        active_variant=active_variant,
    )


def add_tool_event_to_history(
    character_name: str,
    tool_name: str,
    content: str,
    *,
    timestamp: datetime = None,
    tags: list | None = None,
    runtime_meta: dict | None = None,
):
    # Tool events are intentionally not persisted in dialog history.
    from core import tool_event_bus

    tool_event_bus.emit_tool_event(
        tool_name=str(tool_name or "").strip() or "unknown_tool",
        content=str(content or ""),
        status=None,
        source="database_service.add_tool_event_to_history",
        runtime_meta=runtime_meta,
        character_name=character_name,
        timestamp=timestamp,
        tags=tags,
    )
    return None


def get_history(character_name: str, limit: int = 20, offset: int = 0):
    char = character_service.get_character(character_name)
    if not char:
        return []

    rows = history_service.get_history(char.id, limit, offset)
    return _serialize_history_rows(rows)


def delete_telegram_history_by_message_id(
    *,
    character_name: str,
    chat_id: int | None,
    telegram_message_ids: list[int],
) -> int:
    char = character_service.get_character(character_name)
    if not char:
        return 0
    return history_service.delete_telegram_history_entries(
        char.id,
        chat_id=int(chat_id) if chat_id is not None else None,
        telegram_message_ids=list(telegram_message_ids or []),
    )


def get_history_since(character_name: str, start_time):
    char = character_service.get_character(character_name)
    if not char:
        return []

    rows = history_service.get_history_since(char.id, start_time)
    return _serialize_history_rows(rows)


def delete_message_chain(message_id: str):
    return history_service.delete_message_chain(message_id)


def delete_message(message_id: str):
    return history_service.delete_message(message_id)


async def reroll_message(message_id: str):
    return await history_service.reroll_assistant_message(message_id)


def prepare_reroll_payload(message_id: str) -> dict:
    return history_service.prepare_reroll_payload(message_id)


def prepare_continue_payload(message_id: str) -> dict:
    return history_service.prepare_continue_payload(message_id)


def prepare_edit_payload(message_id: str, new_content: str) -> dict:
    return history_service.prepare_edit_payload(message_id, new_content)


def get_last_user_message_time(character_name: str):
    return history_service.get_last_user_message_time(character_name)


def get_history_by_ids(message_ids):
    return history_service.get_messages_by_ids(message_ids)


def get_last_messages(character_name: str, limit: int = 10):
    return history_service.get_last_messages(character_name, limit)


def get_message_by_id(message_id: str):
    return history_service.get_message_by_id(message_id)


def get_full_history(character_name: str):
    return history_service.get_full_history(character_name)


def get_lorebook_entries():
    character_name = get_active_character_name(default="default_waifu")
    return history_service.get_lorebook_entries(character_name)


def add_reasoning_entry(message_id: str, content: str):
    return history_service.add_reasoning_entry(message_id, content)


def append_to_history_message(
    message_id: str,
    content_delta: str,
    *,
    reasoning_delta: str | None = None,
    media: list | None = None,
    runtime_meta: dict | None = None,
):
    return history_service.append_to_history_message(
        message_id,
        content_delta,
        reasoning_delta=reasoning_delta,
        media_items=media,
        runtime_meta=runtime_meta,
    )


def activate_history_variant(message_id: str) -> dict:
    return history_service.activate_history_variant(message_id)


def get_reasoning_by_message_id(message_id: str):
    return history_service.get_reasoning_by_message_id(message_id)


def update_history_runtime_meta(message_id: str, runtime_meta: dict) -> bool:
    return history_service.update_history_runtime_meta(message_id, runtime_meta)


def add_conversation_state_log(
    character_name: str,
    conversation_state: dict,
    message_id: str | None = None,
    source: str = "memory_module",
):
    return conversation_state_log_service.add_log(
        character_name,
        conversation_state,
        message_id=message_id,
        source=source,
    )


def get_recent_conversation_state_logs(character_name: str, limit: int = 20):
    return conversation_state_log_service.get_recent_logs(character_name, limit=limit)


def _serialize_history_rows(rows):
    variant_meta = _build_variant_meta(rows)
    serialized = []
    for row in rows:
        row_variant_group = getattr(row, "variant_group_id", None)
        row_variants = variant_meta.get(row_variant_group) if row_variant_group else None
        serialized.append(
            {
                "id": row.id,
                "role": row.role,
                "content": _merge_reasoning(row),
                "timestamp": (
                    to_user_tz_iso(row.timestamp)
                    if hasattr(row, "timestamp")
                    else to_user_tz_iso(None)
                ),
                "media": serialize_media_entries(getattr(row, "media", [])),
                "tags": json.loads(getattr(row, "tags", "[]") or "[]"),
                "runtime_meta": json.loads(getattr(row, "runtime_meta", "{}") or "{}"),
                "parent_message_id": getattr(row, "parent_message_id", None),
                "variant_group_id": row_variant_group,
                "variant_index": getattr(row, "variant_index", None) or 1,
                "active_variant": bool(getattr(row, "active_variant", True)),
                "variants": row_variants,
            }
        )
    return serialized


def _build_variant_meta(rows):
    from modules.database.core import SessionLocal
    from models.models import History

    group_ids = {
        str(getattr(row, "variant_group_id", "") or "").strip()
        for row in rows or []
        if str(getattr(row, "variant_group_id", "") or "").strip()
    }
    if not group_ids:
        return {}

    session = SessionLocal()
    try:
        siblings = (
            session.query(History)
            .filter(History.variant_group_id.in_(group_ids), History.role == "assistant")
            .order_by(History.variant_group_id.asc(), History.variant_index.asc(), History.timestamp.asc())
            .all()
        )
        result = {}
        for group_id in group_ids:
            group = [item for item in siblings if item.variant_group_id == group_id]
            if not group:
                continue
            active = next((item for item in group if bool(item.active_variant)), group[-1])
            result[group_id] = {
                "group_id": group_id,
                "count": len(group),
                "active_id": active.id,
                "active_index": int(getattr(active, "variant_index", 1) or 1),
                "items": [
                    {
                        "id": item.id,
                        "index": int(getattr(item, "variant_index", 1) or 1),
                        "active": bool(getattr(item, "active_variant", False)),
                    }
                    for item in group
                ],
            }
        return result
    finally:
        session.close()


def _merge_reasoning(history_row) -> str:
    content = history_row.content or ""
    reasoning_entity = getattr(history_row, "reasoning", None)

    if reasoning_entity:
        reasoning_text = (reasoning_entity.content or "").strip()
        if reasoning_text:
            return f"<think>\n{reasoning_text}\n</think>\n\n{content}"

    return content
