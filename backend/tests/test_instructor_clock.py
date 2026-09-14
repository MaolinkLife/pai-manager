"""Instructor clock: the "include date and time" switch and the owner's timezone.

The prompt is the whole scope sent to the model; the
clock goes as a role: tool block, and the instructor switch decides whether it
enters the scope. The switch existed in the settings but nothing read it.
"""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import instructor as instructor_module
from core.instructor import Instructor
from models.models import Character, User, UserSettings
from modules.database.core import Base
from modules.system import user as user_module


def _use_config(monkeypatch, **overrides):
    values = {
        "decision_layer.instructor.include_datetime": True,
        "memory.diary.context.enabled": False,
        **overrides,
    }

    def fake_get_config_value(path, default=None, user_uuid=None):
        return values.get(path, default)

    monkeypatch.setattr(instructor_module.config_service, "get_config_value", fake_get_config_value)


def _clock_lines(content):
    return dict(line.split(": ", 1) for line in content.splitlines() if ": " in line)


def _seconds_apart(shown, expected):
    shown_seconds = sum(int(part) * unit for part, unit in zip(shown.split(":"), (3600, 60, 1)))
    expected_seconds = expected.hour * 3600 + expected.minute * 60 + expected.second
    apart = abs(shown_seconds - expected_seconds) % 86400
    return min(apart, 86400 - apart)


def _tool_names(messages):
    return [message.get("name") for message in messages if message.get("role") == "tool"]


def _format(instructor):
    return asyncio.run(
        instructor.format_for_api(
            system_prompt="persona",
            user_message={"id": "u1", "content": "hello", "history": []},
        )
    )


def test_switched_off_clock_is_not_in_the_scope(monkeypatch):
    _use_config(monkeypatch, **{"decision_layer.instructor.include_datetime": False})
    monkeypatch.setattr(user_module, "resolve_owner_timezone", lambda: "Europe/Moscow")
    instructor = Instructor()

    assert instructor._build_environment_tool_content() == ""
    assert "system.clock" not in _tool_names(_format(instructor))


@pytest.mark.parametrize("zone_name", ["Pacific/Kiritimati", "Etc/GMT+12"])
def test_clock_shows_the_owner_time(monkeypatch, zone_name):
    _use_config(monkeypatch)
    monkeypatch.setattr(user_module, "resolve_owner_timezone", lambda: zone_name)
    instructor = Instructor()

    messages = _format(instructor)
    clock = next(message for message in messages if message.get("name") == "system.clock")
    lines = _clock_lines(clock["content"])

    assert lines["Timezone"] == zone_name
    assert _seconds_apart(lines["Time"], datetime.now(ZoneInfo(zone_name))) < 120


def test_clock_falls_back_to_the_server_time(monkeypatch):
    _use_config(monkeypatch)
    monkeypatch.setattr(user_module, "resolve_owner_timezone", lambda: None)

    lines = _clock_lines(Instructor()._build_environment_tool_content())

    assert _seconds_apart(lines["Time"], datetime.now().astimezone()) < 120
    assert lines["Timezone"]


@pytest.fixture
def users_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'users.db'}")
    Base.metadata.create_all(
        bind=engine,
        tables=[Character.__table__, User.__table__, UserSettings.__table__],
    )
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(user_module, "SessionLocal", session_factory)
    yield session_factory
    engine.dispose()


def _add_user(session_factory, *, role, zone_name, is_active=True):
    with session_factory() as session:
        user = User(name=role, role=role, is_active=is_active)
        session.add(user)
        session.flush()
        session.add(UserSettings(user_uuid=user.uuid, timezone_name=zone_name))
        session.commit()


def test_owner_timezone_is_the_owner_one(users_db):
    _add_user(users_db, role="user", zone_name="Asia/Tokyo")
    _add_user(users_db, role="owner", zone_name="Europe/Moscow")

    assert user_module.resolve_owner_timezone() == "Europe/Moscow"


def test_owner_timezone_is_unknown_without_an_owner_or_a_valid_zone(users_db):
    _add_user(users_db, role="user", zone_name="Asia/Tokyo")
    assert user_module.resolve_owner_timezone() is None

    _add_user(users_db, role="owner", zone_name="Mars/Olympus_Mons")
    assert user_module.resolve_owner_timezone() is None
