from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import Base, Character, History, TelegramMessage
from modules.telegram.sync import TelegramSyncMessage, TelegramSyncService


def _session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_telegram_sync_upserts_chat_user_and_message(monkeypatch):
    SessionLocal = _session_factory()
    monkeypatch.setattr("modules.telegram.sync.SessionLocal", SessionLocal)

    session = SessionLocal()
    try:
        character = Character(id="char-1", name="Lim", configs="{}")
        history = History(id="history-1", character_id="char-1", role="user", content="old")
        session.add_all([character, history])
        session.commit()
    finally:
        session.close()

    service = TelegramSyncService()
    row = service.upsert_message(
        TelegramSyncMessage(
            character_name="Lim",
            telegram_chat_id=123,
            telegram_message_id=77,
            chat_kind="private",
            chat_title="Owner",
            sender_telegram_user_id=42,
            sender_name="Alice",
            sender_username="alice",
            is_owner_chat=True,
            is_owner_sender=True,
            role="user",
            event="incoming_message",
            text="hello",
            message_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            history_id="history-1",
        )
    )

    assert row is not None

    session = SessionLocal()
    try:
        stored = session.query(TelegramMessage).one()
        history = session.query(History).filter_by(id="history-1").one()
        assert stored.telegram_chat_id == 123
        assert stored.telegram_message_id == 77
        assert stored.text == "hello"
        assert stored.chat.title == "Owner"
        assert stored.sender.display_name == "Alice"
        assert stored.sender.is_owner is True
        assert history.content == "hello"
    finally:
        session.close()


def test_telegram_sync_marks_deleted(monkeypatch):
    SessionLocal = _session_factory()
    monkeypatch.setattr("modules.telegram.sync.SessionLocal", SessionLocal)

    session = SessionLocal()
    try:
        character = Character(id="char-1", name="Lim", configs="{}")
        session.add(character)
        session.commit()
    finally:
        session.close()

    service = TelegramSyncService()
    service.upsert_message(
        TelegramSyncMessage(
            character_name="Lim",
            telegram_chat_id=123,
            telegram_message_id=77,
            role="user",
            event="incoming_message",
            text="hello",
        )
    )

    deleted = service.mark_deleted(
        character_name="Lim",
        telegram_chat_id=123,
        telegram_message_ids=[77],
    )

    session = SessionLocal()
    try:
        stored = session.query(TelegramMessage).one()
        assert deleted == 1
        assert stored.sync_state == "deleted"
        assert stored.deleted_at is not None
    finally:
        session.close()
