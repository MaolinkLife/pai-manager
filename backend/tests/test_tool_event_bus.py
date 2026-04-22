from core import tool_event_bus
import pytest


pytestmark = pytest.mark.regression


def test_emit_tool_event_logs_without_history_write(monkeypatch):
    captured = {}

    def fake_log_audit_entry(event_type, msg, status, details=None, **kwargs):
        captured["event_type"] = event_type
        captured["msg"] = msg
        captured["status"] = status
        captured["details"] = details or {}

    monkeypatch.setattr(tool_event_bus, "log_audit_entry", fake_log_audit_entry)

    message_id = tool_event_bus.emit_tool_event(
        tool_name="image.generate",
        content="[OK]: image generated",
        status="ok",
        source="unit_test",
        runtime_meta={"transport": {"name": "main_chat"}},
        character_name="default_waifu",
    )

    assert message_id is None
    assert captured["event_type"] == "tool_event_logged"
    assert captured["details"]["tool_name"] == "image.generate"
    assert captured["details"]["status"] == "ok"
    assert captured["details"]["source"] == "unit_test"
    assert captured["details"]["runtime_meta"]["transport"]["name"] == "main_chat"


def test_emit_tool_event_detects_error_status_from_content(monkeypatch):
    captured = {}

    def fake_log_audit_entry(event_type, msg, status, details=None, **kwargs):
        captured["event_type"] = event_type
        captured["details"] = details or {}

    monkeypatch.setattr(tool_event_bus, "log_audit_entry", fake_log_audit_entry)

    tool_event_bus.emit_tool_event(
        tool_name="pipeline.run",
        content="[ERROR]: failed",
        source="unit_test",
        character_name="default_waifu",
    )

    assert captured["event_type"] == "tool_event_logged"
    assert captured["details"]["status"] == "error"
