"""A human message is kept from the moment it arrives until it is in the history.

The main chat writes a new message to the turn queue before the message waits
for the model. The turn stores it in the history as before; when the turn ends,
however it ends, a message the turn never stored is stored from the queue, then
the row goes and the outcome is logged. Rows left by a restart are handled at
the next start, and nothing answers them automatically.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import QueuedTurn
from modules.database.core import Base
from modules.generative import turn_queue
from modules.memory import history as history_service
from modules.system.logger import AuditStatus

pytestmark = pytest.mark.regression

PICTURE = {"data": "aGk=", "mimeType": "image/png", "name": "cat.png", "category": "image"}


@pytest.fixture
def queue(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'queue.db'}")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    state = SimpleNamespace(history={}, stored=[], audit=[], vault=[], fail_store=False, factory=factory)

    def add_message_to_history(**kwargs):
        if state.fail_store:
            raise RuntimeError("database is locked")
        state.stored.append(kwargs)
        state.history[kwargs["message_id"]] = SimpleNamespace(id=kwargs["message_id"])
        return state.history[kwargs["message_id"]]

    monkeypatch.setattr(turn_queue, "SessionLocal", factory)
    monkeypatch.setattr(turn_queue.database_service, "get_message_by_id", lambda message_id: state.history.get(message_id))
    monkeypatch.setattr(turn_queue.database_service, "add_message_to_history", add_message_to_history)
    monkeypatch.setattr(turn_queue, "get_active_character_name", lambda default=None: "Lim")
    monkeypatch.setattr(
        turn_queue,
        "log_audit_entry",
        lambda *args, **kwargs: state.audit.append((args[0], args[2], kwargs.get("details") or {})),
    )
    monkeypatch.setattr(turn_queue, "write_vault_entry", lambda **kwargs: state.vault.append(kwargs))
    yield state
    engine.dispose()


def _rows(state) -> list:
    with state.factory() as session:
        return session.query(QueuedTurn).all()


def _finished(state) -> list:
    return [(details.get("status"), level) for event, level, details in state.audit if event == "turn_queue_finished"]


def test_a_new_message_is_kept_the_moment_it_arrives(queue):
    turn_id, history_message_id = turn_queue.accept({"content": "привет", "media": [PICTURE]}, run_id="run-1")

    [row] = _rows(queue)
    assert row.id == turn_id
    assert row.history_message_id == history_message_id
    assert (row.run_id, row.channel, row.character_name, row.content) == ("run-1", "main_chat", "Lim", "привет")
    assert json.loads(row.media)[0]["data"] == "aGk="
    assert queue.stored == []


def test_a_turn_that_stored_its_message_just_leaves(queue):
    turn_id, history_message_id = turn_queue.accept({"content": "привет"}, run_id="run-1")
    # The turn stored the message itself, with its tags and image descriptions.
    queue.history[history_message_id] = SimpleNamespace(id=history_message_id)

    turn_queue.finish(turn_id, turn_queue.COMPLETED)

    assert _rows(queue) == []
    assert queue.stored == []
    assert _finished(queue) == [("completed", AuditStatus.SUCCESS)]
    assert queue.vault == []


def test_a_failed_turn_stores_the_message_it_never_got_to(queue):
    turn_id, history_message_id = turn_queue.accept({"content": "привет котик", "media": [PICTURE]}, run_id="run-1")

    turn_queue.finish(turn_id, turn_queue.FAILED, error="Ollama did not answer")

    [stored] = queue.stored
    assert stored["message_id"] == history_message_id
    assert (stored["role"], stored["content"], stored["character_name"]) == ("user", "привет котик", "Lim")
    assert stored["media"][0]["name"] == "cat.png"
    assert "котик" in stored["tags"]
    assert stored["timestamp"] is not None
    assert _rows(queue) == []
    assert _finished(queue) == [("failed", AuditStatus.ERROR)]
    assert [(entry["kind"], entry["output"]) for entry in queue.vault] == [("turn_failed", "Ollama did not answer")]


def test_a_stopped_turn_keeps_the_message(queue):
    turn_id, _ = turn_queue.accept({"content": "подожди"}, run_id="run-1")

    turn_queue.finish(turn_id, turn_queue.STOPPED)

    assert [stored["content"] for stored in queue.stored] == ["подожди"]
    assert _rows(queue) == []
    assert _finished(queue) == [("stopped", AuditStatus.INFO)]
    assert queue.vault == []


def test_turns_left_by_a_restart_are_kept_and_recorded_as_interrupted(queue):
    turn_queue.accept({"content": "первое"}, run_id="run-1")
    turn_queue.accept({"content": "второе"}, run_id="run-2")

    assert turn_queue.recover_interrupted() == 2

    assert sorted(stored["content"] for stored in queue.stored) == ["второе", "первое"]
    assert _rows(queue) == []
    assert _finished(queue) == [("interrupted", AuditStatus.WARNING)] * 2
    assert [entry["kind"] for entry in queue.vault] == ["turn_interrupted"] * 2


def test_a_message_that_cannot_be_stored_keeps_its_row(queue):
    turn_id, _ = turn_queue.accept({"content": "привет"}, run_id="run-1")
    queue.fail_store = True

    turn_queue.finish(turn_id, turn_queue.FAILED, error="boom")

    assert len(_rows(queue)) == 1
    assert _finished(queue) == []
    assert "turn_queue_store_failed" in [event for event, _, _ in queue.audit]


def test_the_history_row_takes_the_id_the_queue_gave(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'history.db'}")
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(history_service, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(history_service, "log_audit_entry", lambda *args, **kwargs: None)

    entry = history_service.add_history("char-1", "user", "привет", message_id="hist-1")

    assert entry.id == "hist-1"
    engine.dispose()
