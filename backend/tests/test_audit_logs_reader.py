"""Tests for the DB-backed get_debug_log reader (0.9.0 Wave 2, step B).

Confirms backward compatibility with the JSONL-era API contract:
  * payload shape unchanged (event_type, msg, status, details, meta,
    timestamp, session_id, language, message_key)
  * newest-first ordering
  * limit + offset paging
  * filtering by session_id
  * graceful fallback to JSONL when the DB read fails / yields nothing
  * 404 case (None, _, 0) preserved when neither store has anything
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from modules.database.core import engine
from modules.system import logger as logger_mod
from modules.system.logger import AuditStatus, get_debug_log, log_audit_entry


TEST_SESSION = f"reader-test-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def _cleanup_test_session_rows():
    yield
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM audit_logs WHERE session_id = :sid"),
            {"sid": TEST_SESSION},
        )


def _insert_rows(count: int, *, session_id: str = TEST_SESSION) -> None:
    """Direct DB inserts so we control timestamps and order without sleeps."""
    import json as _json
    from datetime import datetime, timezone

    with engine.begin() as conn:
        for i in range(count):
            conn.execute(
                text(
                    "INSERT INTO audit_logs "
                    "(id, session_id, event_type, severity, msg, details, meta, "
                    " language, message_key, created_at) "
                    "VALUES (:id, :sid, :ev, :sev, :msg, :det, :met, :lang, :mk, :ts)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "sid": session_id,
                    "ev": "reader_seq",
                    "sev": "info",
                    "msg": f"row-{i}",
                    "det": _json.dumps({"i": i}),
                    "met": "{}",
                    "lang": "en",
                    "mk": None,
                    # Ascending timestamps so 'row-0' is OLDEST, 'row-N' is NEWEST.
                    "ts": datetime(2026, 1, 1, 12, 0, i, tzinfo=timezone.utc),
                },
            )


# ---------------------------------------------------------------------------
# Shape contract
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_payload_keys_match_legacy_jsonl_format():
    _insert_rows(1)
    logs, sid, total = get_debug_log(limit=1, offset=0, session_id=TEST_SESSION)

    assert sid == TEST_SESSION
    assert total == 1
    expected_keys = {
        "event_type",
        "msg",
        "status",
        "details",
        "meta",
        "timestamp",
        "session_id",
        "language",
        "message_key",
    }
    assert set(logs[0].keys()) == expected_keys


@pytest.mark.regression
def test_severity_capitalised_for_backward_compat():
    """JSONL/UI expected ``status: Info/Warning/Error``; DB stores lowercased."""
    log_audit_entry("reader_severity_test", "x", AuditStatus.WARNING)
    log_audit_entry("reader_severity_test", "y", AuditStatus.ERROR)
    log_audit_entry("reader_severity_test", "z", AuditStatus.INFO)

    logs, _, _ = get_debug_log(
        limit=10, offset=0, session_id=logger_mod.get_session_id()
    )
    statuses = {row["status"] for row in logs if row["event_type"] == "reader_severity_test"}
    assert statuses <= {"Info", "Warning", "Error", "Success"}
    assert "Warning" in statuses
    assert "Error" in statuses


@pytest.mark.regression
def test_details_and_meta_returned_as_dict():
    _insert_rows(1)
    logs, _, _ = get_debug_log(limit=1, offset=0, session_id=TEST_SESSION)
    assert isinstance(logs[0]["details"], dict)
    assert isinstance(logs[0]["meta"], dict)
    assert logs[0]["details"] == {"i": 0}


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_newest_first_order():
    _insert_rows(5)
    logs, _, _ = get_debug_log(limit=5, offset=0, session_id=TEST_SESSION)
    # We inserted row-0 (oldest) … row-4 (newest); reader returns newest-first.
    assert [r["msg"] for r in logs] == ["row-4", "row-3", "row-2", "row-1", "row-0"]


@pytest.mark.regression
def test_limit_caps_returned_rows():
    _insert_rows(10)
    logs, _, total = get_debug_log(limit=3, offset=0, session_id=TEST_SESSION)
    assert len(logs) == 3
    assert total == 10  # total reflects full set, not the page


@pytest.mark.regression
def test_offset_skips_newest_rows():
    _insert_rows(5)
    logs, _, total = get_debug_log(limit=2, offset=2, session_id=TEST_SESSION)
    # offset 2 in newest-first order: skip row-4, row-3 → start at row-2.
    assert [r["msg"] for r in logs] == ["row-2", "row-1"]
    assert total == 5


@pytest.mark.regression
def test_no_limit_returns_all():
    _insert_rows(4)
    logs, _, total = get_debug_log(limit=None, offset=0, session_id=TEST_SESSION)
    assert len(logs) == 4
    assert total == 4


@pytest.mark.regression
def test_session_filter_isolates_rows():
    _insert_rows(2, session_id=TEST_SESSION)
    other = f"other-{uuid.uuid4().hex[:8]}"
    _insert_rows(3, session_id=other)

    try:
        logs, _, total = get_debug_log(limit=10, offset=0, session_id=TEST_SESSION)
        assert total == 2
        assert len(logs) == 2
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM audit_logs WHERE session_id = :sid"), {"sid": other}
            )


# ---------------------------------------------------------------------------
# Fallback paths
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_returns_none_when_neither_db_nor_jsonl_have_data(monkeypatch):
    """Pre-existing 404 contract: ``logs is None`` ⇒ route renders 404.
    Happens when an unknown session_id is queried."""
    unknown = f"never-existed-{uuid.uuid4().hex[:8]}"
    logs, sid, total = get_debug_log(limit=5, offset=0, session_id=unknown)
    assert logs is None
    assert sid == unknown
    assert total == 0


@pytest.mark.regression
def test_db_failure_falls_back_to_jsonl(monkeypatch, tmp_path):
    """When the DB query throws, the reader must use the JSONL file silently."""
    fake_session = f"jsonl-only-{uuid.uuid4().hex[:8]}"

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated DB outage")

    monkeypatch.setattr(logger_mod, "_fetch_audit_logs_from_db", _boom)

    # Pretend the JSONL file exists with two rows.
    def _fake_jsonl(session_id, limit, offset):
        assert session_id == fake_session
        return ([{"event_type": "jsonl_row", "msg": "from file", "status": "Info"}], 1)

    monkeypatch.setattr(logger_mod, "_fetch_audit_logs_from_jsonl", _fake_jsonl)

    logs, sid, total = get_debug_log(limit=5, offset=0, session_id=fake_session)
    assert total == 1
    assert logs and logs[0]["event_type"] == "jsonl_row"


@pytest.mark.regression
def test_db_success_skips_jsonl_path(monkeypatch):
    """If DB returned rows we must NOT touch the JSONL fallback — otherwise
    boot-window entries would surface forever."""
    _insert_rows(1)

    jsonl_called = []
    monkeypatch.setattr(
        logger_mod,
        "_fetch_audit_logs_from_jsonl",
        lambda *args, **kwargs: jsonl_called.append(args) or None,
    )

    get_debug_log(limit=5, offset=0, session_id=TEST_SESSION)
    assert jsonl_called == []
