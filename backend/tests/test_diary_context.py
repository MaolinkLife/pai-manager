"""Tests for §3.9-bis-retrieval — diary.recent tool block in the instructor.

Coverage:
  * disabled config → ''
  * empty diary → ''
  * narrative + self_reflection rendered, newest first, max_entries respected
  * per-entry truncation by max_chars_per_entry
  * summary fallback when narrative is missing
  * entries without body and reflection are skipped
  * list_daily_activity_entries raising → '' (never breaks a turn)
  * _build_dynamic_tool_messages includes diary.recent when content present
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from core.instructor import Instructor


@dataclass
class _Entry:
    day: str
    mood: str = "joy"
    summary: str = ""
    payload: dict = field(default_factory=dict)


class _Char:
    id = "diary-ctx-test-char"


@pytest.fixture()
def instructor() -> Instructor:
    return Instructor()


def _patch_env(monkeypatch, entries, config_overrides: dict | None = None):
    import core.instructor as instructor_mod
    import modules.memory.diary as diary_mod
    import modules.system.character as character_mod
    import modules.system.service as system_service_mod

    overrides = dict(config_overrides or {})

    def fake_get_config_value(key: str, default: Any = None):
        if key in overrides:
            return overrides[key]
        return default

    monkeypatch.setattr(
        instructor_mod.config_service, "get_config_value", fake_get_config_value
    )
    monkeypatch.setattr(
        diary_mod, "list_daily_activity_entries", lambda **kwargs: entries
    )
    monkeypatch.setattr(
        character_mod, "get_or_create_character", lambda name: _Char()
    )
    monkeypatch.setattr(
        system_service_mod, "get_active_character_name", lambda **kwargs: "T"
    )


def test_disabled_returns_empty(monkeypatch, instructor):
    _patch_env(
        monkeypatch,
        [_Entry(day="2026-06-09", payload={"narrative": "x"})],
        {"memory.diary.context.enabled": False},
    )
    assert instructor._build_diary_tool_content() == ""


def test_empty_diary_returns_empty(monkeypatch, instructor):
    _patch_env(monkeypatch, [])
    assert instructor._build_diary_tool_content() == ""


def test_narrative_and_reflection_rendered(monkeypatch, instructor):
    entries = [
        _Entry(
            day="2026-06-09",
            mood="peace",
            payload={
                "narrative": "Сегодня мы долго говорили про проект.",
                "self_reflection": "Я заметила, что тороплюсь с выводами.",
            },
        ),
        _Entry(day="2026-06-08", payload={"narrative": "Тихий день."}),
    ]
    _patch_env(monkeypatch, entries)
    content = instructor._build_diary_tool_content()
    assert "[2026-06-09] mood: peace" in content
    assert "долго говорили про проект" in content
    assert "Self-reflection: Я заметила" in content
    assert "[2026-06-08]" in content
    # Newest entry comes first.
    assert content.index("2026-06-09") < content.index("2026-06-08")


def test_max_entries_respected(monkeypatch, instructor):
    entries = [
        _Entry(day=f"2026-06-0{i}", payload={"narrative": f"day {i}"})
        for i in range(9, 4, -1)
    ]
    _patch_env(monkeypatch, entries, {"memory.diary.context.max_entries": 2})
    content = instructor._build_diary_tool_content()
    assert "[2026-06-09]" in content
    assert "[2026-06-08]" in content
    assert "[2026-06-07]" not in content


def test_truncation(monkeypatch, instructor):
    entries = [_Entry(day="2026-06-09", payload={"narrative": "а" * 2000})]
    _patch_env(
        monkeypatch, entries, {"memory.diary.context.max_chars_per_entry": 100}
    )
    content = instructor._build_diary_tool_content()
    assert "а" * 100 in content
    assert "а" * 101 not in content


def test_summary_fallback(monkeypatch, instructor):
    entries = [_Entry(day="2026-06-09", summary="Краткое резюме дня", payload={})]
    _patch_env(monkeypatch, entries)
    content = instructor._build_diary_tool_content()
    assert "Краткое резюме дня" in content


def test_blank_entries_skipped(monkeypatch, instructor):
    entries = [_Entry(day="2026-06-09", summary="", payload={})]
    _patch_env(monkeypatch, entries)
    assert instructor._build_diary_tool_content() == ""


def test_diary_error_never_raises(monkeypatch, instructor):
    import modules.memory.diary as diary_mod

    _patch_env(monkeypatch, [])

    def _boom(**kwargs):
        raise RuntimeError("db locked")

    monkeypatch.setattr(diary_mod, "list_daily_activity_entries", _boom)
    assert instructor._build_diary_tool_content() == ""


def test_dynamic_tool_messages_include_diary(monkeypatch, instructor):
    entries = [_Entry(day="2026-06-09", payload={"narrative": "контекст дня"})]
    _patch_env(monkeypatch, entries)
    messages = instructor._build_dynamic_tool_messages(user_message={"id": "m1"})
    diary_msgs = [m for m in messages if m.get("name") == "diary.recent"]
    assert len(diary_msgs) == 1
    assert "контекст дня" in diary_msgs[0]["content"]
