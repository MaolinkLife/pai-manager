# =========================================================
# Модуль: database_service.py
# Назначение: Центральная точка входа для работы с базой данных.
#             Отвечает за выбор нужного движка (SQLite, PostgreSQL и т.д.)
#             и делегирует выполнение конкретным сервисам.
# Используется в: initialize.py, любых сервисах с работой с БД.
# =========================================================

from services.sqlite_service import SessionLocal, Character, create_sqlite_database
from sqlalchemy.exc import IntegrityError
import uuid


def create_database():
    # Пока только SQLite как дефолт. В будущем — конфиг или переменная окружения
    db_type = "sqlite"

    if db_type == "sqlite":
        return create_sqlite_database()
    # elif db_type == "postgres":
    #     return postgres_service.create_database()

    raise ValueError(f"Неизвестный тип базы данных: {db_type}")


def get_or_create_character(name: str):
    session = SessionLocal()
    try:
        # Поиск персонажа по имени
        character = session.query(Character).filter(Character.name == name).first()
        if character:
            return character

        # Создание нового персонажа
        new_character = Character(id=str(uuid.uuid4()), name=name)
        session.add(new_character)
        session.commit()
        session.refresh(new_character)
        return new_character
    except IntegrityError:
        session.rollback()
        # Кто-то другой уже успел создать такого? Повторим запрос
        return session.query(Character).filter(Character.name == name).first()
    finally:
        session.close()