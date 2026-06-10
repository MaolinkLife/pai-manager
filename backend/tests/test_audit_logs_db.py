"""Tests for audit log DB migration + MODE filtering (0.9.0 Wave 2, step A).

Verifies:
  * log_audit_entry persists rows in audit_logs table
  * Each severity (info/warning/error/success) gets a row in DEV mode
  * _DB_LOGGING_READY flips after first successful write
  * In DB-failure scenario, JSONL fallback still receives the entry
  * MODE=prod drops info/success severity at the API boundary

The MODE env var is read once at module import; the test that needs PROD
behaviour stubs _AUDIT_MODE directly instead of re-importing the module.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from modules.database.core import engine
from modules.system import logger as logger_mod
from modules.system.logger import AuditStatus, log_audit_entry


SESSION_TAG_PREFIX = "audit-test-"


@pytest.fixture(autouse=True)
def _cleanup_audit_rows():
    yield
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM audit_logs WHERE event_type LIKE :pat"),
            {"pat": f"{SESSION_TAG_PREFIX}%"},
        )


def _event(name: str) -> str:
    """Test-scoped event_type tag so we can clean up just our rows."""
    return f"{SESSION_TAG_PREFIX}{name}-{uuid.uuid4().hex[:8]}"


def _count_rows(event_type: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT COUNT(*) FROM audit_logs WHERE event_type = :e"),
                {"e": event_type},
            ).scalar()
            or 0
        )


# ---------------------------------------------------------------------------
# Basic persistence
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_info_entry_lands_in_db():
    name = _event("info")
    log_audit_entry(name, "hi there", AuditStatus.INFO, details={"k": "v"})
    assert _count_rows(name) == 1


@pytest.mark.regression
def test_each_severity_lands_separately():
    for severity in (AuditStatus.INFO, AuditStatus.WARNING, AuditStatus.ERROR, AuditStatus.SUCCESS):
        name = _event(severity.value.lower())
        log_audit_entry(name, "test", severity)
        assert _count_rows(name) == 1


@pytest.mark.regression
def test_details_and_meta_are_json_serialised():
    name = _event("rich")
    log_audit_entry(
        name,
        "rich payload",
        AuditStatus.INFO,
        details={"nested": {"x": 1}, "list": [1, 2, 3]},
        meta={"source": "pytest"},
    )
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT details, meta FROM audit_logs "
                    "WHERE event_type = :e LIMIT 1"
                ),
                {"e": name},
            )
            .one()
            ._mapping
        )
    # Stored as JSON text, value-preserving.
    assert '"nested"' in row["details"]
    assert '"x": 1' in row["details"]
    assert '"source": "pytest"' in row["meta"]


@pytest.mark.regression
def test_db_ready_flag_set_after_first_success():
    """_DB_LOGGING_READY should flip to True after any successful write so
    subsequent calls skip the JSONL dual-write in steady state."""
    name = _event("ready")
    log_audit_entry(name, "x", AuditStatus.INFO)
    assert logger_mod._DB_LOGGING_READY is True


# ---------------------------------------------------------------------------
# JSONL fallback when DB write fails
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_jsonl_fallback_invoked_on_db_failure(monkeypatch):
    """When _try_write_audit_to_db returns False we MUST write to JSONL —
    otherwise the entry would be lost. The boot window also relies on this."""
    captured: list = []

    def _fake_db_write(log):
        return False  # simulate DB unreachable

    def _fake_jsonl(filepath, record):
        captured.append((filepath, record.get("event_type")))

    monkeypatch.setattr(logger_mod, "_try_write_audit_to_db", _fake_db_write)
    monkeypatch.setattr(logger_mod, "_write_jsonl", _fake_jsonl)

    log_audit_entry("boot_window_event", "x", AuditStatus.INFO)

    assert len(captured) == 2  # per-session + rolling
    assert all(rec[1] == "boot_window_event" for rec in captured)


@pytest.mark.regression
def test_jsonl_skipped_in_steady_state(monkeypatch):
    """Once DB writes are healthy, JSONL must NOT be written on every call —
    that's the whole point of the migration."""
    monkeypatch.setattr(logger_mod, "_DB_LOGGING_READY", True)
    monkeypatch.setattr(logger_mod, "_try_write_audit_to_db", lambda log: True)

    jsonl_writes: list = []
    monkeypatch.setattr(
        logger_mod,
        "_write_jsonl",
        lambda filepath, record: jsonl_writes.append(filepath),
    )

    log_audit_entry("steady_state_event", "x", AuditStatus.INFO)
    assert jsonl_writes == []


# ---------------------------------------------------------------------------
# MODE filter
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_prod_mode_drops_info(monkeypatch):
    monkeypatch.setattr(logger_mod, "_AUDIT_MODE", "prod")
    name = _event("prod-info")
    log_audit_entry(name, "should be dropped", AuditStatus.INFO)
    assert _count_rows(name) == 0


@pytest.mark.regression
def test_prod_mode_drops_success(monkeypatch):
    monkeypatch.setattr(logger_mod, "_AUDIT_MODE", "prod")
    name = _event("prod-success")
    log_audit_entry(name, "should be dropped", AuditStatus.SUCCESS)
    assert _count_rows(name) == 0


@pytest.mark.regression
def test_prod_mode_keeps_warning(monkeypatch):
    monkeypatch.setattr(logger_mod, "_AUDIT_MODE", "prod")
    name = _event("prod-warning")
    log_audit_entry(name, "kept", AuditStatus.WARNING)
    assert _count_rows(name) == 1


@pytest.mark.regression
def test_prod_mode_keeps_error(monkeypatch):
    monkeypatch.setattr(logger_mod, "_AUDIT_MODE", "prod")
    name = _event("prod-error")
    log_audit_entry(name, "kept", AuditStatus.ERROR)
    assert _count_rows(name) == 1


@pytest.mark.regression
def test_prod_mode_does_not_touch_jsonl_either(monkeypatch):
    """Dropping in PROD means dropping BOTH DB and JSONL — true silence."""
    monkeypatch.setattr(logger_mod, "_AUDIT_MODE", "prod")

    db_calls = []
    jsonl_calls = []
    monkeypatch.setattr(
        logger_mod,
        "_try_write_audit_to_db",
        lambda log: db_calls.append(log) or True,
    )
    monkeypatch.setattr(
        logger_mod,
        "_write_jsonl",
        lambda filepath, record: jsonl_calls.append(filepath),
    )

    log_audit_entry("prod_silent_event", "no trace", AuditStatus.INFO)

    assert db_calls == []
    assert jsonl_calls == []
