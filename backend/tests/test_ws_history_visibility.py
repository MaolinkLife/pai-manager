import pytest

from routes import ws_routes
from routes.ws_routes import _is_chat_visible_history_item, _is_owner_source_history_item


pytestmark = pytest.mark.regression


def test_ws_history_hides_tool_role_messages():
    assert (
        _is_chat_visible_history_item(
            {
                "role": "tool",
                "content": "[OK]: decision context prepared",
            }
        )
        is False
    )


def test_ws_history_hides_tool_event_runtime_meta():
    assert (
        _is_chat_visible_history_item(
            {
                "role": "assistant",
                "runtime_meta": {"event": "tool_event"},
                "content": "hidden",
            }
        )
        is False
    )


def test_ws_history_keeps_regular_messages():
    assert (
        _is_chat_visible_history_item(
            {
                "role": "assistant",
                "content": "Привет!",
                "runtime_meta": {"event": "message"},
            }
        )
        is True
    )


def test_all_sources_history_keeps_only_owner_telegram_chat(monkeypatch):
    monkeypatch.setattr(
        ws_routes,
        "get_config_value",
        lambda path, default=None: 123 if path == "telegram.lockdown.owner_chat_id" else default,
    )

    assert (
        _is_owner_source_history_item(
            {
                "role": "user",
                "content": "owner",
                "runtime_meta": {"transport": {"name": "telegram", "chat_id": 123}},
            }
        )
        is True
    )
    assert (
        _is_owner_source_history_item(
            {
                "role": "user",
                "content": "not owner",
                "runtime_meta": {"transport": {"name": "telegram", "chat_id": 456}},
            }
        )
        is False
    )


def test_all_sources_history_keeps_main_chat_without_owner_marker():
    assert (
        _is_owner_source_history_item(
            {
                "role": "assistant",
                "content": "main",
                "runtime_meta": {"transport": {"name": "main_chat"}},
            }
        )
        is True
    )
