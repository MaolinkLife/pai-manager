"""HuggingFace hub import service.

Search the hub, list repository weight files and download them into the
local model directories (``storage/models/*``) with progress streamed to the
UI as ``hf_download`` WS events. Mirrors the Ollama pull manager pattern:
one asyncio task per download, throttled broadcasts, an in-memory snapshot
for page-refresh recovery, cancellation cleans up the partial file.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

from constants.paths import (
    GGUF_MODELS_DIR,
    IMAGE_GENERATION_CHECKPOINTS_DIR,
    IMAGE_GENERATION_LORA_DIR,
    IMAGE_GENERATION_VAE_DIR,
    RVC_MODELS_DIR,
    STT_MODELS_DIR,
    TTS_MODELS_DIR,
    VISION_MODELS_DIR,
)
from modules.system.logger import AuditStatus, log_audit_entry

HF_API_BASE = "https://huggingface.co/api"
HF_RESOLVE_BASE = "https://huggingface.co"

_WEIGHT_EXTENSIONS = {
    ".gguf", ".safetensors", ".ckpt", ".onnx", ".bin", ".pt", ".pth",
    ".npz", ".tflite", ".txt", ".json", ".model", ".vocab", ".spm",
}
_BROADCAST_MIN_INTERVAL_SEC = 0.5
_DOWNLOAD_CHUNK = 1 << 20  # 1 MiB

CATEGORY_DIRS: Dict[str, str] = {
    "gguf": GGUF_MODELS_DIR,
    "image_checkpoint": IMAGE_GENERATION_CHECKPOINTS_DIR,
    "image_lora": IMAGE_GENERATION_LORA_DIR,
    "image_vae": IMAGE_GENERATION_VAE_DIR,
    "stt": STT_MODELS_DIR,
    "tts": TTS_MODELS_DIR,
    "vision": VISION_MODELS_DIR,
    "rvc": RVC_MODELS_DIR,
}

_states: Dict[str, Dict[str, Any]] = {}
_tasks: Dict[str, asyncio.Task] = {}


# ---------------------------------------------------------------------------
# Hub API
# ---------------------------------------------------------------------------

async def search_models(query: str, limit: int = 20) -> Dict[str, Any]:
    params = {
        "search": query,
        "limit": str(max(1, min(limit, 50))),
        "sort": "downloads",
        "direction": "-1",
    }
    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{HF_API_BASE}/models", params=params) as resp:
                resp.raise_for_status()
                data = await resp.json()
    except Exception as exc:
        return {"status": "error", "message": str(exc), "results": []}

    results: List[Dict[str, Any]] = []
    for item in data if isinstance(data, list) else []:
        repo_id = str(item.get("id") or item.get("modelId") or "").strip()
        if not repo_id:
            continue
        results.append(
            {
                "repo_id": repo_id,
                "downloads": int(item.get("downloads") or 0),
                "likes": int(item.get("likes") or 0),
                "updated_at": item.get("lastModified"),
                "tags": [t for t in (item.get("tags") or []) if isinstance(t, str)][:8],
                "gated": bool(item.get("gated")),
            }
        )
    return {"status": "ok", "results": results}


async def list_repo_files(repo_id: str) -> Dict[str, Any]:
    repo_id = str(repo_id or "").strip().strip("/")
    if not repo_id or repo_id.count("/") > 1:
        return {"status": "error", "message": "Invalid repo id", "files": []}
    url = f"{HF_API_BASE}/models/{repo_id}/tree/main"
    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params={"recursive": "true"}) as resp:
                if resp.status == 404:
                    return {"status": "error", "message": "Repository not found", "files": []}
                if resp.status in (401, 403):
                    return {"status": "error", "message": "Repository is gated or private", "files": []}
                resp.raise_for_status()
                data = await resp.json()
    except Exception as exc:
        return {"status": "error", "message": str(exc), "files": []}

    files: List[Dict[str, Any]] = []
    for item in data if isinstance(data, list) else []:
        if str(item.get("type") or "") != "file":
            continue
        path = str(item.get("path") or "")
        suffix = Path(path).suffix.lower()
        if suffix not in _WEIGHT_EXTENSIONS:
            continue
        files.append(
            {
                "path": path,
                "size": int(item.get("size") or 0),
                "suggested_category": _suggest_category(path),
            }
        )
    files.sort(key=lambda f: (-f["size"], f["path"]))
    return {"status": "ok", "files": files}


def _suggest_category(path: str) -> str:
    lower = path.lower()
    suffix = Path(lower).suffix
    if suffix == ".gguf":
        return "gguf"
    if suffix in (".safetensors", ".ckpt"):
        if "lora" in lower:
            return "image_lora"
        if "vae" in lower:
            return "image_vae"
        return "image_checkpoint"
    if suffix == ".onnx":
        return "stt"
    return "gguf"


# ---------------------------------------------------------------------------
# Download manager
# ---------------------------------------------------------------------------

def snapshot() -> Dict[str, Any]:
    return {"status": "ok", "downloads": [dict(state) for state in _states.values()]}


def is_running(key: str) -> bool:
    task = _tasks.get(key)
    return task is not None and not task.done()


def start_download(repo_id: str, file_path: str, category: str) -> Dict[str, Any]:
    repo_id = str(repo_id or "").strip().strip("/")
    file_path = str(file_path or "").strip().lstrip("/")
    category = str(category or "").strip()
    if not repo_id or not file_path:
        return {"status": "error", "message": "repo and path are required"}
    if category not in CATEGORY_DIRS:
        return {"status": "error", "message": f"Unknown category: {category}"}

    dest_root = Path(CATEGORY_DIRS[category])
    # Preserve the relative layout (sherpa/STT repos rely on it) but make sure
    # the resolved target cannot escape the category directory.
    target = (dest_root / file_path).resolve()
    if not str(target).startswith(str(dest_root.resolve())):
        return {"status": "error", "message": "Invalid file path"}

    key = f"{repo_id}::{file_path}"
    if is_running(key):
        return {"status": "already_running", "id": key}

    _states[key] = {
        "type": "hf_download",
        "id": key,
        "repo_id": repo_id,
        "path": file_path,
        "category": category,
        "status": "starting",
        "completed": 0,
        "total": 0,
        "done": False,
        "error": None,
        "started_at": time.time(),
    }
    _tasks[key] = asyncio.create_task(_run_download(key, repo_id, file_path, target))
    log_audit_entry(
        "hf_download_started",
        "[HF] Model file download started.",
        AuditStatus.INFO,
        details={"repo": repo_id, "path": file_path, "category": category},
    )
    return {"status": "started", "id": key}


def cancel_download(key: str) -> Dict[str, Any]:
    task = _tasks.get(key)
    if task is None or task.done():
        return {"status": "not_running", "id": key}
    task.cancel()
    return {"status": "cancelling", "id": key}


async def _broadcast(state: Dict[str, Any]) -> None:
    try:
        from core.websocket_manager import manager

        await manager.send_message(json.dumps(state, ensure_ascii=False))
    except Exception:
        pass


async def _run_download(key: str, repo_id: str, file_path: str, target: Path) -> None:
    state = _states[key]
    part_path = target.with_name(target.name + ".part")
    url = f"{HF_RESOLVE_BASE}/{repo_id}/resolve/main/{file_path}"
    last_sent = 0.0
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        timeout = aiohttp.ClientTimeout(total=None, sock_read=300)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status in (401, 403):
                    state.update(status="error", error="Repository is gated or private", done=True)
                    return
                if resp.status == 404:
                    state.update(status="error", error="File not found", done=True)
                    return
                resp.raise_for_status()
                state["total"] = int(resp.headers.get("Content-Length") or 0)
                state["status"] = "downloading"
                with open(part_path, "wb") as handle:
                    async for chunk in resp.content.iter_chunked(_DOWNLOAD_CHUNK):
                        handle.write(chunk)
                        state["completed"] += len(chunk)
                        now = time.monotonic()
                        if now - last_sent >= _BROADCAST_MIN_INTERVAL_SEC:
                            last_sent = now
                            await _broadcast(state)
        os.replace(part_path, target)
        state.update(status="success", done=True, error=None)
    except asyncio.CancelledError:
        state.update(status="cancelled", error=None, done=True)
    except Exception as exc:
        state.update(status="error", error=str(exc), done=True)
    finally:
        if state.get("status") != "success":
            try:
                part_path.unlink(missing_ok=True)
            except Exception:
                pass
        _tasks.pop(key, None)
        await _broadcast(state)
        if state.get("status") in ("cancelled", "success"):
            _states.pop(key, None)
        log_audit_entry(
            "hf_download_finished",
            "[HF] Model file download finished.",
            AuditStatus.INFO if not state.get("error") else AuditStatus.WARNING,
            details={
                "repo": repo_id,
                "path": file_path,
                "status": state.get("status"),
                "error": state.get("error"),
            },
        )
