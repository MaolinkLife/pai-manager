import json
import os
import sys
import threading
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from constants.paths import LOGS_DIR, TRACEBACK_LOGS_DIR
from modules.system.localization import get_active_language, get_text
from utils.open_file_w_utf8 import open_utf8

TRACEBACK_FILE = os.path.join(TRACEBACK_LOGS_DIR, "runtime_tracebacks.log")

# MODE controls audit verbosity. Read once at module load — must NOT depend on
# DB-first config because the logger boots before initialize_database().
# Accepted values:
#   "dev"  (default) — log everything (info/warning/error/success).
#   "prod"           — drop info/success, keep warning+ only.
# Anything else falls back to dev for safety.
_AUDIT_MODE = (os.getenv("MODE", "dev") or "dev").strip().lower()
if _AUDIT_MODE not in {"dev", "prod"}:
    _AUDIT_MODE = "dev"

# In PROD these severities are dropped before reaching the DB writer.
_PROD_DROPPED_SEVERITIES = {"info", "success"}

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


# Flag flipped after the first successful DB write — used to decide whether
# to keep dual-writing JSONL on every call (boot window) or to write JSONL
# only when the DB write itself fails (steady state).
_DB_LOGGING_READY = False
_DB_READY_LOCK = threading.Lock()


def _try_write_audit_to_db(log: "AuditLog") -> bool:
    """Persist one AuditLog row in `audit_logs`. Returns True on success.

    Best-effort: any exception (DB not ready, schema not migrated yet, write
    failure under load) is swallowed so the caller can fall back to JSONL.
    The first successful write flips ``_DB_LOGGING_READY`` so subsequent
    successful writes skip the JSONL dual-write.
    """
    global _DB_LOGGING_READY
    try:
        # Imported here so the logger module can be imported at startup —
        # well before SQLAlchemy / config finished initialising.
        from models.models import AuditLogRecord
        from modules.database.core import SessionLocal

        with SessionLocal() as session:
            record = AuditLogRecord(
                id=str(uuid.uuid4()),
                session_id=log.session_id,
                event_type=log.event_type,
                severity=str(log.status.value if hasattr(log.status, "value") else log.status).lower(),
                msg=log.msg or "",
                details=json.dumps(log.details or {}, ensure_ascii=False, default=str),
                meta=json.dumps(log.meta or {}, ensure_ascii=False, default=str),
                language=log.language,
                message_key=log.message_key,
                created_at=datetime.now(timezone.utc),
            )
            session.add(record)
            session.commit()

        if not _DB_LOGGING_READY:
            with _DB_READY_LOCK:
                _DB_LOGGING_READY = True
        return True
    except Exception:
        return False


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
    """Record a runtime audit event.

    Writes go to the ``audit_logs`` table; the JSONL files remain as fallback
    so the boot window (before DB is ready) and DB-write failures are still
    captured. In ``MODE=prod`` the verbose severities (info / success) are
    dropped before reaching either sink.
    """
    severity_label = str(status.value if hasattr(status, "value") else status).lower()
    if _AUDIT_MODE == "prod" and severity_label in _PROD_DROPPED_SEVERITIES:
        return

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

    db_ok = _try_write_audit_to_db(log)
    # JSONL fallback:
    #   * always while DB hasn't accepted a single write yet (boot window)
    #   * always when the current write itself failed
    # Once the DB is healthy, JSONL stays quiet — the file is for emergencies
    # and post-mortems, not for steady-state log volume.
    if not db_ok or not _DB_LOGGING_READY:
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


def _audit_row_to_legacy_dict(row: Any) -> dict:
    """Map an audit_logs row back into the JSONL/AuditLog shape the UI expects.

    Pre-migration the API returned ``{event_type, msg, status, details, meta,
    timestamp, session_id, language, message_key}`` where status had the
    enum value (``Info``/``Warning``/...). The DB stores severity lowercased,
    so we capitalise back for backward compat with the existing frontend.
    """
    def _parse_json(text_value: Any) -> Any:
        if isinstance(text_value, (dict, list)):
            return text_value
        if not isinstance(text_value, str) or not text_value.strip():
            return {}
        try:
            return json.loads(text_value)
        except Exception:
            return {}

    severity = str(getattr(row, "severity", "") or "info").lower()
    status_legacy = severity.capitalize()  # info → Info, warning → Warning, etc.

    created_at = getattr(row, "created_at", None)
    if hasattr(created_at, "isoformat"):
        timestamp_iso = created_at.isoformat(timespec="seconds")
    else:
        timestamp_iso = str(created_at) if created_at else ""

    return {
        "event_type": getattr(row, "event_type", "") or "",
        "msg": getattr(row, "msg", "") or "",
        "status": status_legacy,
        "details": _parse_json(getattr(row, "details", "{}")),
        "meta": _parse_json(getattr(row, "meta", "{}")),
        "timestamp": timestamp_iso,
        "session_id": getattr(row, "session_id", "") or "",
        "language": getattr(row, "language", None),
        "message_key": getattr(row, "message_key", None),
    }


def _fetch_audit_logs_from_db(
    session_id: str, limit: Optional[int], offset: int
) -> tuple[list[dict], int]:
    """Page through audit_logs newest-first. Returns (rows, total)."""
    from models.models import AuditLogRecord
    from modules.database.core import SessionLocal

    safe_offset = max(int(offset or 0), 0)
    safe_limit = max(int(limit), 1) if limit is not None else None

    with SessionLocal() as session:
        base_query = session.query(AuditLogRecord).filter(
            AuditLogRecord.session_id == session_id
        )
        total = base_query.count()

        ordered = base_query.order_by(AuditLogRecord.created_at.desc())
        if safe_limit is not None:
            ordered = ordered.offset(safe_offset).limit(safe_limit)
        rows = ordered.all()

    return [_audit_row_to_legacy_dict(row) for row in rows], total


def _fetch_audit_logs_from_jsonl(
    session_id: str, limit: Optional[int], offset: int
) -> Optional[tuple[list[dict], int]]:
    """Legacy JSONL reader — used only when the DB path failed or the file
    still contains boot-window entries that never made it to the DB.
    Returns None when the file doesn't exist."""
    log_file = os.path.join(LOGS_DIR, f"{session_id}_debug.jsonl")
    if not os.path.exists(log_file):
        return None

    safe_offset = max(int(offset or 0), 0)
    safe_limit = max(int(limit), 1) if limit is not None else None

    lines = _read_log_lines_lossy(log_file)
    total = len(lines)
    if safe_limit is None:
        selected_lines = lines
    else:
        end_idx = max(total - safe_offset, 0)
        start_idx = max(end_idx - safe_limit, 0)
        selected_lines = lines[start_idx:end_idx]

    logs = _parse_log_lines(selected_lines)
    logs.reverse()
    return logs, total


def get_debug_log(limit: Optional[int] = None, offset: int = 0, session_id: Optional[str] = None):
    """Page through audit logs. Returns ``(rows | None, session_id, total)``.

    Reads from the DB first. If the DB query throws (table missing during
    early boot, transient error), falls back to the JSONL file. If neither
    has anything, returns ``(None, session_id, 0)`` so the route can render
    a 404 like before.
    """
    resolved_session_id = str(session_id or get_session_id()).strip()

    try:
        rows, total = _fetch_audit_logs_from_db(resolved_session_id, limit, offset)
    except Exception:
        rows, total = [], 0
        db_query_succeeded = False
    else:
        db_query_succeeded = True

    if db_query_succeeded and total > 0:
        return rows, resolved_session_id, total

    # DB had nothing (or the query failed) — try the JSONL fallback. This
    # covers two cases: the boot window (entries written before DB came up)
    # and an emergency where the DB has been wiped but the operator still
    # needs to inspect the live session.
    fallback = _fetch_audit_logs_from_jsonl(resolved_session_id, limit, offset)
    if fallback is None:
        # Backward-compat: caller (route) treats ``None`` as "session unknown"
        # → 404. Returning [] here would silently turn unknown sessions into
        # empty pages and surprise the existing frontend.
        return None, resolved_session_id, 0

    jsonl_rows, jsonl_total = fallback
    return jsonl_rows, resolved_session_id, jsonl_total


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
