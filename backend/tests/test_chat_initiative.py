"""Блок C — chat initiative: gating, persist/broadcast, selfie scheduling."""

import pytest

from modules.initiative import service as initiative_service


class _Row:
    id = "msg-initiative-1"


@pytest.fixture
def _wired(monkeypatch):
    """Wire the happy path with fakes; tests flip individual pieces."""
    calls = {
        "persisted": [],
        "broadcast": [],
        "selfie": [],
    }

    monkeypatch.setattr(
        initiative_service,
        "_settings",
        lambda: {"enabled": True, "selfie_enabled": True, "selfie_chance": 1.0},
    )
    monkeypatch.setattr(
        initiative_service,
        "_compose_initiative_text",
        lambda emotion, character_name: "Эй, ты куда пропал?",
    )

    import modules.database.service as database_service
    import modules.system.service as system_service

    monkeypatch.setattr(
        system_service, "get_active_character_name", lambda default=None: "TestChar"
    )

    def fake_add(**kwargs):
        calls["persisted"].append(kwargs)
        return _Row()

    monkeypatch.setattr(database_service, "add_message_to_history", fake_add)
    monkeypatch.setattr(
        initiative_service, "_broadcast_ws", lambda payload: calls["broadcast"].append(payload) or True
    )
    monkeypatch.setattr(
        initiative_service, "_schedule_selfie", lambda mid, text: calls["selfie"].append(mid)
    )
    return calls


def test_initiative_persists_and_broadcasts(_wired):
    message_id = initiative_service.run_chat_initiative("беспокойство")
    assert message_id == "msg-initiative-1"
    assert len(_wired["persisted"]) == 1
    persisted = _wired["persisted"][0]
    assert persisted["role"] == "assistant"
    assert "initiative" in persisted["tags"]
    assert persisted["runtime_meta"]["emotion"] == "беспокойство"
    assert _wired["broadcast"][0]["source"] == "initiative"


def test_selfie_scheduled_when_chance_hits(_wired):
    initiative_service.run_chat_initiative("беспокойство")
    assert _wired["selfie"] == ["msg-initiative-1"]


def test_selfie_skipped_when_disabled(_wired, monkeypatch):
    monkeypatch.setattr(
        initiative_service,
        "_settings",
        lambda: {"enabled": True, "selfie_enabled": False, "selfie_chance": 1.0},
    )
    initiative_service.run_chat_initiative("беспокойство")
    assert _wired["selfie"] == []


def test_disabled_initiative_returns_none(_wired, monkeypatch):
    monkeypatch.setattr(
        initiative_service,
        "_settings",
        lambda: {"enabled": False, "selfie_enabled": True, "selfie_chance": 1.0},
    )
    assert initiative_service.run_chat_initiative("беспокойство") is None
    assert _wired["persisted"] == []


def test_empty_compose_skips_silently(_wired, monkeypatch):
    monkeypatch.setattr(
        initiative_service, "_compose_initiative_text", lambda emotion, name: ""
    )
    assert initiative_service.run_chat_initiative("беспокойство") is None
    assert _wired["persisted"] == []
    assert _wired["selfie"] == []
