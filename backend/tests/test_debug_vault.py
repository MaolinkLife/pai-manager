"""Tests for debug_vault module (0.9.0 Wave 2, §3.6 step 2).

Cover:
  * insert persists a row with JSON-serialised context/violations/runtime_meta
  * list paginates newest-first
  * list filters by kind and reviewed flag
  * mark_reviewed sets the flag + timestamp + optional note
  * mark_reviewed returns False for unknown id
  * get_entry returns None for unknown id
  * write_vault_entry mirrors an audit_logs row with severity='error'
    referencing the new vault_entry_id
  * write_vault_entry returns None on repository failure (no exception
    leaks to caller)
  * empty kind/summary handled gracefully
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from models.models import DebugVaultEntry
from modules.database.core import engine, SessionLocal
from modules.debug_vault.repository import DebugVaultRepository
from modules.debug_vault import write_vault_entry
from modules.debug_vault import service as vault_service


TEST_TAG_PREFIX = "vault-test-"


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM debug_vault_entries WHERE kind LIKE :pat"),
            {"pat": f"{TEST_TAG_PREFIX}%"},
        )
        conn.execute(
            text("DELETE FROM audit_logs WHERE event_type = :ev"),
            {"ev": "debug_vault_entry_recorded"},
        )


def _kind(label: str) -> str:
    return f"{TEST_TAG_PREFIX}{label}-{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_insert_persists_serialised_payload():
    repo = DebugVaultRepository()
    entry_id = repo.insert(
        kind=_kind("payload"),
        summary="serialisation",
        context={"nested": {"x": 1}, "msg": "hi"},
        output="model said X",
        violations=["used forbidden word", "ignored MUST clause"],
        runtime_meta={"latency_ms": 420, "provider": "ollama"},
    )

    fresh = repo.get(entry_id)
    assert fresh is not None
    assert fresh["context"] == {"nested": {"x": 1}, "msg": "hi"}
    assert fresh["violations"] == ["used forbidden word", "ignored MUST clause"]
    assert fresh["runtime_meta"]["provider"] == "ollama"
    assert fresh["output"] == "model said X"
    assert fresh["reviewed"] is False


@pytest.mark.regression
def test_list_newest_first():
    repo = DebugVaultRepository()
    kind = _kind("order")
    ids = [repo.insert(kind=kind, summary=f"row-{i}") for i in range(3)]
    page = repo.list(kind=kind, limit=10)

    # Newest insert (last id) should appear first.
    returned_ids = [row["id"] for row in page["rows"]]
    assert returned_ids == ids[::-1]
    assert page["total"] == 3


@pytest.mark.regression
def test_list_filters_by_kind():
    repo = DebugVaultRepository()
    a = _kind("kindA")
    b = _kind("kindB")
    repo.insert(kind=a, summary="x")
    repo.insert(kind=b, summary="y")
    repo.insert(kind=b, summary="z")

    page = repo.list(kind=b, limit=10)
    assert page["total"] == 2
    assert all(row["kind"] == b for row in page["rows"])


@pytest.mark.regression
def test_list_filters_by_reviewed_flag():
    repo = DebugVaultRepository()
    kind = _kind("reviewfilter")
    repo.insert(kind=kind, summary="unreviewed-1")
    rid = repo.insert(kind=kind, summary="will be reviewed")
    repo.insert(kind=kind, summary="unreviewed-2")
    repo.mark_reviewed(rid)

    unreviewed = repo.list(kind=kind, reviewed=False)
    reviewed = repo.list(kind=kind, reviewed=True)

    assert unreviewed["total"] == 2
    assert reviewed["total"] == 1
    assert reviewed["rows"][0]["id"] == rid


@pytest.mark.regression
def test_list_pagination_respects_limit_and_offset():
    repo = DebugVaultRepository()
    kind = _kind("page")
    ids = [repo.insert(kind=kind, summary=f"r{i}") for i in range(5)]

    page1 = repo.list(kind=kind, limit=2, offset=0)
    page2 = repo.list(kind=kind, limit=2, offset=2)
    page3 = repo.list(kind=kind, limit=2, offset=4)

    assert [row["id"] for row in page1["rows"]] == [ids[4], ids[3]]
    assert [row["id"] for row in page2["rows"]] == [ids[2], ids[1]]
    assert [row["id"] for row in page3["rows"]] == [ids[0]]
    # total remains the full set count regardless of page.
    assert page1["total"] == 5
    assert page3["total"] == 5


@pytest.mark.regression
def test_mark_reviewed_sets_flag_and_note():
    repo = DebugVaultRepository()
    kind = _kind("review")
    entry_id = repo.insert(kind=kind, summary="anomaly")
    ok = repo.mark_reviewed(entry_id, note="checked, false positive")
    assert ok is True

    fresh = repo.get(entry_id)
    assert fresh["reviewed"] is True
    assert fresh["reviewed_at"] is not None
    assert fresh["reviewed_note"] == "checked, false positive"


@pytest.mark.regression
def test_mark_reviewed_unknown_id_returns_false():
    repo = DebugVaultRepository()
    assert repo.mark_reviewed("nonexistent") is False


@pytest.mark.regression
def test_get_unknown_id_returns_none():
    repo = DebugVaultRepository()
    assert repo.get("nonexistent") is None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_write_vault_entry_mirrors_audit_log():
    """write_vault_entry must record both the vault row AND an audit_logs row
    so the debug UI can find the entry from either side."""
    kind = _kind("mirror")
    entry_id = write_vault_entry(
        kind=kind,
        summary="duplex test",
        context={"input": "x"},
        violations=["v1"],
        runtime_meta={"run_id": "rid-123"},
    )
    assert entry_id is not None

    with engine.connect() as conn:
        # The audit_logs row must exist with the vault_entry_id in details JSON.
        rows = conn.execute(
            text(
                "SELECT details FROM audit_logs "
                "WHERE event_type = 'debug_vault_entry_recorded' "
                "ORDER BY created_at DESC LIMIT 5"
            )
        ).fetchall()

    # At least one row must mention our entry_id.
    assert any(entry_id in (row[0] or "") for row in rows)


@pytest.mark.regression
def test_write_vault_entry_returns_none_on_repository_failure(monkeypatch):
    """A broken vault must NEVER raise into the generation pipeline."""

    def _boom(**kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(
        vault_service.debug_vault_repository, "insert", _boom
    )

    result = write_vault_entry(kind=_kind("fail"), summary="should not raise")
    assert result is None


@pytest.mark.regression
def test_insert_handles_empty_kind_gracefully():
    """Defensive: empty kind shouldn't break the index — it's coerced to a
    placeholder string."""
    repo = DebugVaultRepository()
    entry_id = repo.insert(kind="", summary="x")
    fresh = repo.get(entry_id)
    assert fresh["kind"] == "unspecified"
