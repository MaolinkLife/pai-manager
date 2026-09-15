"""The chat WebSocket opens with a one-time pass, never with the access token in its address.

A browser cannot put the Authorization header on a WebSocket, and an address
ends up in every log that prints addresses — the dev server's and uvicorn's
among them. So the page asks for a pass over HTTP, where the token travels in
the header, and opens the socket with the pass: it works once, lives briefly
and names a user. A token in the address is refused.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from core import ws_tickets
from core.interaction import InteractionPolicy
from core.websocket_manager import ConnectionManager
from core.ws_tickets import WsPass, WsTicketStore
from modules.system import auth as auth_module
from routes import auth_routes, ws_routes

pytestmark = pytest.mark.regression


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_a_pass_names_its_user_and_sign_in_once():
    store = WsTicketStore()
    ticket = store.issue("owner-uuid", "sign-in-1")

    assert store.redeem(ticket) == WsPass(user_uuid="owner-uuid", sign_in_id="sign-in-1")
    assert store.redeem(ticket) is None


def test_a_pass_expires():
    clock = Clock()
    store = WsTicketStore(ttl_seconds=30, clock=clock)
    ticket = store.issue("owner-uuid", "sign-in-1")

    clock.now += 31

    assert store.redeem(ticket) is None


def test_passes_are_long_random_and_unguessable():
    store = WsTicketStore()

    tickets = {store.issue("owner-uuid", "sign-in-1") for _ in range(50)}

    assert len(tickets) == 50
    assert all(len(ticket) >= 40 for ticket in tickets)
    assert store.redeem("") is None
    assert store.redeem("not-a-pass") is None


def test_a_pass_is_given_only_for_a_valid_access_token(monkeypatch):
    store = WsTicketStore()
    monkeypatch.setattr(ws_tickets, "store", store)
    monkeypatch.setattr(
        auth_routes.auth_service,
        "get_user_from_access_token",
        lambda token: SimpleNamespace(uuid="owner-uuid") if token == "good" else None,
    )
    monkeypatch.setattr(auth_routes.auth_service, "decode_access_token", lambda token: {"sid": "row-1"})
    monkeypatch.setattr(auth_routes.auth_service, "sign_in_of_session", lambda session_id: "sign-in-1")

    with pytest.raises(HTTPException) as missing:
        asyncio.run(auth_routes.issue_ws_ticket(authorization=None))
    with pytest.raises(HTTPException) as stale:
        asyncio.run(auth_routes.issue_ws_ticket(authorization="Bearer stale"))
    response = asyncio.run(auth_routes.issue_ws_ticket(authorization="Bearer good"))

    assert missing.value.status_code == 401
    assert stale.value.status_code == 401
    assert response["expires_in"] == 30
    assert store.redeem(response["ticket"]).user_uuid == "owner-uuid"


@pytest.fixture
def client(monkeypatch):
    store = WsTicketStore()
    monkeypatch.setattr(ws_tickets, "store", store)
    monkeypatch.setattr(ws_routes, "manager", ConnectionManager())

    async def accept(websocket):
        return True

    monkeypatch.setattr(ws_routes.access_guard, "accept_ws", accept)
    # Even a valid token must not open the socket from the address.
    monkeypatch.setattr(auth_module, "get_user_from_access_token", lambda token: SimpleNamespace(uuid="owner-uuid"))
    monkeypatch.setattr(auth_module, "live_sign_ins", lambda sign_in_ids: set(sign_in_ids))

    def policy(user_uuid):
        role = "owner" if user_uuid == "owner-uuid" else "anonymous"
        return InteractionPolicy(
            actor_role=role,
            can_affect_moral=role == "owner",
            can_affect_global_memory=role == "owner",
        )

    monkeypatch.setattr(ws_routes, "resolve_interaction_policy", policy)
    monkeypatch.setattr(ws_routes, "log_audit_entry", lambda *args, **kwargs: None)
    monkeypatch.setattr(ws_routes, "get_active_character_name", lambda **kwargs: "lim")
    monkeypatch.setattr(ws_routes, "_get_visible_main_chat_history", lambda *args, **kwargs: [{"id": "m1"}])

    app = FastAPI()
    app.include_router(ws_routes.ws_router)
    with TestClient(app) as test_client:
        yield SimpleNamespace(http=test_client, store=store)


def history_seen(socket) -> list:
    socket.send_json({"action": "fetch_history", "payload": {}})
    return socket.receive_json()["items"]


def test_a_socket_opened_with_a_pass_belongs_to_its_user(client):
    ticket = client.store.issue("owner-uuid", "sign-in-1")

    with client.http.websocket_connect(f"/api/ws?ticket={ticket}") as socket:
        assert history_seen(socket) == [{"id": "m1"}]


def test_a_socket_without_a_pass_is_an_anonymous_guest(client):
    with client.http.websocket_connect("/api/ws") as socket:
        assert history_seen(socket) == []


def test_a_used_pass_does_not_open_the_socket(client):
    ticket = client.store.issue("owner-uuid", "sign-in-1")
    with client.http.websocket_connect(f"/api/ws?ticket={ticket}") as socket:
        history_seen(socket)

    with pytest.raises(WebSocketDisconnect) as closed:
        with client.http.websocket_connect(f"/api/ws?ticket={ticket}") as socket:
            socket.receive_json()

    assert closed.value.code == 4401


def test_an_access_token_in_the_address_is_refused(client):
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.http.websocket_connect("/api/ws?access_token=owner-token") as socket:
            socket.receive_json()

    assert closed.value.code == 4401
