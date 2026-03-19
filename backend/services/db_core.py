# ==========================================================
# Module: db_core.py
# Purpose: Low-level DB core for SQLAlchemy
# - Defines engine, Base, SessionLocal
# - Responsible for schema creation
# - Works as foundation for higher-level services
# ==========================================================

import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from constants.paths import STORAGE_DIR

# =======================
# Config
# =======================
# Always resolve DB location from backend root, not from current working directory.
DB_PATH = os.path.join(STORAGE_DIR, "database", "core.db")
DB_URL = f"sqlite:///{DB_PATH}"

# Some services touch DB during import-time config reads.
# Ensure the DB directory exists before first connection attempt.
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# In the future you can switch to Postgres via ENV:
# DB_URL = os.getenv("DB_URL", f"sqlite:///{DB_PATH}")

# =======================
# Engine & Session
# =======================
engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()

# =======================
# Init schema
# =======================
def create_database():
    """Ensure DB directory exists and create schema if needed"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _ensure_history_runtime_meta_column()
    _ensure_users_auth_columns()
    _ensure_user_settings_active_character_column()


def _ensure_history_runtime_meta_column() -> None:
    """Backward-compatible migration for runtime metadata storage."""
    with engine.begin() as conn:
        table_info = conn.execute(text("PRAGMA table_info(history)")).fetchall()
        columns = {row[1] for row in table_info} if table_info else set()
        if "runtime_meta" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE history ADD COLUMN runtime_meta TEXT DEFAULT '{}'"
                )
            )


def _ensure_users_auth_columns() -> None:
    with engine.begin() as conn:
        table_info = conn.execute(text("PRAGMA table_info(users)")).fetchall()
        if not table_info:
            return

        columns = {row[1] for row in table_info}
        additions = [
            ("email", "TEXT"),
            ("login", "TEXT"),
            ("password_hash", "TEXT"),
            ("role", "TEXT DEFAULT 'anonymous'"),
            ("auth_provider", "TEXT DEFAULT 'local'"),
            ("is_active", "BOOLEAN DEFAULT 1"),
            ("last_login_at", "DATETIME"),
        ]
        for column_name, column_sql in additions:
            if column_name not in columns:
                conn.execute(
                    text(f"ALTER TABLE users ADD COLUMN {column_name} {column_sql}")
                )

        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email_unique "
                "ON users(email) WHERE email IS NOT NULL"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_login_unique "
                "ON users(login) WHERE login IS NOT NULL"
            )
        )


def _ensure_user_settings_active_character_column() -> None:
    with engine.begin() as conn:
        table_info = conn.execute(text("PRAGMA table_info(user_settings)")).fetchall()
        if not table_info:
            return

        columns = {row[1] for row in table_info}
        if "active_character_id" not in columns:
            conn.execute(
                text("ALTER TABLE user_settings ADD COLUMN active_character_id TEXT")
            )

        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_user_settings_active_character_id "
                "ON user_settings(active_character_id)"
            )
        )
