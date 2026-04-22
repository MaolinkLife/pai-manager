from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from modules.system.logger import AuditStatus, log_audit_entry
from modules.system.service import get_active_character_name


def _normalize_status(status: Optional[str], content: str) -> str:
    raw = (status or "").strip().lower()
    if raw in {"ok", "error", "info"}:
        return raw

    text = str(content or "").strip().lower()
    if text.startswith("[error]"):
        return "error"
    if text.startswith("[ok]"):
        return "ok"
    return "info"


def emit_tool_event(
    *,
    tool_name: str,
    content: str,
    status: Optional[str] = None,
    source: str = "tool_orchestration",
    runtime_meta: Optional[dict[str, Any]] = None,
    character_name: Optional[str] = None,
    timestamp: Optional[datetime] = None,
    tags: Optional[list[str]] = None,
) -> Optional[str]:
    payload = str(content or "").strip()
    if not payload:
        return None

    resolved_character = character_name or get_active_character_name(default="default_waifu")
    resolved_status = _normalize_status(status, payload)
    event_meta: dict[str, Any] = {
        "event": "tool_event",
        "source": source,
        "character_name": resolved_character,
        "timestamp": (timestamp or datetime.now(timezone.utc)).isoformat(),
        "tool": {
            "name": str(tool_name or "").strip() or "unknown_tool",
            "status": resolved_status,
        },
        "content": payload,
    }
    if isinstance(runtime_meta, dict):
        event_meta.update(runtime_meta)

    log_audit_entry(
        "tool_event_logged",
        "[ToolEventBus] Tool event logged to audit/debug stream.",
        AuditStatus.INFO if resolved_status != "error" else AuditStatus.WARNING,
        details={
            "tool_name": event_meta["tool"]["name"],
            "status": resolved_status,
            "source": source,
            "tags": list(tags or []),
            "runtime_meta": event_meta,
        },
    )
    # Tool events are intentionally NOT persisted to dialog history.
    return None
