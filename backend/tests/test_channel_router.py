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
