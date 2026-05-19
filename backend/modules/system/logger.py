import json
import os
import sys
import threading
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from constants.paths import LOGS_DIR, TRACEBACK_LOGS_DIR
from modules.system.localization import get_active_language, get_text
from utils.open_file_w_utf8 import open_utf8

TRACEBACK_FILE = os.path.join(TRACEBACK_LOGS_DIR, "runtime_tracebacks.log")

os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(TRACEBACK_LOGS_DIR, exist_ok=True)


def _cleanup_old_log_files(keep_sessions: int = 1) -> None:
    try:
        session_logs = [
            file
            for file in os.listdir(LOGS_DIR)
            if file.endswith("_debug.jsonl")
        ]
        session_logs.sort(
            key=lambda name: os.path.getmtime(os.path.join(LOGS_DIR, name)),
            reverse=True,
        )

        for obsolete in session_logs[keep_sessions:]:
            try:
                os.remove(os.path.join(LOGS_DIR, obsolete))
                print(
                    get_text(
                        "logger.cleanup_removed",
                        params={"file": obsolete},
                        default=f"[Logger] Removed old log file: {obsolete}",
                    )
                )
            except OSError as exc:
                print(
                    get_text(
                        "logger.cleanup_remove_failed",
                        params={"file": obsolete, "error": exc},
                        default=f"[Logger] Failed to remove log file {obsolete}: {exc}",
                    )
                )

        rolling_debug = os.path.join(LOGS_DIR, "debug_log.jsonl")
        if os.path.exists(rolling_debug):
            try:
                os.remove(rolling_debug)
                print(
                    get_text(
                        "logger.cleanup_cleared",
                        default="[Logger] Cleared rolling debug log.",
                    )
                )
            except OSError as exc:
                print(
                    get_text(
                        "logger.cleanup_clear_failed",
                        params={"error": exc},
                        default=f"[Logger] Failed to clear rolling debug log: {exc}",
                    )
                )
    except Exception as exc:
        print(
            get_text(
                "logger.cleanup_failed",
                params={"error": exc},
                default=f"[Logger] Log cleanup failed: {exc}",
            )
        )


SESSION_ID = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

DEBUG_FILE_PER_SESSION = os.path.join(LOGS_DIR, f"{SESSION_ID}_debug.jsonl")
DEBUG_FILE_CURRENT = os.path.join(LOGS_DIR, "debug_log.jsonl")
_LOGGER_INIT_LOCK = threading.Lock()
_LOG_WRITE_LOCK = threading.Lock()
_LOGGER_RUNTIME_INITIALIZED = False


class AuditStatus(str, Enum):
    SUCCESS = "Success"
    ERROR = "Error"
    WARNING = "Warning"
    INFO = "Info"


@dataclass
class AuditLog:
    event_type: str
    msg: str
    status: AuditStatus = AuditStatus.INFO
    details: dict = field(default_factory=dict)
    meta: Optional[dict] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    session_id: str = field(default_factory=lambda: SESSION_ID)
    language: str = field(default_factory=get_active_language)
    message_key: Optional[str] = None

    def as_dict(self) -> dict:
        return asdict(self)


def get_session_id():
    return SESSION_ID


def initialize_log_files():
    for path in [DEBUG_FILE_PER_SESSION, DEBUG_FILE_CURRENT, TRACEBACK_FILE]:
        if not os.path.exists(path):
            with open_utf8(path, "w") as file:
                file.write("")


def initialize_logger_runtime(*, keep_sessions: int = 1) -> None:
    global _LOGGER_RUNTIME_INITIALIZED
    with _LOGGER_INIT_LOCK:
        if _LOGGER_RUNTIME_INITIALIZED:
            return
        _cleanup_old_log_files(keep_sessions=keep_sessions)
        initialize_log_files()
        _LOGGER_RUNTIME_INITIALIZED = True


def _write_jsonl(filepath, record):
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with _LOG_WRITE_LOCK:
        with open_utf8(filepath, "a") as file:
            file.write(line)


def _read_log_lines_lossy(filepath: str) -> list[str]:
    with open(filepath, "rb") as file:
        return file.read().decode("utf-8", errors="replace").splitlines()


def _parse_log_lines(lines: list[str]) -> list[dict]:
    logs: list[dict] = []
    for line in lines:
        raw_line = str(line or "").strip()
        if not raw_line:
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            logs.append(payload)
    return logs


def _default_message_key(event_type: Optional[str]) -> Optional[str]:
    if not event_type:
        return None
    return f"logger.{event_type}"


def _resolve_localized_message(
    event_type: str,
    raw_message: Optional[str],
    message_key: Optional[str],
    message_args: Optional[dict],
) -> tuple[str, Optional[str]]:
    params = message_args or {}
    candidate_key = message_key or _default_message_key(event_type)
    default_message = raw_message if isinstance(raw_message, str) else None

    if candidate_key:
        localized = get_text(candidate_key, params=params, default=default_message)
    else:
        localized = default_message or ""

    if not localized and default_message:
        localized = default_message

    return localized, candidate_key


def log_audit_entry(
    event_type: str,
    msg: str,
    status: AuditStatus = AuditStatus.INFO,
    details: Optional[dict] = None,
    meta: Optional[dict] = None,
    *,
    message_key: Optional[str] = None,
    message_args: Optional[dict] = None,
):
    localized_message, resolved_key = _resolve_localized_message(
        event_type, msg, message_key, message_args
    )

    meta_payload = dict(meta or {})
    if message_args:
        meta_payload.setdefault("message_args", message_args)

    log = AuditLog(
        event_type=event_type,
        msg=localized_message,
        status=status,
        meta=meta_payload,
        details=details or {},
        timestamp=datetime.now().isoformat(timespec="seconds"),
        session_id=SESSION_ID,
        message_key=resolved_key,
    )
    _write_jsonl(DEBUG_FILE_PER_SESSION, log.as_dict())
    _write_jsonl(DEBUG_FILE_CURRENT, log.as_dict())


def log_error(error_msg, context=None, severity="error"):
    with open_utf8(TRACEBACK_FILE, "a") as file:
        file.write(
            f"[{datetime.now().isoformat(timespec='seconds')}] [SESSION: {SESSION_ID}] ERROR: {error_msg}\n"
        )
        if context:
            file.write(f"Context: {context}\n")

    log_audit_entry(
        event_type="error",
        msg=f"Error occurred: {error_msg}",
        status=AuditStatus.ERROR,
        details={"error": error_msg, "context": context},
        meta={"source": "system", "severity": severity, "context": context or {}},
        message_key="logger.error",
        message_args={"error": error_msg},
    )


def log_debug(message, tag="DEBUG"):
    print(f"[{tag}][{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def log_console(component: str, message: str, details: Optional[dict[str, Any]] = None) -> None:
    prefix = f"[{component}]"
    if details:
        try:
            payload = json.dumps(details, ensure_ascii=False, default=str)
        except Exception:
            payload = str(details)
        print(f"{prefix} {message} | {payload}", flush=True)
        return
    print(f"{prefix} {message}", flush=True)


def get_debug_log(limit: Optional[int] = None, offset: int = 0, session_id: Optional[str] = None):
    resolved_session_id = str(session_id or get_session_id()).strip()
    log_file = os.path.join(LOGS_DIR, f"{resolved_session_id}_debug.jsonl")

    if not os.path.exists(log_file):
        return None, resolved_session_id, 0

    try:
        safe_offset = max(int(offset or 0), 0)
        safe_limit: Optional[int]
        if limit is None:
            safe_limit = None
        else:
            safe_limit = max(int(limit), 1)

        lines = _read_log_lines_lossy(log_file)

        total = len(lines)
        if safe_limit is None:
            selected_lines = lines
        else:
            # Stored order in file is oldest -> newest. API returns newest-first page.
            end_idx = max(total - safe_offset, 0)
            start_idx = max(end_idx - safe_limit, 0)
            selected_lines = lines[start_idx:end_idx]

        logs = _parse_log_lines(selected_lines)
        logs.reverse()
        return logs, resolved_session_id, total
    except Exception as exc:
        raise RuntimeError(f"Error reading log: {exc}")


def log_traceback(exc: BaseException, *, source: str = "runtime") -> None:
    traceback_payload = "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )
    with open_utf8(TRACEBACK_FILE, "a") as file:
        file.write(
            f"[{datetime.now().isoformat(timespec='seconds')}] "
            f"[SESSION: {SESSION_ID}] "
            f"[SOURCE: {source}] {type(exc).__name__}: {exc}\n"
        )
        file.write(traceback_payload)
        file.write("\n")


_ORIGINAL_SYS_EXCEPTHOOK = sys.excepthook
_TRACEBACK_HOOKS_INSTALLED = False


def _sys_excepthook(exc_type, exc_value, exc_tb):
    try:
        if exc_value is not None:
            rendered = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            with open_utf8(TRACEBACK_FILE, "a") as file:
                file.write(
                    f"[{datetime.now().isoformat(timespec='seconds')}] "
                    f"[SESSION: {SESSION_ID}] "
                    f"[SOURCE: sys.excepthook] {exc_type.__name__}: {exc_value}\n"
                )
                file.write(rendered)
                file.write("\n")
    except Exception:
        pass

    if _ORIGINAL_SYS_EXCEPTHOOK:
        _ORIGINAL_SYS_EXCEPTHOOK(exc_type, exc_value, exc_tb)


def _threading_excepthook(args):
    try:
        rendered = "".join(
            traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
        )
        with open_utf8(TRACEBACK_FILE, "a") as file:
            file.write(
                f"[{datetime.now().isoformat(timespec='seconds')}] "
                f"[SESSION: {SESSION_ID}] "
                f"[SOURCE: threading.excepthook] "
                f"thread={getattr(args.thread, 'name', 'unknown')} "
                f"{args.exc_type.__name__}: {args.exc_value}\n"
            )
            file.write(rendered)
            file.write("\n")
    except Exception:
        pass


def install_traceback_hooks() -> None:
    global _TRACEBACK_HOOKS_INSTALLED
    if _TRACEBACK_HOOKS_INSTALLED:
        return

    sys.excepthook = _sys_excepthook
    try:
        threading.excepthook = _threading_excepthook
    except Exception:
        pass
    _TRACEBACK_HOOKS_INSTALLED = True


install_traceback_hooks()
