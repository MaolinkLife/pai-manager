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
import json
from datetime import datetime, timezone
from sqlalchemy import (
    create_engine, Column, String, Text, ForeignKey, DateTime
)
from sqlalchemy.dialects.sqlite import BLOB  # эмуляция UUID
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
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.utcnow)

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