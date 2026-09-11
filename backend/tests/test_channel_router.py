from core import channel_router
import pytest


pytestmark = pytest.mark.regression


def test_main_chat_primary_blocks_telegram_ingress():
    policy = {
        "priority": ["main_chat", "telegram"],
        "channels": {
            "main_chat": {"enabled": True, "allow_fallback": False},
            "telegram": {"enabled": True, "allow_fallback": True},
        },
    }

    allowed, reason = channel_router.can_accept_ingress("telegram", policy=policy)
    assert allowed is False
    assert reason == "main_chat_priority_exclusive"


def test_telegram_primary_allows_telegram_ingress():
    policy = {
        "priority": ["telegram", "main_chat"],
        "channels": {
            "main_chat": {"enabled": True, "allow_fallback": False},
            "telegram": {"enabled": True, "allow_fallback": True},
        },
    }

    allowed, reason = channel_router.can_accept_ingress("telegram", policy=policy)
    assert allowed is True
    assert reason == "ok"


def test_resolve_fallback_to_main_chat_when_telegram_unavailable():
    policy = {
        "priority": ["telegram", "main_chat"],
        "channels": {
            "main_chat": {"enabled": True, "allow_fallback": False},
            "telegram": {"enabled": True, "allow_fallback": True},
        },
    }
    channel, reason = channel_router.resolve_channel_with_fallback(
        "telegram",
        availability={"telegram": False, "main_chat": True},
        policy=policy,
    )

    assert channel == "main_chat"
    assert reason == "fallback"


def test_main_chat_primary_disables_fallback_even_if_telegram_has_allow_fallback():
    policy = {
        "priority": ["main_chat", "telegram"],
        "channels": {
            "main_chat": {"enabled": True, "allow_fallback": False},
            "telegram": {"enabled": True, "allow_fallback": True},
        },
    }
    channel, reason = channel_router.resolve_channel_with_fallback(
        "telegram",
        availability={"telegram": False, "main_chat": True},
        policy=policy,
    )

    assert channel is None
    assert reason in {"main_chat_priority_exclusive", "main_chat_priority_no_fallback"}


def test_main_chat_ingress_is_always_open():
    policy = {
        "priority": ["telegram", "main_chat"],
        "channels": {
            "main_chat": {"enabled": False, "allow_fallback": False},
            "telegram": {"enabled": True, "allow_fallback": False},
        },
    }

    allowed, reason = channel_router.can_accept_ingress("main_chat", policy=policy)
    assert allowed is True
    assert reason == "ok"


def test_main_chat_is_fallback_even_without_allow_fallback():
    policy = {
        "priority": ["telegram", "main_chat"],
        "channels": {
            "main_chat": {"enabled": True, "allow_fallback": False},
            "telegram": {"enabled": True, "allow_fallback": False},
        },
    }
    channel, reason = channel_router.resolve_channel_with_fallback(
        "telegram",
        availability={"telegram": False, "main_chat": True},
        policy=policy,
    )

    assert channel == "main_chat"
    assert reason == "fallback"


def test_policy_takes_telegram_switch_from_bridge_flag(monkeypatch):
    values = {
        "communication": {
            "priority": ["telegram", "main_chat"],
            "channels": {
                "main_chat": {"enabled": False, "allow_fallback": False},
                "telegram": {"enabled": True, "allow_fallback": True},
            },
        },
        "telegram.enabled": False,
    }
    monkeypatch.setattr(
        channel_router.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: values.get(path, default),
    )

    policy = channel_router.get_policy()
    assert policy["channels"]["telegram"]["enabled"] is False
    assert policy["channels"]["main_chat"]["enabled"] is True

    allowed, reason = channel_router.can_accept_ingress("telegram")
    assert allowed is False
    assert reason == "channel_disabled"
