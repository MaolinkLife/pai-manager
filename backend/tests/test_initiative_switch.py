"""Global initiative switch: off on a fresh install, gates main chat and Telegram.

Initiative is a global setting. A channel keeps its
own initiative behaviour, but none of it works while the global switch is off.
"""

import copy

import pytest

from constants.default_config import DEFAULT_CONFIG
from modules.initiative import service as initiative_service
from modules.system import config as config_service
from modules.system.config import normalize_config_structure
from modules.telegram.service import TelegramBridgeService


def _use_initiative(monkeypatch, initiative):
    def fake_get_config_value(path, default=None, user_uuid=None):
        if path == "initiative":
            return initiative
        if path == "initiative.enabled":
            return initiative.get("enabled", default)
        return default

    monkeypatch.setattr(config_service, "get_config_value", fake_get_config_value)


def test_fresh_install_has_initiative_switched_off():
    assert DEFAULT_CONFIG["initiative"]["enabled"] is False

    fresh = normalize_config_structure(copy.deepcopy(DEFAULT_CONFIG))

    assert fresh["initiative"]["enabled"] is False


@pytest.mark.parametrize(
    "stored, expected",
    [
        ({"initiative": {"chat": {"enabled": True}, "selfie": {"enabled": True, "chance": 0.4}}}, True),
        ({"initiative": {"chat": {"enabled": False}}}, False),
        ({"initiative": {"chat": {"enabled": False}}, "telegram": {"initiative": {"enabled": True}}}, True),
        # No section at all: the main chat initiative ran on the code default.
        ({}, True),
    ],
)
def test_config_stored_before_the_switch_keeps_what_it_did(stored, expected):
    normalized = normalize_config_structure(stored)

    assert normalized["initiative"]["enabled"] is expected


def test_a_stored_switch_is_never_overridden():
    stored = {"initiative": {"enabled": False, "chat": {"enabled": True}}}

    assert normalize_config_structure(stored)["initiative"]["enabled"] is False


def test_stored_initiative_gets_the_missing_defaults():
    normalized = normalize_config_structure({"initiative": {"enabled": True}})

    assert normalized["initiative"]["chat"] == DEFAULT_CONFIG["initiative"]["chat"]
    assert normalized["initiative"]["selfie"] == DEFAULT_CONFIG["initiative"]["selfie"]


def test_switched_off_initiative_does_not_write_in_the_main_chat(monkeypatch):
    _use_initiative(monkeypatch, {"enabled": False, "chat": {"enabled": True}})
    composed = []
    monkeypatch.setattr(
        initiative_service,
        "_compose_initiative_text",
        lambda emotion, character_name: composed.append(emotion) or "Эй",
    )

    assert initiative_service.run_chat_initiative("беспокойство") is None
    assert composed == []


def test_main_chat_writes_first_only_when_both_switches_are_on(monkeypatch):
    _use_initiative(monkeypatch, {"enabled": True, "chat": {"enabled": False}})
    assert initiative_service._settings()["enabled"] is False

    _use_initiative(monkeypatch, {"enabled": True, "chat": {"enabled": True}})
    assert initiative_service._settings()["enabled"] is True
    assert initiative_service.initiative_enabled() is True


def test_telegram_initiative_waits_for_the_global_switch(monkeypatch):
    _use_initiative(monkeypatch, {"enabled": False})
    assert TelegramBridgeService._initiative_switched_on({"enabled": True}) is False

    _use_initiative(monkeypatch, {"enabled": True})
    assert TelegramBridgeService._initiative_switched_on({"enabled": True}) is True
    assert TelegramBridgeService._initiative_switched_on({"enabled": False}) is False
