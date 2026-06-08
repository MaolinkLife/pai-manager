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


def _log_console(message: str, details: dict | None = None) -> None:
    prefix = "[Database]"
    if details:
        payload = ", ".join(f"{key}={value}" for key, value in details.items())
        print(f"{prefix} {message} | {payload}", flush=True)
        return
    print(f"{prefix} {message}", flush=True)


def create_database():
    db_exists = os.path.exists(DB_PATH)
    if db_exists:
        _log_console("База данных найдена, проверяю схему.", {"path": DB_PATH})
    else:
        _log_console("Создаем базу данных.", {"path": DB_PATH})

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _log_console("Синхронизируем базу данных.")
    _ensure_conversation_state_logs_table()
    _ensure_daily_activity_diary_table()
    _ensure_history_runtime_meta_column()
    _ensure_history_variant_columns()
    _ensure_telegram_sync_tables()
    _ensure_users_auth_columns()
    _ensure_user_settings_active_character_column()
    _ensure_emotional_trace_decay_columns()
    _ensure_forgiveness_events_table()
    _ensure_audit_logs_table()
    _ensure_debug_vault_table()
    _log_console("Схема базы данных готова.")


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


def _ensure_history_variant_columns() -> None:
    with engine.begin() as conn:
        table_info = conn.execute(text("PRAGMA table_info(history)")).fetchall()
        columns = {row[1] for row in table_info} if table_info else set()
        additions = [
            ("parent_message_id", "TEXT"),
            ("variant_group_id", "TEXT"),
            ("variant_index", "INTEGER DEFAULT 1"),
            ("active_variant", "BOOLEAN DEFAULT 1"),
        ]
        for column_name, column_sql in additions:
            if column_name not in columns:
                conn.execute(text(f"ALTER TABLE history ADD COLUMN {column_name} {column_sql}"))

        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_history_parent_message_id "
                "ON history(parent_message_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_history_variant_group_id "
                "ON history(variant_group_id)"
            )
        )


def _ensure_telegram_sync_tables() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS telegram_chats (
                    id TEXT PRIMARY KEY,
                    telegram_chat_id INTEGER NOT NULL UNIQUE,
                    chat_kind TEXT NOT NULL DEFAULT 'unknown',
                    title TEXT,
                    username TEXT,
                    is_owner_chat BOOLEAN DEFAULT 0,
                    last_synced_message_id INTEGER,
                    last_synced_at DATETIME,
                    meta TEXT DEFAULT '{}',
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS telegram_users (
                    id TEXT PRIMARY KEY,
                    telegram_user_id INTEGER NOT NULL UNIQUE,
                    telegram_user_uuid TEXT NOT NULL UNIQUE,
                    username TEXT,
                    display_name TEXT,
                    is_owner BOOLEAN DEFAULT 0,
                    trust_level INTEGER DEFAULT 0,
                    last_seen_at DATETIME,
                    meta TEXT DEFAULT '{}',
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS telegram_messages (
                    id TEXT PRIMARY KEY,
                    history_id TEXT,
                    character_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    sender_user_id TEXT,
                    telegram_chat_id INTEGER NOT NULL,
                    telegram_message_id INTEGER NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    event TEXT NOT NULL DEFAULT 'incoming_message',
                    text TEXT NOT NULL DEFAULT '',
                    message_date DATETIME,
                    edit_date DATETIME,
                    deleted_at DATETIME,
                    sync_state TEXT NOT NULL DEFAULT 'active',
                    meta TEXT DEFAULT '{}',
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS telegram_sync_jobs (
                    id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    character_id TEXT,
                    telegram_chat_id INTEGER,
                    cursor_message_id INTEGER,
                    payload TEXT DEFAULT '{}',
                    error TEXT,
                    created_at DATETIME,
                    started_at DATETIME,
                    completed_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_chats_telegram_chat_id ON telegram_chats(telegram_chat_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_users_telegram_user_id ON telegram_users(telegram_user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_users_telegram_user_uuid ON telegram_users(telegram_user_uuid)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_messages_history_id ON telegram_messages(history_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_messages_character_id ON telegram_messages(character_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_messages_chat_id ON telegram_messages(chat_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_messages_sender_user_id ON telegram_messages(sender_user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_messages_telegram_chat_id ON telegram_messages(telegram_chat_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_messages_telegram_message_id ON telegram_messages(telegram_message_id)"))
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_telegram_messages_unique_projection "
                "ON telegram_messages(character_id, telegram_chat_id, telegram_message_id, role, event)"
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_sync_jobs_job_type ON telegram_sync_jobs(job_type)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_sync_jobs_status ON telegram_sync_jobs(status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_sync_jobs_character_id ON telegram_sync_jobs(character_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_sync_jobs_telegram_chat_id ON telegram_sync_jobs(telegram_chat_id)"))


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


def _ensure_debug_vault_table() -> None:
    """Curated anomalies — Validator failures, judge skips, factual flags."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS debug_vault_entries (
                    id TEXT PRIMARY KEY,
                    character_id TEXT,
                    kind TEXT NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'warning',
                    summary TEXT NOT NULL DEFAULT '',
                    context TEXT DEFAULT '{}',
                    output TEXT DEFAULT '',
                    violations TEXT DEFAULT '[]',
                    runtime_meta TEXT DEFAULT '{}',
                    reviewed BOOLEAN DEFAULT 0,
                    reviewed_at DATETIME,
                    reviewed_note TEXT,
                    created_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_debug_vault_kind_created "
                "ON debug_vault_entries(kind, created_at)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_debug_vault_reviewed_created "
                "ON debug_vault_entries(reviewed, created_at)"
            )
        )


def _ensure_audit_logs_table() -> None:
    """Replaces backend/logs/*_debug.jsonl as the canonical audit log store.

    The JSONL files remain as a boot-window fallback (see logger._jsonl_dual_write)
    but UI reads and retention now go through this table.
    """
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'info',
                    msg TEXT NOT NULL DEFAULT '',
                    details TEXT DEFAULT '{}',
                    meta TEXT DEFAULT '{}',
                    language TEXT,
                    message_key TEXT,
                    created_at DATETIME
                )
                """
            )
        )
        # Filters used by the UI page (severity + time range) and by the
        # retention worker (severity + created_at).
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_audit_logs_severity_created "
                "ON audit_logs(severity, created_at)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_audit_logs_session_created "
                "ON audit_logs(session_id, created_at)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_audit_logs_event_type_created "
                "ON audit_logs(event_type, created_at)"
            )
        )


def _ensure_forgiveness_events_table() -> None:
    """Records of compensating actions that softened a specific EmotionalTrace.

    SQLAlchemy create_all builds the table on fresh DBs; this ensures it also
    exists on databases migrated from earlier schema, plus the index used by
    the per-trace forgiveness aggregation query.
    """
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS forgiveness_events (
                    id TEXT PRIMARY KEY,
                    character_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    cause TEXT,
                    compensating_action TEXT,
                    delta_intensity FLOAT DEFAULT 0.0,
                    triggered_resolve BOOLEAN DEFAULT 0,
                    created_at DATETIME
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_forgiveness_events_trace_id "
                "ON forgiveness_events(trace_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_forgiveness_events_character_created "
                "ON forgiveness_events(character_id, created_at)"
            )
        )


def _ensure_emotional_trace_decay_columns() -> None:
    """Add the decay-related columns to emotional_traces for the 0.8.0 cycle.

    Backfills existing rows with sensible defaults so the nightly decay job
    doesn't crash on legacy data. ``last_decayed_at`` stays NULL — the worker
    treats NULL as "decay from created_at".
    """
    with engine.begin() as conn:
        table_info = conn.execute(text("PRAGMA table_info(emotional_traces)")).fetchall()
        if not table_info:
            return

        columns = {row[1] for row in table_info}
        additions = [
            ("decay_rate", "FLOAT DEFAULT 0.05"),
            ("persistence_floor", "FLOAT DEFAULT 0.0"),
            ("resolved", "BOOLEAN DEFAULT 0"),
            ("last_decayed_at", "DATETIME"),
        ]
        for column_name, column_sql in additions:
            if column_name not in columns:
                conn.execute(
                    text(f"ALTER TABLE emotional_traces ADD COLUMN {column_name} {column_sql}")
                )

        # Composite index for the nightly worker scan.
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_emotional_traces_decay_scan "
                "ON emotional_traces(character_id, resolved, last_decayed_at)"
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
