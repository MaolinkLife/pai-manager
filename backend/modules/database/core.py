import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from constants.paths import STORAGE_DIR

DB_PATH = os.path.join(STORAGE_DIR, "database", "core.db")
DB_URL = f"sqlite:///{DB_PATH}"

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


def create_database():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _ensure_conversation_state_logs_table()
    _ensure_daily_activity_diary_table()
    _ensure_history_runtime_meta_column()
    _ensure_users_auth_columns()
    _ensure_user_settings_active_character_column()


def _ensure_conversation_state_logs_table() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS conversation_state_logs (
                    id TEXT PRIMARY KEY,
                    character_id TEXT,
                    message_id TEXT,
                    source TEXT NOT NULL DEFAULT 'memory_module',
                    last_message_at DATETIME,
                    hours_since_last_message REAL,
                    inactivity_bucket TEXT NOT NULL DEFAULT 'unknown',
                    last_topic TEXT NOT NULL DEFAULT '',
                    recent_tone_summary TEXT NOT NULL DEFAULT 'neutral',
                    payload TEXT DEFAULT '{}',
                    created_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_conversation_state_logs_created_at "
                "ON conversation_state_logs(created_at)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_conversation_state_logs_message_id "
                "ON conversation_state_logs(message_id)"
            )
        )


def _ensure_history_runtime_meta_column() -> None:
    with engine.begin() as conn:
        table_info = conn.execute(text("PRAGMA table_info(history)")).fetchall()
        columns = {row[1] for row in table_info} if table_info else set()
        if "runtime_meta" not in columns:
            conn.execute(text("ALTER TABLE history ADD COLUMN runtime_meta TEXT DEFAULT '{}'"))


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
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} {column_sql}"))

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
            conn.execute(text("ALTER TABLE user_settings ADD COLUMN active_character_id TEXT"))

        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_user_settings_active_character_id "
                "ON user_settings(active_character_id)"
            )
        )


def _ensure_daily_activity_diary_table() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS daily_activity_diary (
                    id TEXT PRIMARY KEY,
                    character_id TEXT NOT NULL,
                    day DATE NOT NULL,
                    mood TEXT NOT NULL DEFAULT 'neutral',
                    summary TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '[]',
                    stats TEXT NOT NULL DEFAULT '{}',
                    payload TEXT NOT NULL DEFAULT '{}',
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_daily_activity_diary_character_day "
                "ON daily_activity_diary(character_id, day)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_daily_activity_diary_day "
                "ON daily_activity_diary(day)"
            )
        )
