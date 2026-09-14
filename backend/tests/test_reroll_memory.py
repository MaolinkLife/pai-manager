"""An answer replaced by a reroll is not memory.

After a reroll the model answered "I already said
that". The rerolled-away answer stays the active variant until the new one is
stored, so the rerolling turn found it in memory; the day summary, the diary,
"continue" and the memory emulator read every variant. The table keeps the
variants for the variant switcher only.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import Character, History
from modules.database.core import Base
from modules.memory import diary as diary_module
from modules.memory import emulator as emulator_module
from modules.memory import service as memory_service
from modules.memory import short_term as short_term_module
from modules.memory.emulator import MemorySearchEmulator
from modules.memory.history import (
    build_history_up_to_assistant_message,
    build_history_up_to_user_message,
)
from modules.memory.service import MemoryModule

REROLL = {
    "id": "u1",
    "content": "как дела?",
    "reroll_target_message_id": "a2",
    "variant_group_id": "u1",
}


def _conversation_rows():
    return [
        {"id": "u0", "role": "user", "content": "привет"},
        {"id": "a0", "role": "assistant", "content": "привет!", "variant_group_id": "u0"},
        {"id": "u1", "role": "user", "content": "как дела?"},
        {"id": "a1", "role": "assistant", "content": "ранний вариант", "variant_group_id": "u1"},
        {"id": "a2", "role": "assistant", "content": "отвергаемый ответ", "variant_group_id": "u1"},
    ]


# ---------------------------------------------------------------------------
# The rerolling turn
# ---------------------------------------------------------------------------


def test_a_reroll_scope_names_the_replaced_answer():
    assert MemoryModule._resolve_message_scope(REROLL) == {
        "channel": "main_chat",
        "replaced_answer_id": "a2",
        "replaced_answer_group": "u1",
    }
    assert MemoryModule._resolve_message_scope({"id": "u1", "content": "hi"}) == {"channel": "main_chat"}


def test_the_replaced_answer_and_its_variants_are_left_out():
    scope = MemoryModule._resolve_message_scope(REROLL)

    kept = [row["id"] for row in MemoryModule._apply_scope_filter(_conversation_rows(), scope)]

    assert kept == ["u0", "a0", "u1"]


def test_without_a_reroll_nothing_is_left_out():
    kept = MemoryModule._apply_scope_filter(_conversation_rows(), {"channel": "main_chat"})

    assert [row["id"] for row in kept] == ["u0", "a0", "u1", "a1", "a2"]


def test_memory_search_candidates_of_a_reroll_skip_the_replaced_answer(monkeypatch):
    monkeypatch.setattr(
        memory_service.database_service,
        "get_history",
        lambda name, limit=20, offset=0: list(reversed(_conversation_rows())),
    )
    module = MemoryModule.__new__(MemoryModule)

    payloads = module._load_recent_messages(
        "Lim", 32, scope=MemoryModule._resolve_message_scope(REROLL)
    )

    assert [payload["id"] for payload in payloads] == ["u0", "a0", "u1"]


# ---------------------------------------------------------------------------
# Everything else that reads the conversation: only the chosen variant
# ---------------------------------------------------------------------------


DAY = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def chat_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'chat.db'}")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(Character(id="char", name="Lim"))
        session.add_all(
            [
                History(id="u1", character_id="char", role="user", content="как дела?", timestamp=DAY),
                History(
                    id="a1",
                    character_id="char",
                    role="assistant",
                    content="отвергнутый ответ",
                    timestamp=DAY + timedelta(seconds=10),
                    variant_group_id="u1",
                    variant_index=1,
                    active_variant=False,
                ),
                History(
                    id="a2",
                    character_id="char",
                    role="assistant",
                    content="выбранный ответ",
                    timestamp=DAY + timedelta(seconds=60),
                    variant_group_id="u1",
                    variant_index=2,
                    active_variant=True,
                ),
                History(
                    id="u2",
                    character_id="char",
                    role="user",
                    content="понятно",
                    timestamp=DAY + timedelta(seconds=120),
                ),
            ]
        )
        session.commit()
    yield factory
    engine.dispose()


def test_the_day_summary_reads_only_the_chosen_answer(chat_db):
    with chat_db() as session:
        rows = short_term_module._load_day_history(session, "char", DAY - timedelta(hours=10), DAY + timedelta(hours=14))

    assert [row.id for row in rows] == ["u1", "a2", "u2"]


def test_the_diary_reads_only_the_chosen_answer(chat_db, monkeypatch):
    monkeypatch.setattr(diary_module, "SessionLocal", chat_db)

    rows = diary_module._load_day_rows(character_id="char", day=date(2026, 9, 12))

    assert [row.id for row in rows] == ["u1", "a2", "u2"]


def test_continue_and_reroll_history_skip_the_rejected_answer(chat_db):
    with chat_db() as session:
        next_user = session.get(History, "u2")
        chosen = session.get(History, "a2")
        up_to_user = build_history_up_to_user_message(session, "char", next_user)
        up_to_answer = build_history_up_to_assistant_message(session, "char", chosen)

    assert [item["content"] for item in up_to_user] == ["как дела?", "выбранный ответ", "понятно"]
    assert [item["id"] for item in up_to_answer] == ["u1", "a2"]


def test_the_memory_emulator_shows_only_the_chosen_answer(chat_db, monkeypatch):
    monkeypatch.setattr(emulator_module, "SessionLocal", chat_db)
    emulator = MemorySearchEmulator.__new__(MemorySearchEmulator)

    day_rows = emulator._load_day_messages("char", DAY - timedelta(hours=10))
    by_ids = emulator._load_messages_by_ids("char", ["a1", "a2"])

    assert [row["id"] for row in day_rows] == ["u1", "a2", "u2"]
    assert [row["id"] for row in by_ids] == ["a2"]
