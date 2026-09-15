"""A signed-out device loses its open chat too.

Signing a device out revokes its sign-in, so its access token stops working;
the chat socket it already holds closes as well. A sign-in keeps one id through
every quiet renewal, so renewing the access key never closes the chat.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from starlette.websockets import WebSocketDisconnect

from core import websocket_manager, ws_tickets
from core.interaction import InteractionPolicy
from core.websocket_manager import ConnectionManager
from core.ws_tickets import WsPass, WsTicketStore
from models.models import User
from modules.database import core as database_core
from modules.database.core import Base
from modules.system import auth
from routes import auth_routes, ws_routes

pytestmark = pytest.mark.regression

PASSWORD = "old-password-1"


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, "SessionLocal", factory)
    monkeypatch.setattr(auth, "log_audit_entry", lambda *args, **kwargs: None)
    monkeypatch.setattr(auth, "_read_owner_security_settings", lambda: {})
    monkeypatch.setattr(auth, "_security_settings_cache", None)
    with factory() as session:
        session.add(
            User(uuid="owner", name="Owner", role="owner", is_active=True, password_hash=auth.hash_password(PASSWORD))
        )
        session.commit()
    yield factory
    engine.dispose()


def _sign_in(factory) -> tuple[str, str, str]:
    with factory() as session:
        user = session.query(User).filter(User.uuid == "owner").first()
        refresh_token, row = auth._create_refresh_session(session, user)
        session.commit()
        return refresh_token, row.id, row.sign_in_id


def test_a_sign_in_keeps_its_id_through_renewals(db):
    refresh_token, row_id, sign_in_id = _sign_in(db)

    renewed = auth.refresh_tokens(refresh_token=refresh_token)
    again = auth.refresh_tokens(refresh_token=renewed.refresh_token)

    assert sign_in_id == row_id
    assert again.session_id not in (row_id, renewed.session_id)
    assert auth.sign_in_of_session(again.session_id) == sign_in_id
    assert auth.live_sign_ins({sign_in_id, "unknown"}) == {sign_in_id}


@pytest.mark.parametrize("sign_out", ["logout", "one device", "other devices", "password change"])
def test_every_way_of_signing_out_ends_the_sign_in(db, sign_out):
    phone_refresh, _, phone_sign_in = _sign_in(db)
    _, this_row, this_sign_in = _sign_in(db)
    # The phone renewed its access key once since it signed in.
    renewed = auth.refresh_tokens(refresh_token=phone_refresh)

    if sign_out == "logout":
        auth.logout(renewed.refresh_token)
    elif sign_out == "one device":
        auth.revoke_session("owner", renewed.session_id)
    elif sign_out == "other devices":
        auth.revoke_other_sessions("owner", keep_session_id=this_row)
    else:
        auth.change_password("owner", current_password=PASSWORD, new_password="new-password-2", keep_session_id=this_row)

    assert auth.live_sign_ins({phone_sign_in, this_sign_in}) == {this_sign_in}


def test_sign_ins_stored_before_the_column_existed_get_their_own_id(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE auth_sessions (id TEXT PRIMARY KEY, user_uuid TEXT NOT NULL, "
                "refresh_token_hash TEXT NOT NULL, expires_at DATETIME NOT NULL, revoked_at DATETIME)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO auth_sessions (id, user_uuid, refresh_token_hash, expires_at) "
                "VALUES ('old-row', 'owner', 'hash', '2099-01-01 00:00:00')"
            )
        )
    monkeypatch.setattr(database_core, "engine", engine)

    database_core._ensure_auth_sessions_sign_in_column()
    # The check runs on every start.
    database_core._ensure_auth_sessions_sign_in_column()

    with engine.begin() as conn:
        assert conn.execute(text("SELECT sign_in_id FROM auth_sessions WHERE id = 'old-row'")).scalar() == "old-row"
    engine.dispose()


def test_the_pass_names_the_sign_in_of_the_token(monkeypatch):
    store = WsTicketStore()
    monkeypatch.setattr(ws_tickets, "store", store)
    monkeypatch.setattr(auth, "get_user_from_access_token", lambda token: SimpleNamespace(uuid="owner-uuid"))
    monkeypatch.setattr(auth, "decode_access_token", lambda token: {"sid": "renewed-row"})
    monkeypatch.setattr(auth, "sign_in_of_session", lambda session_id: "sign-in-1" if session_id == "renewed-row" else None)

    response = asyncio.run(auth_routes.issue_ws_ticket(authorization="Bearer token"))

    assert store.redeem(response["ticket"]) == WsPass(user_uuid="owner-uuid", sign_in_id="sign-in-1")


@pytest.fixture
def chat(monkeypatch):
    store = WsTicketStore()
    manager = ConnectionManager()
    ended: set[str] = set()
    monkeypatch.setattr(ws_tickets, "store", store)
    monkeypatch.setattr(ws_routes, "manager", manager)
    monkeypatch.setattr(websocket_manager, "manager", manager)

    async def accept(websocket):
        return True

    monkeypatch.setattr(ws_routes.access_guard, "accept_ws", accept)

    def policy(user_uuid):
        role = "owner" if user_uuid else "anonymous"
        return InteractionPolicy(actor_role=role, can_affect_moral=role == "owner", can_affect_global_memory=role == "owner")

    monkeypatch.setattr(ws_routes, "resolve_interaction_policy", policy)
    monkeypatch.setattr(ws_routes, "log_audit_entry", lambda *args, **kwargs: None)
    monkeypatch.setattr(ws_routes, "get_active_character_name", lambda **kwargs: "lim")
    monkeypatch.setattr(ws_routes, "_get_visible_main_chat_history", lambda *args, **kwargs: [{"id": "m1"}])
    monkeypatch.setattr(auth, "live_sign_ins", lambda sign_in_ids: set(sign_in_ids) - ended)

    # The owner asks from this device; every way of signing out ends the phone's sign-in.
    def end_the_phone(*args, **kwargs):
        ended.add("phone")
        return 1

    monkeypatch.setattr(auth, "get_user_from_access_token", lambda token: SimpleNamespace(uuid="owner-uuid", role="owner"))
    monkeypatch.setattr(auth, "decode_access_token", lambda token: {"sid": "this-device-row"})
    monkeypatch.setattr(auth, "revoke_session", lambda user_uuid, session_id: end_the_phone() == 1)
    monkeypatch.setattr(auth, "revoke_other_sessions", end_the_phone)
    monkeypatch.setattr(auth, "change_password", end_the_phone)
    monkeypatch.setattr(auth, "logout", lambda refresh_token: end_the_phone() == 1)

    def retired_token_came_back(**kwargs):
        end_the_phone()
        raise auth.RefreshTokenReused("Refresh token was already used")

    monkeypatch.setattr(auth, "refresh_tokens", retired_token_came_back)

    app = FastAPI()
    app.include_router(ws_routes.ws_router)
    app.include_router(auth_routes.router)
    with TestClient(app) as client:
        yield SimpleNamespace(http=client, store=store, ended=ended)


def history_seen(socket) -> list:
    socket.send_json({"action": "fetch_history", "payload": {}})
    return socket.receive_json()["items"]


SIGN_OUTS = {
    "one device": ("/api/auth/me/sessions/phone-row/revoke", {}, 200),
    "other devices": ("/api/auth/me/sessions/revoke-others", {}, 200),
    "password change": ("/api/auth/me/password", {"current_password": PASSWORD, "new_password": "new-password-2"}, 200),
    "logout": ("/api/auth/logout", {"refresh_token": "phone-refresh-token"}, 200),
    # A copied renewal token came back: the sign-in ends and its chat closes.
    "retired renewal token": ("/api/auth/refresh", {"refresh_token": "phone-refresh-token"}, 401),
}


@pytest.mark.parametrize("sign_out", list(SIGN_OUTS))
def test_signing_out_a_device_closes_its_open_chat(chat, sign_out):
    path, body, expected_status = SIGN_OUTS[sign_out]
    phone = chat.http.websocket_connect(f"/api/ws?ticket={chat.store.issue('owner-uuid', 'phone')}")
    here = chat.http.websocket_connect(f"/api/ws?ticket={chat.store.issue('owner-uuid', 'this-device')}")
    guest = chat.http.websocket_connect("/api/ws")

    with phone as phone_socket, here as here_socket, guest as guest_socket:
        assert history_seen(phone_socket) == [{"id": "m1"}]

        response = chat.http.post(path, json=body, headers={"Authorization": "Bearer token"})

        assert response.status_code == expected_status
        with pytest.raises(WebSocketDisconnect) as closed:
            phone_socket.receive_json()
        assert closed.value.code == 4401
        assert history_seen(here_socket) == [{"id": "m1"}]
        assert history_seen(guest_socket) == []


def test_a_pass_of_an_ended_sign_in_does_not_open_the_socket(chat):
    ticket = chat.store.issue("owner-uuid", "phone")
    chat.ended.add("phone")

    with pytest.raises(WebSocketDisconnect) as closed:
        with chat.http.websocket_connect(f"/api/ws?ticket={ticket}") as socket:
            socket.receive_json()

    assert closed.value.code == 4401
