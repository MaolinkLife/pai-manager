import pytest

from routes.ws_routes import _is_chat_visible_history_item


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
