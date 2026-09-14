"""A sent message gets its real id in the chat; a reroll never stores it twice.

After a reroll the user message was in the database
and in the chat twice. The chat draws a sent message at once under a temporary
id; the server never told it the real id, and the reroll looked the message up by
the temporary one, did not find it and stored it again.
"""

import asyncio
from types import SimpleNamespace

import pytest

from modules.generative import conversation


@pytest.fixture
def db(monkeypatch):
    state = {"rows": {}, "added": []}

    def get_message_by_id(message_id):
        return state["rows"].get(message_id)

    def add_message_to_history(**kwargs):
        row = SimpleNamespace(id=f"db-{len(state['added']) + 1}", media_payload=[], **kwargs)
        state["added"].append(kwargs)
        state["rows"][row.id] = row
        return row

    monkeypatch.setattr(conversation.database_service, "get_message_by_id", get_message_by_id)
    monkeypatch.setattr(conversation.database_service, "add_message_to_history", add_message_to_history)
    monkeypatch.setattr(conversation, "get_active_character_name", lambda default=None: "Lim")
    return state


def _store(message, *, store=True):
    return conversation._store_user_message_once(
        message, store=store, content=message.get("content", ""), media=None, tags=[]
    )


def test_a_new_message_is_stored_once(db):
    row = _store({"id": "temp-1", "content": "привет"})

    assert row is not None
    assert len(db["added"]) == 1
    assert _store({"id": row.id, "content": "привет"}) is None
    assert len(db["added"]) == 1


def test_a_reroll_never_stores_the_user_message(db):
    rerolled = {
        "id": "db-user-7",
        "client_message_id": "temp-1",
        "content": "привет",
        "reroll_target_message_id": "db-assistant-8",
    }

    assert _store(rerolled) is None
    assert db["added"] == []


def test_nothing_is_stored_without_store(db):
    assert _store({"id": "temp-1", "content": "привет"}, store=False) is None
    assert db["added"] == []


def _confirm(message, *, client_message_id, stored_entry=None, emit=True):
    sent = []

    async def emit_fn(payload):
        sent.append(payload)
        return True

    asyncio.run(
        conversation._confirm_user_message_id(
            message,
            client_message_id=client_message_id,
            stored_entry=stored_entry,
            emit_fn=emit_fn if emit else None,
            with_run=lambda payload: {**payload, "run_id": "run-1"},
        )
    )
    return sent


def test_the_chat_learns_the_real_id_after_storing():
    message = {"id": "temp-1"}
    row = SimpleNamespace(id="db-user-7", media_payload=[{"id": "m1"}])

    sent = _confirm(message, client_message_id="temp-1", stored_entry=row)

    assert sent == [
        {"type": "ack_message", "tempId": "temp-1", "realId": "db-user-7", "media": [{"id": "m1"}], "run_id": "run-1"}
    ]
    # The echo and everything after it use the real id.
    assert message["id"] == "db-user-7"


def test_a_reroll_tells_the_chat_the_real_id_of_its_bubble():
    message = {"id": "db-user-7", "client_message_id": "temp-1", "reroll_target_message_id": "db-assistant-8"}

    sent = _confirm(message, client_message_id="temp-1")

    assert [(payload["tempId"], payload["realId"]) for payload in sent] == [("temp-1", "db-user-7")]
    assert message["id"] == "db-user-7"


def test_no_ack_when_the_chat_already_has_the_real_id():
    assert _confirm({"id": "db-user-7"}, client_message_id="db-user-7") == []
    # A guest's message is not stored: its id stays the chat's own.
    guest = {"id": "temp-9"}
    assert _confirm(guest, client_message_id="temp-9") == []
    assert guest["id"] == "temp-9"
