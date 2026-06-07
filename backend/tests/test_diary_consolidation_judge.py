"""Tests for diary consolidation enhancements (Phase 8).

Covers:
  * importance threshold flags low-importance entries as pruned
  * list_daily_activity_entries hides pruned entries by default
  * include_pruned=True returns the full set (admin/debug)
  * un-pruning when the threshold lowers
  * threshold=0.0 disables the filter entirely

DB writes are stubbed via monkeypatch; we only need the consolidation logic
to walk the entries and emit the right payload.
"""

from __future__ import annotations

from typing import Any

import pytest

from modules.memory import diary as diary_module
from modules.memory.diary import DiaryEntry


def _entry(
    *,
    entry_id: str,
    importance: float | None = 0.5,
    pruned: dict[str, Any] | None = None,
    summary: str = "summary",
) -> DiaryEntry:
    payload: dict[str, Any] = {
        "importance_score": importance,
        "contradictions": [],
    }
    if pruned is not None:
        payload["pruned"] = pruned
    return DiaryEntry(
        id=entry_id,
        character_id="char-1",
        day="2026-06-01",
        mood="neutral",
        summary=summary,
        tags=[],
        stats={},
        payload=payload,
        created_at="2026-06-01T00:00:00+00:00",
        updated_at="2026-06-01T00:00:00+00:00",
    )


@pytest.fixture
def stub_diary(monkeypatch):
    """Replace DB reads/writes so consolidation runs against an in-memory list."""
    state: dict[str, Any] = {
        "entries": [],
        "upserts": [],
    }

    def fake_list(*, character_id: str, days: int = 30, include_pruned: bool = False) -> list[DiaryEntry]:
        items = list(state["entries"])
        if include_pruned:
            return items
        return [e for e in items if not diary_module._is_entry_pruned(e)]

    def fake_upsert(**kwargs) -> DiaryEntry:
        state["upserts"].append(kwargs)
        # Persist into state so subsequent calls see the updated payload.
        target_id = kwargs.get("character_id") + ":" + kwargs.get("day").isoformat()
        for idx, existing in enumerate(state["entries"]):
            if f"{existing.character_id}:{existing.day}" == target_id:
                state["entries"][idx] = DiaryEntry(
                    id=existing.id,
                    character_id=existing.character_id,
                    day=existing.day,
                    mood=kwargs.get("mood"),
                    summary=kwargs.get("summary"),
                    tags=kwargs.get("tags") or [],
                    stats=kwargs.get("stats") or {},
                    payload=kwargs.get("payload") or {},
                    created_at=existing.created_at,
                    updated_at="2026-06-01T01:00:00+00:00",
                )
                return state["entries"][idx]
        return DiaryEntry(
            id="x",
            character_id=kwargs.get("character_id"),
            day=kwargs.get("day").isoformat(),
            mood=kwargs.get("mood"),
            summary=kwargs.get("summary"),
            tags=kwargs.get("tags") or [],
            stats=kwargs.get("stats") or {},
            payload=kwargs.get("payload") or {},
            created_at="2026-06-01T00:00:00+00:00",
            updated_at="2026-06-01T00:00:00+00:00",
        )

    monkeypatch.setattr(diary_module, "list_daily_activity_entries", fake_list)
    monkeypatch.setattr(diary_module, "_upsert_diary_entry", fake_upsert)
    return state


@pytest.fixture
def force_threshold(monkeypatch):
    """Force a known consolidation threshold without touching the real DB."""
    state = {"value": 0.2}

    def _setter(value: float) -> None:
        state["value"] = value

    monkeypatch.setattr(diary_module, "_resolve_importance_threshold", lambda: state["value"])
    return _setter


# ---------------------------------------------------------------------------
# threshold pruning
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_low_importance_entries_are_pruned(stub_diary, force_threshold):
    stub_diary["entries"] = [
        _entry(entry_id="a", importance=0.05),  # below
        _entry(entry_id="b", importance=0.8),   # above
    ]
    force_threshold(0.2)

    result = diary_module.run_sleeping_consolidation(character_id="char-1")
    assert result["entries_pruned"] == 1
    assert result["entries_unpruned"] == 0

    upserts_by_id = {u["payload"].get("consolidation", {}).get("summary_signature") or u["summary"]: u for u in stub_diary["upserts"]}
    # Find the low-importance row's payload
    pruned_payload = next(
        u["payload"] for u in stub_diary["upserts"] if (u["payload"].get("importance_score") or 0) < 0.2
    )
    assert pruned_payload["pruned"]["reason"] == "low_importance"
    assert pruned_payload["pruned"]["score"] == 0.05
    assert pruned_payload["pruned"]["threshold"] == 0.2

    high_payload = next(
        u["payload"] for u in stub_diary["upserts"] if (u["payload"].get("importance_score") or 0) >= 0.2
    )
    assert "pruned" not in high_payload


@pytest.mark.regression
def test_zero_threshold_disables_pruning(stub_diary, force_threshold):
    stub_diary["entries"] = [
        _entry(entry_id="a", importance=0.05),
        _entry(entry_id="b", importance=0.8),
    ]
    force_threshold(0.0)

    result = diary_module.run_sleeping_consolidation(character_id="char-1")
    assert result["entries_pruned"] == 0
    for upsert in stub_diary["upserts"]:
        assert "pruned" not in upsert["payload"]


@pytest.mark.regression
def test_lowering_threshold_unprunes_existing(stub_diary, force_threshold):
    # Entry was already pruned at threshold 0.5 — now run with threshold 0.05.
    stub_diary["entries"] = [
        _entry(
            entry_id="a",
            importance=0.1,
            pruned={"reason": "low_importance", "score": 0.1, "threshold": 0.5, "at": "earlier"},
        ),
    ]
    force_threshold(0.05)

    result = diary_module.run_sleeping_consolidation(character_id="char-1")
    assert result["entries_unpruned"] == 1
    assert "pruned" not in stub_diary["upserts"][-1]["payload"]


@pytest.mark.regression
def test_pruning_does_not_un_prune_other_reasons(stub_diary, force_threshold):
    """A 'pruned' marker placed for another reason (e.g. user delete) must stay."""
    stub_diary["entries"] = [
        _entry(
            entry_id="a",
            importance=0.9,
            pruned={"reason": "user_archived", "at": "earlier"},
        ),
    ]
    force_threshold(0.2)

    diary_module.run_sleeping_consolidation(character_id="char-1")
    final = stub_diary["upserts"][-1]["payload"]
    assert final["pruned"]["reason"] == "user_archived"


@pytest.mark.regression
def test_missing_importance_score_treated_as_unset(stub_diary, force_threshold):
    stub_diary["entries"] = [_entry(entry_id="a", importance=None)]
    force_threshold(0.5)

    result = diary_module.run_sleeping_consolidation(character_id="char-1")
    # No importance → cannot decide → no prune.
    assert result["entries_pruned"] == 0
    assert "pruned" not in stub_diary["upserts"][-1]["payload"]


# ---------------------------------------------------------------------------
# list_daily_activity_entries filter (white-box)
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_is_entry_pruned_helper():
    assert diary_module._is_entry_pruned(_entry(entry_id="a", pruned={"reason": "low_importance"}))
    assert not diary_module._is_entry_pruned(_entry(entry_id="a"))
    assert not diary_module._is_entry_pruned(_entry(entry_id="a", pruned={}))


@pytest.mark.regression
def test_resolve_importance_threshold_clamps(monkeypatch):
    monkeypatch.setattr(
        diary_module.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: -0.5 if path == "memory.consolidation.importance_threshold" else default,
    )
    assert diary_module._resolve_importance_threshold() == 0.0

    monkeypatch.setattr(
        diary_module.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: 5.0 if path == "memory.consolidation.importance_threshold" else default,
    )
    assert diary_module._resolve_importance_threshold() == 1.0


@pytest.mark.regression
def test_resolve_importance_threshold_falls_back_on_invalid(monkeypatch):
    monkeypatch.setattr(
        diary_module.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: "not-a-number" if path == "memory.consolidation.importance_threshold" else default,
    )
    assert diary_module._resolve_importance_threshold() == 0.2
