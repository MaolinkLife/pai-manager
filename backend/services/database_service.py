# =========================================================
# Модуль: database_service.py
# Назначение: Центральная точка входа для работы с базой данных.
#             Отвечает за выбор нужного движка (SQLite, PostgreSQL и т.д.)
#             и делегирует выполнение конкретным сервисам.
# Используется в: initialize.py, любых сервисах с работой с БД.
# =========================================================

from services.sqlite_service import (
    create_sqlite_database,

    get_or_create_character_sqlite,
    get_history_sqlite,

    add_history_entry,

    delete_message_sqlite,
    delete_message_chain_sqlite,

    reroll_assistant_message_sqlite
)
from datetime import datetime, timezone

# Пока только SQLite как дефолт. В будущем — конфиг или переменная окружения
db_type = "sqlite"

def create_database():
    if db_type == "sqlite":
        return create_sqlite_database()
    # elif db_type == "postgres":
    #     return postgres_service.create_database()

    raise ValueError(f"Неизвестный тип базы данных: {db_type}")


def get_or_create_character(name: str):
    if db_type == "sqlite":
        return get_or_create_character_sqlite(name)


def add_message_to_history(character_name: str, role: str, content: str, timestamp: datetime = None):
    # timestamp может быть строкой — валидируем
    if isinstance(timestamp, str):
        try:
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except Exception as e:
            print(f"[⚠️ Ошибка парсинга timestamp]: {e}")
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