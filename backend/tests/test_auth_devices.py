"""The devices signed in to the account, and signing them out.

The owner sees every live sign-in (not revoked, not expired) with its browser,
address and last activity, and can sign out one device or all the others; the
device that asks stays signed in. A signed-out device's access token stops
working at once.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import AuthSession, User
from modules.database.core import Base
from modules.system import auth
from routes import auth_routes

pytestmark = pytest.mark.regression


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, "SessionLocal", factory)
    monkeypatch.setattr(auth, "log_audit_entry", lambda *args, **kwargs: None)
    monkeypatch.setattr(auth, "_read_owner_security_settings", lambda: {})
    monkeypatch.setattr(auth, "_security_settings_cache", None)
    now = datetime.now(timezone.utc)
    live = now + timedelta(days=30)
    with factory() as session:
        session.add(User(uuid="owner", name="Owner", role="owner", is_active=True))
        session.add(User(uuid="someone", name="Someone", role="user", is_active=True))
        session.add_all(
            [
                AuthSession(id="this-device", user_uuid="owner", refresh_token_hash="a", user_agent="Chrome on Windows",
                            ip_address="10.0.0.1", expires_at=live, created_at=now - timedelta(hours=1)),
                AuthSession(id="phone", user_uuid="owner", refresh_token_hash="b", user_agent="Chrome on Android",
                            ip_address="10.0.0.2", expires_at=live, created_at=now - timedelta(minutes=10)),
                AuthSession(id="old", user_uuid="owner", refresh_token_hash="c", expires_at=live,
                            created_at=now - timedelta(days=2), revoked_at=now - timedelta(days=1)),
                AuthSession(id="expired", user_uuid="owner", refresh_token_hash="d",
                            expires_at=now - timedelta(minutes=1), created_at=now - timedelta(days=40)),
                AuthSession(id="their-device", user_uuid="someone", refresh_token_hash="e", expires_at=live,
                            created_at=now - timedelta(minutes=5)),
            ]
        )
        session.commit()
    yield factory
    engine.dispose()


def _revoked(factory) -> dict:
    with factory() as session:
        return {row.id: row.revoked_at is not None for row in session.query(AuthSession)}


def _token(session_id: str, user_uuid: str = "owner") -> str:
    token, _ = auth.create_access_token(SimpleNamespace(uuid=user_uuid, role="owner"), session_id)
    return token


def test_the_list_shows_live_sign_ins_newest_first(db):
    sessions = auth.list_active_sessions("owner")

    assert [item["id"] for item in sessions] == ["phone", "this-device"]
    assert sessions[0]["user_agent"] == "Chrome on Android"
    assert sessions[0]["ip_address"] == "10.0.0.2"
    assert sessions[0]["last_active_at"]


def test_signing_out_the_other_devices_keeps_this_one(db):
    this_token, phone_token = _token("this-device"), _token("phone")

    revoked = auth.revoke_other_sessions("owner", keep_session_id="this-device")

    assert revoked == 1
    assert _revoked(db) == {"this-device": False, "phone": True, "old": True, "expired": False, "their-device": False}
    assert auth.get_user_from_access_token(this_token).uuid == "owner"
    assert auth.get_user_from_access_token(phone_token) is None


def test_signing_out_one_device_leaves_the_rest(db):
    assert auth.revoke_session("owner", "phone") is True
    assert auth.revoke_session("owner", "phone") is False
    assert auth.revoke_session("owner", "their-device") is False
    assert auth.revoke_session("owner", "no-such-session") is False

    assert _revoked(db)["this-device"] is False
    assert _revoked(db)["their-device"] is False


def _as(monkeypatch, role: str, session_id: str = "this-device"):
    monkeypatch.setattr(
        auth_routes.auth_service, "get_user_from_access_token", lambda token: SimpleNamespace(uuid="owner", role=role)
    )
    monkeypatch.setattr(auth_routes.auth_service, "decode_access_token", lambda token: {"sid": session_id})


def test_the_route_marks_this_device(monkeypatch):
    _as(monkeypatch, "owner")
    monkeypatch.setattr(
        auth_routes.auth_service,
        "list_active_sessions",
        lambda user_uuid: [{"id": "phone"}, {"id": "this-device"}],
    )

    response = asyncio.run(auth_routes.list_my_sessions(authorization="Bearer token"))

    assert response["sessions"] == [{"id": "phone", "current": False}, {"id": "this-device", "current": True}]


@pytest.mark.parametrize("role", ["user", "anonymous"])
def test_only_the_owner_manages_the_devices(monkeypatch, role):
    _as(monkeypatch, role)
    touched = []
    monkeypatch.setattr(auth_routes.auth_service, "list_active_sessions", lambda *a, **k: touched.append(a))
    monkeypatch.setattr(auth_routes.auth_service, "revoke_other_sessions", lambda *a, **k: touched.append(a))
    monkeypatch.setattr(auth_routes.auth_service, "revoke_session", lambda *a, **k: touched.append(a))

    for call in (
        lambda: auth_routes.list_my_sessions(authorization="Bearer token"),
        lambda: auth_routes.revoke_my_other_sessions(authorization="Bearer token"),
        lambda: auth_routes.revoke_my_session("phone", authorization="Bearer token"),
    ):
        with pytest.raises(HTTPException) as refused:
            asyncio.run(call())
        assert refused.value.status_code == 403

    assert touched == []


def test_without_a_token_the_devices_are_not_shown():
    with pytest.raises(HTTPException) as refused:
        asyncio.run(auth_routes.list_my_sessions(authorization=None))

    assert refused.value.status_code == 401


def test_signing_out_the_others_keeps_the_session_that_asked(monkeypatch):
    _as(monkeypatch, "owner")
    calls = []
    monkeypatch.setattr(
        auth_routes.auth_service,
        "revoke_other_sessions",
        lambda user_uuid, keep_session_id=None: calls.append((user_uuid, keep_session_id)) or 2,
    )

    response = asyncio.run(auth_routes.revoke_my_other_sessions(authorization="Bearer token"))

    assert calls == [("owner", "this-device")]
    assert response == {"status": "ok", "revoked_sessions": 2}


def test_one_device_is_signed_out_but_not_the_one_that_asks(monkeypatch):
    _as(monkeypatch, "owner")
    revoked = []
    monkeypatch.setattr(
        auth_routes.auth_service,
        "revoke_session",
        lambda user_uuid, session_id: revoked.append(session_id) or session_id == "phone",
    )

    assert asyncio.run(auth_routes.revoke_my_session("phone", authorization="Bearer token")) == {"status": "ok"}
    with pytest.raises(HTTPException) as current:
        asyncio.run(auth_routes.revoke_my_session("this-device", authorization="Bearer token"))
    with pytest.raises(HTTPException) as unknown:
        asyncio.run(auth_routes.revoke_my_session("no-such-session", authorization="Bearer token"))

    assert current.value.status_code == 400
    assert unknown.value.status_code == 404
    assert revoked == ["phone", "no-such-session"]
