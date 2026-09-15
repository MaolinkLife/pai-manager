"""How long a sign-in lasts is a setting of the owner account, not a hidden switch.

The access token lives minutes and is renewed quietly while the page is used;
a sign-in that is not renewed for refresh_ttl_days ends. A token issued longer
ago than the setting allows is refused even when its own expiry lies years
ahead, so lowering the setting ends old tokens at once.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from constants.default_config import DEFAULT_CONFIG
from models.config_model import SystemConfig
from modules.system import auth

pytestmark = pytest.mark.regression


@pytest.fixture
def security(monkeypatch):
    settings: dict = {}
    monkeypatch.setattr(auth, "_read_owner_security_settings", lambda: dict(settings))
    monkeypatch.setattr(auth, "_security_settings_cache", None)
    return settings


def _user():
    return SimpleNamespace(uuid="owner", role="owner")


def test_the_defaults_are_fifteen_minutes_and_thirty_days(security):
    model = SystemConfig().security

    assert auth._get_access_ttl_minutes() == 15
    assert auth._get_refresh_ttl_days() == 30
    assert DEFAULT_CONFIG["system"]["security"] == {"access_token_ttl_minutes": 15, "refresh_ttl_days": 30}
    assert (model.access_token_ttl_minutes, model.refresh_ttl_days) == (15, 30)


def test_an_access_token_lives_as_long_as_the_setting_says(security):
    security["access_token_ttl_minutes"] = 20
    before = datetime.now(timezone.utc)

    token, expires_at = auth.create_access_token(_user(), "session-1")

    assert timedelta(minutes=19) < expires_at - before <= timedelta(minutes=20, seconds=1)
    assert auth.decode_access_token(token)["sid"] == "session-1"


def test_a_sign_in_without_renewal_ends_after_the_setting(security):
    security["refresh_ttl_days"] = 7
    session = SimpleNamespace(add=lambda row: None, flush=lambda: None)

    _, row = auth._create_refresh_session(session, _user())

    left = row.expires_at - datetime.now(timezone.utc)
    assert timedelta(days=6, hours=23) < left <= timedelta(days=7)


@pytest.mark.parametrize("value, expected", [(0, 1), (-5, 1), (5000, 1440), ("abc", 15), (None, 15)])
def test_the_access_setting_is_kept_within_its_bounds(security, value, expected):
    security["access_token_ttl_minutes"] = value

    assert auth._get_access_ttl_minutes() == expected


@pytest.mark.parametrize("value, expected", [(0, 1), (1000, 365), ("x", 30)])
def test_the_sign_in_setting_is_kept_within_its_bounds(security, value, expected):
    security["refresh_ttl_days"] = value

    assert auth._get_refresh_ttl_days() == expected


def test_a_token_issued_longer_ago_than_the_setting_allows_is_refused(security):
    # A token from the old ten-year default: its own expiry is years ahead.
    now = int(time.time())
    token = auth._encode_access_token(
        {"sub": "owner", "sid": "s", "type": "access", "role": "owner", "iat": now - 3600, "exp": now + 10 * 365 * 24 * 3600}
    )

    with pytest.raises(ValueError, match="Token expired"):
        auth.decode_access_token(token)


def test_a_longer_setting_lets_the_same_token_through(security):
    security["access_token_ttl_minutes"] = 120
    now = int(time.time())
    token = auth._encode_access_token(
        {"sub": "owner", "sid": "s", "type": "access", "role": "owner", "iat": now - 3600, "exp": now + 3600}
    )

    assert auth.decode_access_token(token)["sub"] == "owner"


def test_a_token_without_an_issue_time_is_refused(security):
    now = int(time.time())
    token = auth._encode_access_token({"sub": "owner", "sid": "s", "type": "access", "exp": now + 600})

    with pytest.raises(ValueError):
        auth.decode_access_token(token)


def test_the_settings_come_from_the_owner_account_config(monkeypatch):
    from modules.system import config as config_service

    monkeypatch.setattr(
        config_service, "get_owner_default_config", lambda: {"system": {"security": {"access_token_ttl_minutes": 42}}}
    )
    monkeypatch.setattr(
        config_service, "get_config", lambda user_uuid=None: {"system": {"security": {"access_token_ttl_minutes": 999}}}
    )
    monkeypatch.setattr(auth, "_security_settings_cache", None)

    assert auth._get_access_ttl_minutes() == 42


def test_the_old_environment_variables_change_nothing(monkeypatch, security):
    monkeypatch.setenv("AUTH_ACCESS_TTL_MINUTES", str(60 * 24 * 365 * 10))
    monkeypatch.setenv("AUTH_REFRESH_TTL_DAYS", str(365 * 10))

    assert auth._get_access_ttl_minutes() == 15
    assert auth._get_refresh_ttl_days() == 30
