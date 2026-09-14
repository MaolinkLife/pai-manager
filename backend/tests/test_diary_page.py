"""Diary screen: every entry of the active character, page by page.

The screen asked for the last 30 days only, so older entries in the table never
reached it. Runs on a throwaway SQLite file, never on
the live database.
"""

import asyncio
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from modules.database import core as database_core
from modules.memory import diary as diary_module
from routes import memory_routes

CHARACTER = "char-diary"


@pytest.fixture
def diary_db(tmp_path, monkeypatch):
    test_engine = create_engine(f"sqlite:///{tmp_path / 'diary.db'}")
    monkeypatch.setattr(database_core, "engine", test_engine)
    monkeypatch.setattr(diary_module, "engine", test_engine)
    database_core._ensure_daily_activity_diary_table()
    yield
    test_engine.dispose()


def _add(days_ago, *, character_id=CHARACTER, pruned=None):
    diary_module._upsert_diary_entry(
        character_id=character_id,
        day=date.today() - timedelta(days=days_ago),
        mood="neutral",
        summary=f"day -{days_ago}",
        tags=[],
        stats={},
        payload={"pruned": pruned} if pruned else {},
    )


def _summaries(page):
    return [entry.summary for entry in page["entries"]]


def test_older_entries_come_newest_first(diary_db):
    for days_ago in (45, 1, 400):
        _add(days_ago)

    page = diary_module.list_diary_page(character_id=CHARACTER)

    assert _summaries(page) == ["day -1", "day -45", "day -400"]
    assert page["total"] == 3
    assert page["has_more"] is False


def test_pages_cover_every_entry_without_gaps_or_repeats(diary_db):
    for days_ago in range(65):
        _add(days_ago)

    pages = [
        diary_module.list_diary_page(character_id=CHARACTER, limit=30, offset=offset)
        for offset in (0, 30, 60)
    ]

    assert [len(page["entries"]) for page in pages] == [30, 30, 5]
    assert [page["has_more"] for page in pages] == [True, True, False]
    assert sum((_summaries(page) for page in pages), []) == [f"day -{n}" for n in range(65)]


def test_hidden_entries_come_only_when_asked(diary_db):
    _add(1)
    _add(2, pruned={"reason": "low_importance", "score": 0.1})
    _add(3, pruned={"reason": "superseded_by", "by_entry_id": "x"})

    shown = diary_module.list_diary_page(character_id=CHARACTER)
    with_hidden = diary_module.list_diary_page(character_id=CHARACTER, include_hidden=True)

    assert _summaries(shown) == ["day -1"]
    assert shown["total"] == 1
    assert _summaries(with_hidden) == ["day -1", "day -2", "day -3"]
    assert [entry.payload.get("pruned", {}).get("reason") for entry in with_hidden["entries"]] == [
        None,
        "low_importance",
        "superseded_by",
    ]


def test_other_characters_are_not_on_the_page(diary_db):
    _add(1)
    _add(1, character_id="someone-else")

    page = diary_module.list_diary_page(character_id=CHARACTER)

    assert _summaries(page) == ["day -1"]
    assert page["total"] == 1


def test_route_gives_the_active_character_page(diary_db, monkeypatch):
    for days_ago in (1, 45, 120):
        _add(days_ago)
    _add(2, pruned={"reason": "low_importance"})
    monkeypatch.setattr(memory_routes, "_require_owner_memory_access", lambda request: "owner-uuid")
    monkeypatch.setattr(
        memory_routes, "get_active_character_name", lambda user_uuid=None, default=None: "Lim"
    )
    monkeypatch.setattr(
        memory_routes.character_service,
        "get_or_create_character",
        lambda name: SimpleNamespace(id=CHARACTER),
    )

    first = asyncio.run(
        memory_routes.list_diary_entries(request=None, limit=2, offset=0, include_hidden=False)
    )
    rest = asyncio.run(
        memory_routes.list_diary_entries(request=None, limit=2, offset=2, include_hidden=False)
    )
    hidden = asyncio.run(
        memory_routes.list_diary_entries(request=None, limit=10, offset=0, include_hidden=True)
    )

    assert [entry["summary"] for entry in first["entries"]] == ["day -1", "day -45"]
    assert first["total"] == 3 and first["has_more"] is True
    assert [entry["summary"] for entry in rest["entries"]] == ["day -120"]
    assert rest["has_more"] is False
    assert hidden["total"] == 4
    assert hidden["entries"][1]["payload"]["pruned"]["reason"] == "low_importance"
