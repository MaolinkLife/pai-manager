"""Tests for prune_audit_logs (0.9.0 Wave 2, step C).

Cover:
  * rows older than age_days[severity] are deleted
  * fresh rows survive the age sweep
  * hard_cap drops the oldest rows when the count exceeds the limit
  * cap=0 disables the hard cap for that severity
  * age_days=0 disables the age sweep for that severity
  * loop_initiative._run_audit_log_retention respects audit_logs.retention.enabled
  * per-severity failure isolates: one bad severity doesn't kill the whole job

DB writes go through SessionLocal directly so we control created_at — no
sleeps needed.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from modules.database.core import engine
from modules.system import logger as logger_mod


TEST_TAG_PREFIX = "retention-test-"


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM audit_logs WHERE event_type LIKE :pat"),
            {"pat": f"{TEST_TAG_PREFIX}%"},
        )
        # The cap tests also use unique severities outside the tag prefix
        # (event_type stays under the prefix, so the above query catches them).
        # But to be defensive against future test renames, also nuke our test
        # session id explicitly.
        conn.execute(
            text("DELETE FROM audit_logs WHERE session_id = :sid"),
            {"sid": "retention-test-session"},
        )


def _insert_row(*, severity: str, days_ago: int, event_type: str = None) -> str:
    """Insert a row with controlled severity and age. Returns row id."""
    row_id = str(uuid.uuid4())
    created = datetime.now(timezone.utc) - timedelta(days=days_ago)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO audit_logs "
                "(id, session_id, event_type, severity, msg, details, meta, "
                " language, message_key, created_at) "
                "VALUES (:id, :sid, :ev, :sev, :msg, '{}', '{}', NULL, NULL, :ts)"
            ),
            {
                "id": row_id,
                "sid": "retention-test-session",
                "ev": event_type or f"{TEST_TAG_PREFIX}{severity}",
                "sev": severity,
                "msg": f"row from {days_ago}d ago",
                "ts": created,
            },
        )
    return row_id


def _row_exists(row_id: str) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text("SELECT 1 FROM audit_logs WHERE id = :id"), {"id": row_id}
            ).first()
        )


def _count_for_severity(severity: str) -> int:
    """Counts only our tagged test rows for ``severity``."""
    with engine.connect() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM audit_logs "
                    "WHERE severity = :sev AND event_type LIKE :pat"
                ),
                {"sev": severity, "pat": f"{TEST_TAG_PREFIX}%"},
            ).scalar()
            or 0
        )


# ---------------------------------------------------------------------------
# Age sweep
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_age_deletes_rows_older_than_threshold(monkeypatch):
    """info severity defaults: age_days=7. Insert at 10 days ago → should die."""
    old_id = _insert_row(severity="info", days_ago=10)
    fresh_id = _insert_row(severity="info", days_ago=2)

    # Constrain prune to just the info bucket so we don't disturb other
    # severities in the shared dev DB.
    monkeypatch.setattr(
        logger_mod,
        "_resolve_retention_policy",
        lambda: ({"info": 7}, {"info": 0}),
    )

    stats = logger_mod.prune_audit_logs()
    assert stats["info"]["age_deleted"] >= 1
    assert _row_exists(old_id) is False
    assert _row_exists(fresh_id) is True


@pytest.mark.regression
def test_age_zero_disables_age_sweep(monkeypatch):
    old_id = _insert_row(severity="info", days_ago=999)

    monkeypatch.setattr(
        logger_mod,
        "_resolve_retention_policy",
        lambda: ({"info": 0}, {"info": 0}),
    )

    logger_mod.prune_audit_logs()
    assert _row_exists(old_id) is True


# ---------------------------------------------------------------------------
# Hard cap
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_hard_cap_drops_oldest_when_exceeded(monkeypatch):
    """Cap = 2. Insert 5 rows under a unique severity so the shared dev DB's
    other rows don't influence the count. The 3 oldest should die; the 2
    newest survive."""
    custom_severity = f"retention_cap_test_{uuid.uuid4().hex[:6]}"
    # ``ids`` ordered oldest → newest.
    ids = [
        _insert_row(severity=custom_severity, days_ago=10 - i) for i in range(5)
    ]

    monkeypatch.setattr(
        logger_mod,
        "_resolve_retention_policy",
        lambda: ({custom_severity: 0}, {custom_severity: 2}),
    )

    stats = logger_mod.prune_audit_logs()
    assert stats[custom_severity]["cap_deleted"] == 3

    assert not _row_exists(ids[0])
    assert not _row_exists(ids[1])
    assert not _row_exists(ids[2])
    assert _row_exists(ids[3])
    assert _row_exists(ids[4])


@pytest.mark.regression
def test_cap_zero_disables_cap(monkeypatch):
    custom_severity = f"retention_cap_off_{uuid.uuid4().hex[:6]}"
    ids = [_insert_row(severity=custom_severity, days_ago=1) for _ in range(3)]

    monkeypatch.setattr(
        logger_mod,
        "_resolve_retention_policy",
        lambda: ({custom_severity: 0}, {custom_severity: 0}),
    )

    logger_mod.prune_audit_logs()
    for row_id in ids:
        assert _row_exists(row_id) is True


# ---------------------------------------------------------------------------
# Per-severity isolation
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_per_severity_failure_does_not_break_others(monkeypatch):
    """Force a failure for one severity and check other severities still run."""
    target_id = _insert_row(severity="warning", days_ago=60)

    monkeypatch.setattr(
        logger_mod,
        "_resolve_retention_policy",
        lambda: (
            {"info": 7, "warning": 30},
            {"info": 0, "warning": 0},
        ),
    )

    # Sabotage SessionLocal only for the info delete by patching a helper that
    # both severities use. The most surgical way is to patch SessionLocal —
    # but that breaks both severities. Instead patch the second-pass remaining
    # count for info to raise. That gets isolated by the per-severity try/except.
    original_session_local = logger_mod.__dict__.get("SessionLocal")
    # We can't easily inject per-severity failure without restructuring code;
    # easier path: force prune_audit_logs to see a malformed policy entry.
    monkeypatch.setattr(
        logger_mod,
        "_resolve_retention_policy",
        lambda: (
            {"info": "not-a-number", "warning": 30},  # int(...) will explode
            {"info": 0, "warning": 0},
        ),
    )

    stats = logger_mod.prune_audit_logs()
    # info bucket records an error string, warning still ran.
    assert "error" in stats["info"]
    assert "error" not in stats["warning"]
    # The 60-day warning row should be gone (warning age = 30 days).
    assert _row_exists(target_id) is False


# ---------------------------------------------------------------------------
# loop_initiative wrapper
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_run_audit_log_retention_respects_disabled_flag(monkeypatch):
    """When audit_logs.retention.enabled=False, the worker must skip."""
    from loops import loop_initiative

    called = []

    def _no_call():
        called.append(True)
        return {}

    monkeypatch.setattr(logger_mod, "prune_audit_logs", _no_call)

    def _cfg(path, default=None, user_uuid=None):
        if path == "audit_logs.retention.enabled":
            return False
        return default

    monkeypatch.setattr("modules.system.config.get_config_value", _cfg)

    loop_initiative._run_audit_log_retention(day_iso="2026-06-08")
    assert called == []


@pytest.mark.regression
def test_run_audit_log_retention_calls_prune_when_enabled(monkeypatch):
    from loops import loop_initiative

    called = []

    def _capture():
        called.append(True)
        return {"info": {"age_deleted": 0, "cap_deleted": 0, "remaining": 0}}

    monkeypatch.setattr(logger_mod, "prune_audit_logs", _capture)

    def _cfg(path, default=None, user_uuid=None):
        if path == "audit_logs.retention.enabled":
            return True
        return default

    monkeypatch.setattr("modules.system.config.get_config_value", _cfg)

    loop_initiative._run_audit_log_retention(day_iso="2026-06-08")
    assert called == [True]
