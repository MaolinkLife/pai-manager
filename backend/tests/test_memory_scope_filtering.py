from modules.memory.service import MemoryModule


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
