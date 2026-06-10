"""Tests for §3.9-quinquies Tasks/Reminders.

Coverage:
  Repository:
    * create + get round-trip, naive-UTC normalisation
    * list filters by status, list_due returns only pending+overdue
    * mark: fired sets fired_at, invalid status rejected
    * update: edit due_at revives cancelled rows
  Capture (maybe_capture_reminder):
    * disabled config → None
    * no gate keyword → None (no LLM call)
    * gate + extractor says not a reminder → None
    * gate + valid extraction → row created, ack returned
    * extractor returns past due → None
    * never raises on garbage / LLM failure
  Firing (fire_due_reminders):
    * disabled → noop
    * due rows get fired exactly once; delivery failure → status=failed
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from modules.database.core import engine, _ensure_user_reminders_table
from modules.reminders import fire_due_reminders, maybe_capture_reminder
from modules.reminders.repository import RemindersRepository
from modules.reminders import service as reminders_service

_TEST_CHAR_PREFIX = "reminders-test-"


@pytest.fixture(autouse=True)
def _cleanup():
    _ensure_user_reminders_table()
    yield
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM user_reminders WHERE character_id LIKE :pat"),
            {"pat": f"{_TEST_CHAR_PREFIX}%"},
        )


def _repo() -> RemindersRepository:
    return RemindersRepository()


def _char(suffix: str = "a") -> str:
    return f"{_TEST_CHAR_PREFIX}{suffix}"


def _in(minutes: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


def test_create_and_get_roundtrip():
    repo = _repo()
    row = repo.create(
        character_id=_char(),
        text="позвонить маме",
        due_at=_in(30),
        meta={"timezone": "Europe/Moscow"},
    )
    assert row["status"] == "pending"
    assert row["text"] == "позвонить маме"
    fetched = repo.get(row["id"])
    assert fetched is not None
    assert fetched["meta"]["timezone"] == "Europe/Moscow"
    # naive-UTC stored; serialised with Z suffix
    assert fetched["due_at"].endswith("Z")


def test_list_filters_by_status():
    repo = _repo()
    a = repo.create(character_id=_char(), text="a", due_at=_in(5))
    repo.create(character_id=_char(), text="b", due_at=_in(10))
    repo.mark(a["id"], status="cancelled")

    pending = repo.list(character_id=_char(), status="pending")
    assert pending["total"] == 1
    assert pending["items"][0]["text"] == "b"

    everything = repo.list(character_id=_char())
    assert everything["total"] == 2


def test_list_due_only_pending_overdue():
    repo = _repo()
    overdue = repo.create(character_id=_char(), text="due", due_at=_in(-5))
    repo.create(character_id=_char(), text="future", due_at=_in(60))
    cancelled = repo.create(character_id=_char(), text="cancelled", due_at=_in(-10))
    repo.mark(cancelled["id"], status="cancelled")

    due = repo.list_due()
    due_ids = {r["id"] for r in due}
    assert overdue["id"] in due_ids
    assert cancelled["id"] not in due_ids
    assert all(r["status"] == "pending" for r in due)


def test_mark_fired_sets_fired_at_and_rejects_invalid():
    repo = _repo()
    row = repo.create(character_id=_char(), text="x", due_at=_in(-1))
    fired = repo.mark(row["id"], status="fired")
    assert fired["status"] == "fired"
    assert fired["fired_at"] is not None
    assert repo.mark(row["id"], status="nonsense") is None


def test_update_due_revives_cancelled():
    repo = _repo()
    row = repo.create(character_id=_char(), text="x", due_at=_in(5))
    repo.mark(row["id"], status="cancelled")
    revived = repo.update(row["id"], due_at=_in(15))
    assert revived["status"] == "pending"


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


class _StubResult:
    def __init__(self, content: str):
        self.content = content


def _patch_llm(monkeypatch, payload: str):
    class _StubManager:
        def generate(self, request):
            return _StubResult(payload)

    import modules.generative.manager as gm

    monkeypatch.setattr(gm, "generation_manager", _StubManager())


def _patch_language(monkeypatch):
    import modules.system.user as user_mod

    monkeypatch.setattr(
        user_mod, "resolve_user_language", lambda **kwargs: "ru-RU"
    )


def test_capture_disabled(monkeypatch):
    from modules.system import config as config_service

    monkeypatch.setattr(
        config_service,
        "get_config_value",
        lambda key, default=None: False if key == "reminders.enabled" else default,
    )
    result = maybe_capture_reminder(
        {"content": "напомни через час"}, character_id=_char(), character_name="T"
    )
    assert result is None


def test_capture_no_gate_keyword():
    result = maybe_capture_reminder(
        {"content": "как дела? расскажи про погоду"},
        character_id=_char(),
        character_name="T",
    )
    assert result is None


def test_capture_extractor_says_no(monkeypatch):
    _patch_llm(monkeypatch, '{"is_reminder": false, "text": "", "due_at_local": ""}')
    _patch_language(monkeypatch)
    result = maybe_capture_reminder(
        {"content": "помнишь, я просил напомнить тебе вчера?"},
        character_id=_char(),
        character_name="T",
    )
    assert result is None


def test_capture_valid(monkeypatch):
    due_local = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime(
        "%Y-%m-%dT%H:%M"
    )
    _patch_llm(
        monkeypatch,
        f'{{"is_reminder": true, "text": "выключить духовку", '
        f'"due_at_local": "{due_local}", "recurrence": "none"}}',
    )
    _patch_language(monkeypatch)
    ack = maybe_capture_reminder(
        {"content": "напомни мне выключить духовку через 2 часа", "id": "msg-1"},
        character_id=_char(),
        character_name="T",
    )
    assert ack is not None
    assert ack["text"] == "выключить духовку"
    stored = _repo().list(character_id=_char(), status="pending")
    assert stored["total"] == 1
    assert stored["items"][0]["source_message_id"] == "msg-1"


def test_capture_past_due_rejected(monkeypatch):
    past_local = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime(
        "%Y-%m-%dT%H:%M"
    )
    _patch_llm(
        monkeypatch,
        f'{{"is_reminder": true, "text": "x", "due_at_local": "{past_local}"}}',
    )
    _patch_language(monkeypatch)
    ack = maybe_capture_reminder(
        {"content": "разбуди меня"}, character_id=_char(), character_name="T"
    )
    assert ack is None
    assert _repo().list(character_id=_char())["total"] == 0


def test_capture_never_raises_on_llm_failure(monkeypatch):
    class _Broken:
        def generate(self, request):
            raise RuntimeError("provider down")

    import modules.generative.manager as gm

    monkeypatch.setattr(gm, "generation_manager", _Broken())
    _patch_language(monkeypatch)
    ack = maybe_capture_reminder(
        {"content": "напомни мне про встречу завтра в 10"},
        character_id=_char(),
        character_name="T",
    )
    assert ack is None


# ---------------------------------------------------------------------------
# Firing
# ---------------------------------------------------------------------------


def test_fire_disabled(monkeypatch):
    from modules.system import config as config_service

    monkeypatch.setattr(
        config_service,
        "get_config_value",
        lambda key, default=None: False if key == "reminders.enabled" else default,
    )
    _repo().create(character_id=_char(), text="x", due_at=_in(-1))
    summary = fire_due_reminders()
    assert summary == {"fired": 0, "failed": 0}


def test_fire_due_marks_fired_once(monkeypatch):
    repo = _repo()
    row = repo.create(character_id=_char(), text="x", due_at=_in(-1))

    delivered = []
    monkeypatch.setattr(
        reminders_service,
        "_deliver_main_chat",
        lambda reminder: delivered.append(reminder["id"]) or True,
    )
    summary = fire_due_reminders()
    assert summary["fired"] >= 1
    assert row["id"] in delivered
    assert repo.get(row["id"])["status"] == "fired"

    # Second pass: nothing due anymore.
    delivered.clear()
    fire_due_reminders()
    assert row["id"] not in delivered


def test_fire_delivery_failure_marks_failed(monkeypatch):
    repo = _repo()
    row = repo.create(character_id=_char(), text="x", due_at=_in(-1))

    def _boom(reminder):
        raise RuntimeError("ws down")

    monkeypatch.setattr(reminders_service, "_deliver_main_chat", _boom)
    summary = fire_due_reminders()
    assert summary["failed"] >= 1
    refreshed = repo.get(row["id"])
    assert refreshed["status"] == "failed"
    assert "ws down" in str(refreshed["meta"].get("delivery_error"))
