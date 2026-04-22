from routes.ws_routes import _is_chat_visible_history_item


def test_main_chat_hides_telegram_transport_messages():
    item = {
        "role": "assistant",
        "content": "hello from tg",
        "runtime_meta": {
            "transport": {"name": "telegram", "chat_id": 123},
            "event": "incoming_message",
        },
    }
    assert _is_chat_visible_history_item(item) is False


def test_main_chat_keeps_main_chat_transport_messages():
    item = {
        "role": "assistant",
        "content": "hello from main",
        "runtime_meta": {
            "transport": {"name": "main_chat"},
            "event": "outgoing_message",
        },
    }
    assert _is_chat_visible_history_item(item) is True
