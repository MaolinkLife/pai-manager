"""A guest in the chat sees and hears nothing of the owner's.

Besides the owner, a registered user and an anonymous
guest may only write to PAI. They do not read the owner's history, do not get
the owner's system events over the WebSocket, and their replies are not voiced
on the owner's speakers. Who is asking is decided by the session token, never by
the payload.
"""

import asyncio
from types import SimpleNamespace

import pytest

from core.websocket_manager import ConnectionManager
from modules.generative import conversation
from routes import ws_routes

pytestmark = pytest.mark.regression


class FakeSocket:
    def __init__(self):
        self.accepted = False
        self.sent = []

    async def accept(self):
        self.accepted = True

    async def send_text(self, message):
        self.sent.append(message)


def test_system_events_reach_only_the_owners_sockets():
    manager = ConnectionManager()
    owner, guest = FakeSocket(), FakeSocket()

    async def scenario():
        await manager.connect(owner, owner=True)
        await manager.connect(guest)
        await manager.send_message('{"type": "voice_state"}')

    asyncio.run(scenario())

    assert owner.sent == ['{"type": "voice_state"}']
    assert guest.sent == []
    assert guest.accepted


def test_a_users_live_sockets_are_found_by_the_token_user_newest_first():
    manager = ConnectionManager()
    first, second, guest = FakeSocket(), FakeSocket(), FakeSocket()

    async def scenario():
        await manager.connect(first, owner=True, user_uuid="owner-uuid")
        await manager.connect(second, owner=True, user_uuid="owner-uuid")
        await manager.connect(guest)

    asyncio.run(scenario())

    assert manager.sockets_for_user("owner-uuid") == [second, first]
    assert manager.sockets_for_user(None) == []
    assert manager.sockets_for_user("") == []
    manager.disconnect(second)
    assert manager.sockets_for_user("owner-uuid") == [first]


def test_a_disconnected_owner_socket_is_forgotten():
    manager = ConnectionManager()
    owner = FakeSocket()

    async def scenario():
        await manager.connect(owner, owner=True)
        manager.disconnect(owner)
        await manager.send_message("event")

    asyncio.run(scenario())

    assert owner.sent == [] and not manager.is_owner(owner)


@pytest.mark.parametrize("session_user_uuid", [None, "user-uuid"])
def test_a_payload_cannot_name_another_user(session_user_uuid):
    data = ws_routes._bind_session_actor({"actor_user_uuid": "owner-uuid", "content": "hi"}, session_user_uuid)

    assert data["actor_user_uuid"] == session_user_uuid


@pytest.mark.parametrize("role", ["anonymous", "user"])
def test_a_guest_reads_no_history(monkeypatch, role):
    def history(*args, **kwargs):
        raise AssertionError("the shared history must not be read for a guest")

    monkeypatch.setattr(ws_routes, "_get_visible_main_chat_history", history)

    items = ws_routes._history_for_actor(
        SimpleNamespace(actor_role=role), "lim", limit=32, offset=0, include_all_sources=False
    )

    assert items == []


def test_the_owner_reads_the_shared_history(monkeypatch):
    monkeypatch.setattr(ws_routes, "_get_visible_main_chat_history", lambda *a, **k: [{"id": "m1"}])

    items = ws_routes._history_for_actor(
        SimpleNamespace(actor_role="owner"), "lim", limit=32, offset=0, include_all_sources=True
    )

    assert items == [{"id": "m1"}]


@pytest.mark.parametrize("speak, voiced", [(True, ["reply"]), (False, [])])
def test_only_the_owners_replies_are_voiced(monkeypatch, speak, voiced):
    spoken = []
    monkeypatch.setattr(
        conversation.decision_layer, "handle_response", lambda content, message_id=None: spoken.append(content)
    )

    conversation._speak_reply("reply", "m1", speak=speak)

    assert spoken == voiced
