"""A day summary belongs to a character.

A summary was built from the active character's
messages but stored without a character; "already there" was checked by the date
alone, and memory read every character's summaries and pulled their messages by
id. A summary is now stored with its character and read only for it. Summaries
written before that are bound by their messages, or removed when the messages no
longer say whose day it was.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from models.models import Character, History, ShortTermMemory
from modules.database.core import Base
from modules.memory import service as memory_service
from modules.memory import short_term
from modules.memory.service import MemoryModule

_NOW = datetime.now(timezone.utc)
TODAY = datetime(_NOW.year, _NOW.month, _NOW.day, tzinfo=timezone.utc)


def _world(tmp_path, monkeypatch, name="core.db"):
    engine = create_engine(f"sqlite:///{tmp_path / name}")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(short_term, "engine", engine)
    monkeypatch.setattr(short_term, "SessionLocal", factory)
    monkeypatch.setattr(short_term, "log_audit_entry", lambda *args, **kwargs: None)
    with factory() as session:
        session.add_all(
            [
                Character(id="lim", name="Lim"),
                Character(id="kate", name="Kate"),
                History(id="l1", character_id="lim", role="user", content="кофе с утра", timestamp=TODAY + timedelta(hours=1)),
                History(id="k1", character_id="kate", role="user", content="прогулка", timestamp=TODAY + timedelta(hours=2)),
            ]
        )
        session.commit()
    return engine, factory


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine, factory = _world(tmp_path, monkeypatch)
    yield factory
    engine.dispose()


def _add_summary(factory, summary_id, character_id, dialogue_ids):
    with factory() as session:
        session.add(
            ShortTermMemory(
                id=summary_id,
                character_id=character_id,
                summary=f"{summary_id} day",
                dialogue_ids=json.dumps(dialogue_ids),
                created_at=TODAY,
            )
        )
        session.commit()


def test_a_summary_is_read_only_for_its_character(db):
    _add_summary(db, "st-lim", "lim", ["l1"])

    assert [record.id for record in short_term.load_recent_records(character_id="lim")] == ["st-lim"]
    assert short_term.load_recent_records(character_id="kate") == []


def test_one_characters_day_does_not_block_anothers(db, monkeypatch):
    monkeypatch.setattr(short_term, "_generate_day_summary", lambda transcript, day, **kwargs: (transcript, []))

    short_term.refresh_recent_days("lim", days=1)
    short_term.refresh_recent_days("kate", days=1)
    short_term.refresh_recent_days("lim", days=1)

    with db() as session:
        rows = [(row.character_id, json.loads(row.dialogue_ids)) for row in session.query(ShortTermMemory)]
    assert sorted(rows) == [("kate", ["k1"]), ("lim", ["l1"])]


def test_the_memory_stage_gives_kate_nothing_of_lims_day(db, monkeypatch):
    _add_summary(db, "st-lim", "lim", ["l1"])
    monkeypatch.setattr(
        memory_service,
        "find_matching_record",
        lambda embedding, records, threshold: records[0] if records else None,
    )
    module = MemoryModule.__new__(MemoryModule)

    result = module._search_short_term_memory(
        [1.0], {"threshold": 0.1}, {"lookback_days": 7}, character_id="kate"
    )

    assert result == (None, None, {})


def test_a_summary_never_brings_another_characters_message(db, monkeypatch):
    _add_summary(db, "st-kate", "kate", ["k1", "l1"])

    def rows_by_ids(ids):
        with db() as session:
            return session.query(History).filter(History.id.in_(list(ids))).all()

    seen = []
    monkeypatch.setattr(
        memory_service,
        "find_matching_record",
        lambda embedding, records, threshold: records[0] if records else None,
    )
    monkeypatch.setattr(memory_service.database_service, "get_history_by_ids", rows_by_ids)
    module = MemoryModule.__new__(MemoryModule)
    monkeypatch.setattr(module, "_prepare_history_payload", lambda row: {"id": row.id})
    monkeypatch.setattr(module, "_find_best_match", lambda payloads, *args, **kwargs: seen.extend(payloads))

    module._search_short_term_memory([1.0], {"threshold": 0.1}, {"lookback_days": 7}, character_id="kate")

    assert seen == [{"id": "k1"}]


def test_old_summaries_are_bound_by_their_messages_or_removed(tmp_path, monkeypatch):
    engine, _factory = _world(tmp_path, monkeypatch, name="legacy.db")
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE short_term_memory"))
        conn.execute(
            text(
                "CREATE TABLE short_term_memory (id TEXT PRIMARY KEY, summary TEXT NOT NULL, "
                "dialogue_ids TEXT NOT NULL, themes TEXT DEFAULT '[]', created_at DATETIME, "
                "updated_at DATETIME)"
            )
        )
        for summary_id, dialogue_ids in (
            ("lim-day", ["l1"]),
            ("kate-day-partly-gone", ["k1", "deleted-3"]),
            ("all-messages-gone", ["deleted-1", "deleted-2"]),
            ("empty-day", []),
            ("two-characters", ["l1", "k1"]),
        ):
            conn.execute(
                text("INSERT INTO short_term_memory (id, summary, dialogue_ids) VALUES (:id, 'day', :ids)"),
                {"id": summary_id, "ids": json.dumps(dialogue_ids)},
            )

    short_term.ensure_short_term_schema()
    short_term.ensure_short_term_schema()

    with engine.connect() as conn:
        rows = dict(conn.execute(text("SELECT id, character_id FROM short_term_memory")).fetchall())
    assert rows == {"lim-day": "lim", "kate-day-partly-gone": "kate"}
    engine.dispose()


def test_summaries_on_start_follow_only_the_setting(monkeypatch):
    """The setting is managed from the UI: no environment switch."""
    from constants.default_config import DEFAULT_CONFIG
    from core import initialize

    assert DEFAULT_CONFIG["memory"]["short_term"]["startup_refresh_enabled"] is False

    started = []

    class _Thread:
        def __init__(self, *args, name=None, **kwargs):
            self.name = name

        def start(self):
            started.append(self.name)

    settings = {"memory.short_term.startup_refresh_enabled": False}
    monkeypatch.setenv("STARTUP_SHORT_MEMORY_REFRESH", "1")
    monkeypatch.setattr(initialize, "get_config_value", lambda path, default=None: settings.get(path, default))
    monkeypatch.setattr(initialize, "log_audit_entry", lambda *args, **kwargs: None)
    monkeypatch.setattr(initialize.threading, "Thread", _Thread)

    initialize.start_async_warmups()
    assert started == []

    settings["memory.short_term.startup_refresh_enabled"] = True
    initialize.start_async_warmups()
    assert started == ["short-memory-startup-warmup"]
