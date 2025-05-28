# =========================================================
# Модуль: sqlite_service.py
# Назначение: Управление SQLite-базой данных:
#             создание таблиц, подключение, сессии.
# Используется в: database_service.py
# Особенности:
# - Использует SQLAlchemy ORM
# - Создаёт файл БД при первом запуске
# - Таблицы: Characters, History (готово к расширению)
# =========================================================

import os
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    create_engine, Column, String, Text, ForeignKey, DateTime
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# 📍 Путь к базе (создастся в storage/database/)
DB_PATH = os.path.join("storage", "database", "core.db")
DB_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False)
Base = declarative_base()


# 📌 Таблица персонажей
class Character(Base):
    __tablename__ = "characters"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, unique=True, index=True, nullable=False)
    configs = Column(Text, default="{}")  # JSON в виде строки
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    history = relationship("History", back_populates="character")


# 📌 Таблица истории
class History(Base):
    __tablename__ = "history"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    character_id = Column(String, ForeignKey("characters.id"), nullable=False)
    role = Column(String, nullable=False)  # 'user' / 'assistant'
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.now(timezone.utc))

    character = relationship("Character", back_populates="history")


# 📦 Инициализация БД
def create_sqlite_database():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    Base.metadata.create_all(bind=engine)
    

def add_history_entry(character_name: str, role: str, content: str, timestamp: datetime):
    session = SessionLocal()
    try:
        character = session.query(Character).filter(Character.name == character_name).first()
        if not character:
            raise ValueError(f"Персонаж '{character_name}' не найден в базе.")

        message = History(
            id=str(uuid.uuid4()),
            character_id=character.id,
            role=role,
            content=content,
            timestamp=timestamp
        )

        session.add(message)
        session.commit()
    finally:
        session.close()
        
        
def get_or_create_character_sqlite(name: str):
    session = SessionLocal()
    try:
        character = session.query(Character).filter_by(name=name).first()
        if character:
            return character

        new_character = Character(id=str(uuid.uuid4()), name=name)
        session.add(new_character)
        session.commit()
        session.refresh(new_character)
        return new_character

    except IntegrityError:
        session.rollback()
        # На случай гонки — пробуем ещё раз
        return session.query(Character).filter_by(name=name).first()

    finally:
        session.close()
        

def get_history_sqlite(character_name: str, limit: int = 20):
    session = SessionLocal()
    try:
        character = session.query(Character).filter_by(name=character_name).first()
        if not character:
            return []

        messages = (
            session.query(History)
            .filter_by(character_id=character.id)
            .order_by(History.timestamp.desc())
            .limit(limit)
            .all()
        )

        return [
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat()
            }
            for msg in reversed(messages)
        ]
    finally:
        session.close()