from modules.memory.service import MemoryModule
from modules.memory import service as memory_service


def test_memory_scope_filters_main_chat_from_telegram_rows():
    rows = [
        {"id": "1", "runtime_meta": {"transport": {"name": "telegram", "chat_id": 1}}},
        {"id": "2", "runtime_meta": {"transport": {"name": "main_chat"}}},
        {"id": "3", "runtime_meta": {}},
    ]
    filtered = MemoryModule._apply_scope_filter(rows, {"channel": "main_chat"})
    assert [r["id"] for r in filtered] == ["2", "3"]


def test_memory_scope_filters_telegram_by_chat_id():
    rows = [
        {"id": "1", "runtime_meta": {"transport": {"name": "telegram", "chat_id": 11}}},
        {"id": "2", "runtime_meta": {"transport": {"name": "telegram", "chat_id": 22}}},
        {"id": "3", "runtime_meta": {"transport": {"name": "main_chat"}}},
    ]
    filtered = MemoryModule._apply_scope_filter(
        rows,
        {"channel": "telegram", "chat_id": 22},
    )
    assert [r["id"] for r in filtered] == ["2"]


def test_memory_scope_deduplicates_telegram_rows_by_message_id():
    rows = [
        {
            "id": "newer-local-row",
            "role": "user",
            "runtime_meta": {
                "event": "incoming_message",
                "transport": {"name": "telegram", "chat_id": 22, "message_id": 77},
            },
        },
        {
            "id": "older-local-row",
            "role": "user",
            "runtime_meta": {
                "event": "incoming_message",
                "transport": {"name": "telegram", "chat_id": 22, "message_id": 77},
            },
        },
    ]
    filtered = MemoryModule._apply_scope_filter(
        rows,
        {"channel": "telegram", "chat_id": 22},
    )
    assert [r["id"] for r in filtered] == ["newer-local-row"]


def test_session_history_preview_does_not_cross_idle_gap(monkeypatch):
    rows = [
        {
            "id": "a-old",
            "role": "assistant",
            "content": "old reply",
            "timestamp": "2026-04-25T10:10:00+00:00",
        },
        {
            "id": "u-old",
            "role": "user",
            "content": "old message",
            "timestamp": "2026-04-25T10:00:00+00:00",
        },
    ]
    monkeypatch.setattr(memory_service.database_service, "get_history", lambda *_args, **_kwargs: rows)

    preview = MemoryModule()._load_session_history_preview(
        "Lim",
        6,
        "2026-04-27T00:30:00+00:00",
        {"enabled": True, "idle_gap_minutes": 90, "max_messages": 512},
    )

    assert preview == []


def test_memory_history_preview_strips_reasoning_blocks(monkeypatch):
    rows = [
        {
            "id": "a1",
            "role": "assistant",
            "content": "<think>secret reasoning</think>\n\nVisible reply",
            "timestamp": "2026-04-27T00:20:00+00:00",
        },
    ]
    monkeypatch.setattr(memory_service.database_service, "get_history", lambda *_args, **_kwargs: rows)

    preview = MemoryModule()._load_history_preview("Lim", 4)

    assert preview[0]["content"] == "Visible reply"
    assert "secret reasoning" not in preview[0]["content"]


def test_memory_recent_messages_strip_reasoning_blocks(monkeypatch):
    rows = [
        {
            "id": "a1",
            "role": "assistant",
            "content": "<think>\nThinking Process\n</think>\n\nVisible memory",
            "timestamp": "2026-04-27T00:20:00+00:00",
        },
    ]
    monkeypatch.setattr(memory_service.database_service, "get_history", lambda *_args, **_kwargs: rows)

    recent = MemoryModule()._load_recent_messages("Lim", 4)

    assert recent[0]["content"] == "Visible memory"
    assert "<think>" not in recent[0]["content"]


def test_session_history_preview_keeps_current_session_until_limit(monkeypatch):
    rows = [
        {
            "id": "a2",
            "role": "assistant",
            "content": "current reply",
            "timestamp": "2026-04-27T00:20:00+00:00",
        },
        {
            "id": "u2",
            "role": "user",
            "content": "current message",
            "timestamp": "2026-04-27T00:10:00+00:00",
        },
        {
            "id": "a1",
            "role": "assistant",
            "content": "previous reply",
            "timestamp": "2026-04-26T23:55:00+00:00",
        },
        {
            "id": "u1",
            "role": "user",
            "content": "previous message",
            "timestamp": "2026-04-26T23:50:00+00:00",
        },
        {
            "id": "old",
            "role": "user",
            "content": "older session",
            "timestamp": "2026-04-26T20:00:00+00:00",
        },
    ]
    monkeypatch.setattr(memory_service.database_service, "get_history", lambda *_args, **_kwargs: rows)

    preview = MemoryModule()._load_session_history_preview(
        "Lim",
        3,
        "2026-04-27T00:30:00+00:00",
        {"enabled": True, "idle_gap_minutes": 90, "max_messages": 512},
    )

    assert [item["id"] for item in preview] == ["a1", "u2", "a2"]
