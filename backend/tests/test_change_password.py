"""Changing the password from inside a signed-in session.

Owner only for now (`user` accounts get it when
guests are wired in); after the change every other session of the owner is
signed out, the one that made the change stays.
"""

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

OLD = "old-password-1"
NEW = "new-password-2"


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, "SessionLocal", factory)
    monkeypatch.setattr(auth, "log_audit_entry", lambda *args, **kwargs: None)
    expires = datetime.now(timezone.utc) + timedelta(days=1)
    with factory() as session:
        session.add(User(uuid="owner", name="Owner", role="owner", password_hash=auth.hash_password(OLD), is_active=True))
        session.add_all(
            [
                AuthSession(id="this-device", user_uuid="owner", refresh_token_hash="a", expires_at=expires),
                AuthSession(id="phone", user_uuid="owner", refresh_token_hash="b", expires_at=expires),
            ]
        )
        session.commit()
    yield factory
    engine.dispose()


def _state(factory):
    with factory() as session:
        user = session.get(User, "owner")
        revoked = {row.id: row.revoked_at is not None for row in session.query(AuthSession)}
        return user.password_hash, revoked


def test_a_wrong_current_password_changes_nothing(db):
    with pytest.raises(ValueError):
        auth.change_password("owner", current_password="not-it-123", new_password=NEW, keep_session_id="this-device")

    password_hash, revoked = _state(db)
    assert auth.verify_password(OLD, password_hash)
    assert revoked == {"this-device": False, "phone": False}


def test_a_short_new_password_is_refused(db):
    with pytest.raises(ValueError):
        auth.change_password("owner", current_password=OLD, new_password="short", keep_session_id="this-device")

    password_hash, _revoked = _state(db)
    assert auth.verify_password(OLD, password_hash)


def test_the_new_password_works_and_other_sessions_are_signed_out(db):
    revoked_count = auth.change_password("owner", current_password=OLD, new_password=NEW, keep_session_id="this-device")

    password_hash, revoked = _state(db)
    assert revoked_count == 1
    assert auth.verify_password(NEW, password_hash)
    assert not auth.verify_password(OLD, password_hash)
    assert revoked == {"this-device": False, "phone": True}


def test_a_signed_out_device_can_no_longer_use_its_access_token(db):
    with db() as session:
        user = session.get(User, "owner")
        phone_token, _ = auth.create_access_token(user, "phone")
        this_token, _ = auth.create_access_token(user, "this-device")
    assert auth.get_user_from_access_token(phone_token).uuid == "owner"

    auth.change_password("owner", current_password=OLD, new_password=NEW, keep_session_id="this-device")

    assert auth.get_user_from_access_token(phone_token) is None
    assert auth.get_user_from_access_token(this_token).uuid == "owner"


def test_an_access_token_of_an_unknown_session_is_refused(db):
    with db() as session:
        user = session.get(User, "owner")
        token, _ = auth.create_access_token(user, "no-such-session")

    assert auth.get_user_from_access_token(token) is None


def _call_route(monkeypatch, role, change):
    monkeypatch.setattr(
        auth_routes.auth_service,
        "get_user_from_access_token",
        lambda token: SimpleNamespace(uuid="someone", role=role),
    )
    monkeypatch.setattr(auth_routes.auth_service, "decode_access_token", lambda token: {"sid": "this-device"})
    monkeypatch.setattr(auth_routes.auth_service, "change_password", change)
    payload = auth_routes.ChangePasswordRequest(current_password=OLD, new_password=NEW)
    return asyncio.run(auth_routes.change_my_password(payload, authorization="Bearer token"))


@pytest.mark.parametrize("role", ["user", "anonymous"])
def test_only_the_owner_changes_the_password_here(monkeypatch, role):
    touched = []

    with pytest.raises(HTTPException) as refused:
        _call_route(monkeypatch, role, lambda *args, **kwargs: touched.append(kwargs))

    assert refused.value.status_code == 403
    assert touched == []


def test_the_route_keeps_the_session_that_asked(monkeypatch):
    calls = []

    def change(user_uuid, **kwargs):
        calls.append((user_uuid, kwargs))
        return 1

    assert _call_route(monkeypatch, "owner", change) == {"status": "ok", "revoked_sessions": 1}
    assert calls == [("someone", {"current_password": OLD, "new_password": NEW, "keep_session_id": "this-device"})]


def test_a_wrong_current_password_is_a_plain_refusal(monkeypatch):
    def change(*args, **kwargs):
        raise ValueError("The current password is wrong")

    with pytest.raises(HTTPException) as refused:
        _call_route(monkeypatch, "owner", change)

    assert refused.value.status_code == 400
    assert refused.value.detail == "The current password is wrong"
