# ==========================================================
# Module: database_service.py
# Purpose: Central entry point for working with the database.
# Acts as a facade: routes calls to user_service, message_service,
# history_service, character_service depending on db_type.
# ==========================================================

from datetime import datetime, timezone

from services import user_service, message_service, history_service, character_service
from services.logger_service import log_error
from services.config_service import get_config_value
from fastapi import HTTPException

db_type = "sqlite"  # later: postgres, etc.


# =========================
# Initialization
# =========================
def create_database():
    if db_type == "sqlite":
        from services.db_core import create_database
        return create_database()
    raise ValueError(f"Unknown database type: {db_type}")


# =========================
# Users
# =========================
def get_or_create_user(name: str, trust_level: int = 0):
    return user_service.get_or_create_user(name, trust_level)


def get_owner():
    return user_service.get_owner()


# =========================
# Characters
# =========================
def get_or_create_character(name: str):
    return character_service.get_or_create_character(name)


# =========================
# Messages
# =========================
def add_message(user_id: str, role: str, content: str, dialog_id: str = None, volatile: bool = False):
    return message_service.add_message(user_id, role, content, dialog_id, volatile)


def get_messages(user_id: str, limit: int = 20):
    return message_service.get_messages(user_id, limit)


# =========================
# History (legacy support)
# =========================
def add_message_to_history(character_name: str, role: str, content: str, timestamp: datetime = None):
    if isinstance(timestamp, str):
        try:
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except Exception as e:
            log_error(f"[⚠️ Error parsing timestamp]: {e}")
            timestamp = datetime.now(timezone.utc)

    char = character_service.get_character(character_name)
    if not char:
       raise ValueError(f"Персонаж '{character_name}' не найден")


    return history_service.add_history(char.id, role, content, timestamp)


def get_history(character_name: str, limit: int = 20):
    char = character_service.get_character(character_name)
    if not char:
        return []
    
    rows = history_service.get_history(char.id, limit)
    
    return [
        {
            "id": r.id,
            "role": r.role,
            "content": r.content,
            "timestamp": r.timestamp.isoformat() if hasattr(r.timestamp, "isoformat") else str(r.timestamp),
        }
        for r in rows
    ]
        


def delete_message_chain(message_id: str):
    return history_service.delete_message_chain(message_id)


def delete_message(message_id: str):
    return history_service.delete_message(message_id)


async def reroll_message(message_id: str):
    return await history_service.reroll_assistant_message(message_id)


def get_last_user_message_time(character_name: str):
    return history_service.get_last_user_message_time(character_name)


def get_last_messages(character_name: str, limit: int = 10):
    return history_service.get_last_messages(character_name, limit)


def get_message_by_id(message_id: str):
    return history_service.get_message_by_id(message_id)


def get_full_history(character_name: str):
    return history_service.get_full_history(character_name)


def get_lorebook_entries():
    character_name = get_config_value("char_name")
    return history_service.get_lorebook_entries(character_name)
