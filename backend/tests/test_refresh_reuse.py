"""A retired refresh token that comes back is treated as stolen.

Every renewal retires the refresh token it used. Two tabs renewing at the same
moment present the same token twice, so a repeat within a short window is only
refused. Later on the token can only have been copied: the whole sign-in ends,
every renewal of it included, so whoever holds any of its tokens is signed out.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import AuthSession, User
from modules.database.core import Base
from modules.system import auth
from modules.system.logger import AuditStatus

pytestmark = pytest.mark.regression


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    audit: list = []
    monkeypatch.setattr(auth, "SessionLocal", factory)
    monkeypatch.setattr(auth, "log_audit_entry", lambda *args, **kwargs: audit.append(args[:3]))
    monkeypatch.setattr(auth, "_read_owner_security_settings", lambda: {})
    monkeypatch.setattr(auth, "_security_settings_cache", None)
    with factory() as session:
        session.add(User(uuid="owner", name="Owner", role="owner", is_active=True))
        session.commit()
    yield SimpleNamespace(factory=factory, audit=audit)
    engine.dispose()


def _sign_in(factory) -> tuple[str, str]:
    with factory() as session:
        user = session.query(User).filter(User.uuid == "owner").first()
        refresh_token, row = auth._create_refresh_session(session, user)
        session.commit()
        return refresh_token, row.sign_in_id


def _retired_seconds_ago(factory, refresh_token: str, seconds: int) -> None:
    """Move the moment the token was retired back in time."""
    with factory() as session:
        row = (
            session.query(AuthSession)
            .filter(AuthSession.refresh_token_hash == auth._hash_refresh_token(refresh_token))
            .first()
        )
        row.revoked_at = auth._as_utc(row.revoked_at) - timedelta(seconds=seconds)
        session.commit()


def test_two_tabs_renewing_at_once_only_get_a_refusal(db):
    old_token, sign_in_id = _sign_in(db.factory)
    renewed = auth.refresh_tokens(refresh_token=old_token)

    with pytest.raises(ValueError) as refused:
        auth.refresh_tokens(refresh_token=old_token)

    assert not isinstance(refused.value, auth.RefreshTokenReused)
    assert auth.live_sign_ins({sign_in_id}) == {sign_in_id}
    assert auth.refresh_tokens(refresh_token=renewed.refresh_token).session_id


def test_a_retired_token_that_comes_back_later_ends_the_whole_sign_in(db):
    old_token, sign_in_id = _sign_in(db.factory)
    _, other_sign_in = _sign_in(db.factory)
    renewed = auth.refresh_tokens(refresh_token=old_token)
    _retired_seconds_ago(db.factory, old_token, auth.REFRESH_REUSE_GRACE_SECONDS + 1)

    with pytest.raises(auth.RefreshTokenReused):
        auth.refresh_tokens(refresh_token=old_token)

    assert auth.live_sign_ins({sign_in_id, other_sign_in}) == {other_sign_in}
    with pytest.raises(ValueError):
        auth.refresh_tokens(refresh_token=renewed.refresh_token)
    assert auth.get_user_from_access_token(renewed.access_token) is None
    assert ("auth_refresh_reuse_detected", AuditStatus.WARNING) in [(event, level) for event, _, level in db.audit]


def test_a_token_of_a_signed_out_device_is_only_refused(db):
    token, _ = _sign_in(db.factory)
    auth.logout(token)
    _retired_seconds_ago(db.factory, token, 3600)

    with pytest.raises(ValueError) as refused:
        auth.refresh_tokens(refresh_token=token)

    assert not isinstance(refused.value, auth.RefreshTokenReused)
