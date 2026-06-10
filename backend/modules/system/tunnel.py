import copy
import re
import subprocess
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from constants.default_config import DEFAULT_CONFIG
from modules.system import service as config_service
from modules.system.logger import AuditStatus, log_audit_entry

_STATE_LOCK = threading.RLock()
_PROCESS: Optional[subprocess.Popen] = None
_READER_THREAD: Optional[threading.Thread] = None
_ACTIVE_USER_UUID: Optional[str] = None

_MAX_LOG_LINES = 200

_STATE: Dict[str, Any] = {
    "running": False,
    "provider": "",
    "command": [],
    "pid": None,
    "public_url": "",
    "started_at": None,
    "stopped_at": None,
    "last_error": "",
    "last_logs": [],
}

_URL_PATTERNS = [
    re.compile(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com"),
    re.compile(r"https://[a-zA-Z0-9.-]+\.loca\.lt"),
    re.compile(r"https://[a-zA-Z0-9.-]+\.ngrok-free\.app"),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_line(value: str) -> str:
    return (value or "").strip().replace("\x00", "")


def _append_log(line: str) -> None:
    if not line:
        return
    logs = _STATE.setdefault("last_logs", [])
    logs.append(line)
    if len(logs) > _MAX_LOG_LINES:
        del logs[: len(logs) - _MAX_LOG_LINES]


def _extract_public_url(line: str) -> Optional[str]:
    clean = _sanitize_line(line)
    if not clean:
        return None

    for pattern in _URL_PATTERNS:
        match = pattern.search(clean)
        if match:
            return match.group(0)

    generic = re.search(r"https://[^\s\"']+", clean)
    if generic:
        return generic.group(0)
    return None


def _default_tunneling_cfg() -> Dict[str, Any]:
    connector = DEFAULT_CONFIG.get("connector", {})
    tunneling = connector.get("tunneling", {}) if isinstance(connector, dict) else {}
    return copy.deepcopy(tunneling if isinstance(tunneling, dict) else {})


def _normalize_tunneling_cfg(raw_cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    defaults = _default_tunneling_cfg()
    cfg = copy.deepcopy(raw_cfg or {})
    if not isinstance(cfg, dict):
        cfg = {}

    merged = copy.deepcopy(defaults)
    merged.update(cfg)

    provider = str(merged.get("provider") or "cloudflared").strip().lower()
    if provider not in {"cloudflared", "localtunnel"}:
        provider = "cloudflared"
    merged["provider"] = provider

    local_url = str(merged.get("local_url") or "http://127.0.0.1:4200").strip()
    merged["local_url"] = local_url

    local_port = merged.get("local_port")
    if not isinstance(local_port, int) or local_port <= 0:
        parsed = urlparse(local_url)
        local_port = parsed.port or 4200
    merged["local_port"] = int(local_port)

    merged["enabled"] = bool(merged.get("enabled", False))
    merged["command_path"] = str(merged.get("command_path") or "").strip()
    merged["public_url"] = str(merged.get("public_url") or "").strip()

    return merged


def _load_user_tunneling_cfg(user_uuid: Optional[str]) -> Dict[str, Any]:
    raw = config_service.get_config_value(
        "connector.tunneling", default={}, user_uuid=user_uuid
    )
    return _normalize_tunneling_cfg(raw if isinstance(raw, dict) else {})


def _build_command(cfg: Dict[str, Any]) -> list[str]:
    provider = cfg["provider"]
    command_path = cfg.get("command_path", "")
    local_url = cfg["local_url"]
    local_port = int(cfg["local_port"])

    if provider == "cloudflared":
        executable = command_path or "cloudflared"
        return [executable, "tunnel", "--url", local_url]

    if provider == "localtunnel":
        executable = command_path or "lt"
        return [executable, "--port", str(local_port)]

    raise ValueError(f"Unsupported tunnel provider: {provider}")


def _set_public_url(url: str) -> None:
    if not url:
        return
    if _STATE.get("public_url") == url:
        return
    _STATE["public_url"] = url

    active_user_uuid = _ACTIVE_USER_UUID
    if active_user_uuid:
        try:
            config_service.set_config_value(
                "connector.tunneling.public_url",
                url,
                user_uuid=active_user_uuid,
            )
        except Exception:
            pass


def _reader_loop(process: subprocess.Popen) -> None:
    exit_code: Optional[int] = None
    try:
        if process.stdout is not None:
            for line in iter(process.stdout.readline, ""):
                clean = _sanitize_line(line)
                if not clean:
                    continue

                with _STATE_LOCK:
                    _append_log(clean)
                    maybe_url = _extract_public_url(clean)
                    if maybe_url:
                        _set_public_url(maybe_url)
    except Exception as exc:
        with _STATE_LOCK:
            _STATE["last_error"] = f"Tunnel output reader failed: {exc}"
    finally:
        try:
            exit_code = process.wait(timeout=1)
        except Exception:
            exit_code = None

        with _STATE_LOCK:
            global _PROCESS, _READER_THREAD, _ACTIVE_USER_UUID
            if _PROCESS is process:
                _PROCESS = None
            _READER_THREAD = None
            _ACTIVE_USER_UUID = None
            _STATE["running"] = False
            _STATE["pid"] = None
            _STATE["stopped_at"] = _now_iso()
            if exit_code not in [None, 0] and not _STATE.get("last_error"):
                _STATE["last_error"] = f"Tunnel process exited with code {exit_code}"


def get_status(user_uuid: Optional[str] = None) -> Dict[str, Any]:
    with _STATE_LOCK:
        status = copy.deepcopy(_STATE)
    status["config"] = _load_user_tunneling_cfg(user_uuid)
    return status


def runtime_snapshot() -> Dict[str, Any]:
    """Cheap, DB-free snapshot for hot-path callers (e.g. access guard middleware)."""
    with _STATE_LOCK:
        return {
            "running": bool(_STATE.get("running")),
            "public_url": str(_STATE.get("public_url") or ""),
        }


def start_tunnel(
    user_uuid: Optional[str] = None, overrides: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    cfg = _load_user_tunneling_cfg(user_uuid)
    if isinstance(overrides, dict):
        cfg = _normalize_tunneling_cfg({**cfg, **overrides})

    command = _build_command(cfg)
    with _STATE_LOCK:
        global _PROCESS, _READER_THREAD, _ACTIVE_USER_UUID
        if _PROCESS and _PROCESS.poll() is None:
            _STATE["last_error"] = ""
            return get_status(user_uuid)

        _STATE["last_error"] = ""
        _STATE["stopped_at"] = None
        _STATE["public_url"] = cfg.get("public_url", "")

        startup_info = None
        if hasattr(subprocess, "STARTUPINFO"):
            startup_info = subprocess.STARTUPINFO()
            startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                startupinfo=startup_info,
            )
        except Exception as exc:
            _STATE["running"] = False
            _STATE["last_error"] = f"Failed to start tunnel: {exc}"
            _append_log(_STATE["last_error"])
            log_audit_entry(
                event_type="tunnel_start_error",
                msg="[Tunnel] Failed to start process.",
                status=AuditStatus.ERROR,
                details={"error": str(exc), "command": command},
            )
            return get_status(user_uuid)

        _PROCESS = process
        _ACTIVE_USER_UUID = user_uuid
        _STATE["running"] = True
        _STATE["provider"] = cfg["provider"]
        _STATE["command"] = command
        _STATE["pid"] = process.pid
        _STATE["started_at"] = _now_iso()
        _STATE["stopped_at"] = None
        _append_log(f"[Tunnel] Started provider={cfg['provider']} pid={process.pid}")

        _READER_THREAD = threading.Thread(
            target=_reader_loop,
            args=(process,),
            daemon=True,
            name="tunnel-output-reader",
        )
        _READER_THREAD.start()

        log_audit_entry(
            event_type="tunnel_started",
            msg="[Tunnel] Tunnel process started.",
            status=AuditStatus.SUCCESS,
            details={
                "provider": cfg["provider"],
                "pid": process.pid,
                "user_uuid": user_uuid,
            },
            meta={"command": command},
        )

    return get_status(user_uuid)


def stop_tunnel(user_uuid: Optional[str] = None) -> Dict[str, Any]:
    with _STATE_LOCK:
        global _PROCESS, _ACTIVE_USER_UUID
        process = _PROCESS
        _ACTIVE_USER_UUID = None

    if not process or process.poll() is not None:
        with _STATE_LOCK:
            _STATE["running"] = False
            _STATE["pid"] = None
            _STATE["stopped_at"] = _now_iso()
        return get_status(user_uuid=user_uuid)

    try:
        process.terminate()
        process.wait(timeout=5)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass

    with _STATE_LOCK:
        _STATE["running"] = False
        _STATE["pid"] = None
        _STATE["stopped_at"] = _now_iso()
        _append_log("[Tunnel] Stopped.")
        log_audit_entry(
            event_type="tunnel_stopped",
            msg="[Tunnel] Tunnel process stopped.",
            status=AuditStatus.SUCCESS,
            details={},
        )
    return get_status(user_uuid=user_uuid)


def autostart_owner_tunnel() -> None:
    try:
        owner_config = config_service.get_owner_default_config()
        if not isinstance(owner_config, dict):
            return

        owner_uuid = owner_config.get("system", {}).get("user_id")
        cfg = _normalize_tunneling_cfg(
            owner_config.get("connector", {}).get("tunneling", {})
        )
        if not cfg.get("enabled"):
            return
        start_tunnel(user_uuid=owner_uuid)
    except Exception as exc:
        log_audit_entry(
            event_type="tunnel_autostart_error",
            msg="[Tunnel] Autostart failed.",
            status=AuditStatus.ERROR,
            details={"error": str(exc)},
        )
