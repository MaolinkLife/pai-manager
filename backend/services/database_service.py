# ==========================================================
# Module: database_service.py
# Purpose: Central entry point for working with the database.
# Responsible for selecting the desired engine (SQLite, PostgreSQL, etc.)
# and delegates execution to specific services.
# Used in: initialize.py, any services that work with the database.
# =========================================================

from services.logger_service import log_error
from services.sqlite_service import (
    create_sqlite_database,

    get_or_create_character_sqlite,
    get_history_sqlite,
    get_full_history_sqlite,
    add_history_entry,
   

    delete_message_sqlite,
    delete_message_chain_sqlite,

    reroll_assistant_message_sqlite,
    
    get_last_user_message_time_sqlite,
    get_message_pattern_sqlite,
    get_message_by_id_sqlite,
)
from datetime import datetime, timezone

# For now only SQLite as default. In the future - config or environment variable
db_type = "sqlite"

def create_database():
    if db_type == "sqlite":
        return create_sqlite_database()
    # elif db_type == "postgres":
    #     return postgres_service.create_database()

    raise ValueError(f"Unknown database type: {db_type}")


def get_or_create_character(name: str):
    if db_type == "sqlite":
        return get_or_create_character_sqlite(name)


def add_message_to_history(character_name: str, role: str, content: str, timestamp: datetime = None):
    # timestamp can be a string - validate
    if isinstance(timestamp, str):
        try:
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except Exception as e:
            log_error(f"[⚠️ Error parsing timestamp]: {e}")
            timestamp = datetime.now(timezone.utc)

    add_history_entry(character_name, role, content, timestamp)


def get_history(character_name: str, limit: int = 20):
    return get_history_sqlite(character_name, limit)


def delete_message_chain(message_id: str):
    deleted_count = delete_message_chain_sqlite(message_id)
    return {"status": "ok", "deleted": deleted_count}


def delete_message(message_id: str):
    success = delete_message_sqlite(message_id)
    return {"status": "ok" if success else "not_found"}

def reroll_message(message_id: str):
    return reroll_assistant_message_sqlite(message_id)


def get_last_user_message_time(character_name: str):
    if db_type == "sqlite":
        return get_last_user_message_time_sqlite(character_name)
    
    
def get_last_messages(char_name: str, limit=10):
    if db_type == "sqlite":
        return get_message_pattern_sqlite(char_name, limit)
    
    
def get_message_by_id(message_id: str):
    if db_type == "sqlite":
        return get_message_by_id_sqlite(message_id)
    
    
def get_full_history(character_name: str):
    if db_type == "sqlite":
        return get_full_history_sqlite(character_name)