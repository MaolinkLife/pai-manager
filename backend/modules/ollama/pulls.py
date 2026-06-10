"""Background Ollama pull tasks with WS progress broadcast.

Started from the FastAPI event loop (routes), so tasks are plain
``asyncio.create_task``. Progress is pushed to the UI as ``model_pull``
WS events (throttled) and the latest state of every pull is kept in
memory so the page can recover after a refresh via the snapshot endpoint.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict

from modules.ollama import client as ollama_client
from modules.system.logger import AuditStatus, log_audit_entry

_BROADCAST_MIN_INTERVAL_SEC = 0.5

_states: Dict[str, Dict[str, Any]] = {}
_tasks: Dict[str, asyncio.Task] = {}


def snapshot() -> Dict[str, Any]:
    return {"status": "ok", "pulls": [dict(state) for state in _states.values()]}


def is_running(model: str) -> bool:
    task = _tasks.get(model)
    return task is not None and not task.done()


def start_pull(model: str) -> Dict[str, Any]:
    model = str(model or "").strip()
    if not model:
        return {"status": "error", "message": "Model name is required"}
    if is_running(model):
        return {"status": "already_running", "model": model}

    _states[model] = {
        "type": "model_pull",
        "model": model,
        "status": "starting",
        "completed": 0,
        "total": 0,
        "done": False,
        "error": None,
        "started_at": time.time(),
    }
    _tasks[model] = asyncio.create_task(_run_pull(model))
    log_audit_entry(
        "ollama_model_pull_started",
        "[Ollama] Model pull started.",
        AuditStatus.INFO,
        details={"model": model},
    )
    return {"status": "started", "model": model}


def cancel_pull(model: str) -> Dict[str, Any]:
    task = _tasks.get(model)
    if task is None or task.done():
        return {"status": "not_running", "model": model}
    task.cancel()
    return {"status": "cancelling", "model": model}


async def _broadcast(state: Dict[str, Any]) -> None:
    try:
        from core.websocket_manager import manager

        await manager.send_message(json.dumps(state, ensure_ascii=False))
    except Exception:
        pass


async def _run_pull(model: str) -> None:
    state = _states[model]
    last_sent = 0.0
    try:
        async for obj in ollama_client.pull_model_stream(model):
            if obj.get("error"):
                state.update(status="error", error=str(obj["error"]), done=True)
                break
            status_text = str(obj.get("status") or "")
            state["status"] = status_text or state["status"]
            if obj.get("total"):
                state["total"] = int(obj.get("total") or 0)
                state["completed"] = int(obj.get("completed") or 0)
            if status_text == "success":
                state.update(done=True, error=None)
                break
            now = time.monotonic()
            if now - last_sent >= _BROADCAST_MIN_INTERVAL_SEC:
                last_sent = now
                await _broadcast(state)
        else:
            # Stream ended without an explicit success/error marker.
            if not state.get("done"):
                state.update(status="error", error="Pull stream ended unexpectedly", done=True)
    except asyncio.CancelledError:
        state.update(status="cancelled", error=None, done=True)
    except Exception as exc:
        state.update(status="error", error=str(exc), done=True)
    finally:
        _tasks.pop(model, None)
        await _broadcast(state)
        log_audit_entry(
            "ollama_model_pull_finished",
            "[Ollama] Model pull finished.",
            AuditStatus.INFO if not state.get("error") else AuditStatus.WARNING,
            details={
                "model": model,
                "status": state.get("status"),
                "error": state.get("error"),
            },
        )
