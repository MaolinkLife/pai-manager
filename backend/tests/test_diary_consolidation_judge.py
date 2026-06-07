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


# ---------------------------------------------------------------------------
# Judge parser
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_parse_judge_response_none_or_empty():
    assert diary_module._parse_judge_response(None) == []
    assert diary_module._parse_judge_response("") == []
    assert diary_module._parse_judge_response("   ") == []


@pytest.mark.regression
def test_parse_judge_response_strict_json():
    raw = '{"matches": [{"entry_id": "abc", "action": "merge", "note": "ok"}]}'
    assert diary_module._parse_judge_response(raw) == [
        {"entry_id": "abc", "action": "merge", "note": "ok"}
    ]


@pytest.mark.regression
def test_parse_judge_response_tolerates_fences_and_prose():
    raw = "Sure! ```json\n{\"matches\":[{\"entry_id\":\"x\",\"action\":\"keep_both\",\"note\":\"\"}]}\n``` done."
    assert diary_module._parse_judge_response(raw)[0]["action"] == "keep_both"


@pytest.mark.regression
def test_parse_judge_response_drops_invalid_actions():
    raw = '{"matches": [{"entry_id": "x", "action": "obliterate", "note": "no"}, {"entry_id": "y", "action": "supersede", "note": ""}]}'
    parsed = diary_module._parse_judge_response(raw)
    assert len(parsed) == 1
    assert parsed[0]["action"] == "supersede"


# ---------------------------------------------------------------------------
# Contradiction resolver integration
# ---------------------------------------------------------------------------


@pytest.fixture
def force_judge(monkeypatch):
    state = {
        "enabled": True,
        "provider": "ollama",
        "model": "judge-model",
        "temperature": 0.0,
        "max_tokens": 256,
        "request_timeout": 30,
    }

    def _setter(**overrides):
        state.update(overrides)

    monkeypatch.setattr(diary_module, "_judge_settings", lambda: state)
    return _setter


def _entry_with_contradictions(
    *,
    entry_id: str,
    importance: float = 0.5,
    contradictions: list[str] | None = None,
    summary: str = "summary",
    day: str = "2026-06-02",
) -> DiaryEntry:
    payload: dict[str, Any] = {
        "importance_score": importance,
        "contradictions": list(contradictions or []),
    }
    return DiaryEntry(
        id=entry_id,
        character_id="char-1",
        day=day,
        mood="neutral",
        summary=summary,
        tags=[],
        stats={},
        payload=payload,
        created_at="2026-06-01T00:00:00+00:00",
        updated_at="2026-06-01T00:00:00+00:00",
    )


@pytest.mark.regression
def test_judge_disabled_skips_resolver(stub_diary, force_threshold, monkeypatch):
    force_threshold(0.0)
    monkeypatch.setattr(diary_module, "_judge_settings", lambda: {
        "enabled": False, "provider": "ollama", "model": "", "temperature": 0, "max_tokens": 256, "request_timeout": 30,
    })

    def _no_llm(**_):
        pytest.fail("_call_judge_llm must not run when judge is disabled")

    monkeypatch.setattr(diary_module, "_call_judge_llm", _no_llm)

    stub_diary["entries"] = [
        _entry_with_contradictions(
            entry_id="new",
            contradictions=["older fact about Max"],
        ),
        _entry(entry_id="old", summary="Max works at Foo Inc."),
    ]
    result = diary_module.run_sleeping_consolidation(character_id="char-1")
    assert result["judge_enabled"] is False
    assert result["judge_invocations"] == 0


@pytest.mark.regression
def test_judge_supersede_marks_old_entry(stub_diary, force_threshold, force_judge, monkeypatch):
    force_threshold(0.0)

    captured_payloads: list[dict[str, Any]] = []

    def fake_llm(*, payload, settings):
        captured_payloads.append(payload)
        # Judge picks the old entry to supersede.
        return '{"matches":[{"entry_id":"old","action":"supersede","note":"newer info"}]}'

    monkeypatch.setattr(diary_module, "_call_judge_llm", fake_llm)

    stub_diary["entries"] = [
        _entry_with_contradictions(
            entry_id="new",
            contradictions=["Max changed jobs"],
            summary="Max now works at Bar Co.",
            day="2026-06-02",
        ),
        _entry(entry_id="old", summary="Max works at Foo Inc.", importance=0.7),
    ]
    result = diary_module.run_sleeping_consolidation(character_id="char-1")

    assert result["judge_invocations"] == 1
    assert result["judge_actions"]["supersede"] == 1
    assert result["entries_superseded"] == 1

    # The judge payload must include the recent entries so the LLM can pick.
    assert captured_payloads
    candidate_ids = [c["id"] for c in captured_payloads[0]["recent_entries"]]
    assert "old" in candidate_ids

    # The old entry should now be flagged as superseded_by the new one.
    # Supersede patches arrive in a second pass after the main consolidation
    # loop, so we want the *last* upsert for that summary.
    old_payloads = [
        u["payload"] for u in stub_diary["upserts"] if u["summary"] == "Max works at Foo Inc."
    ]
    assert old_payloads, "expected at least one upsert for the old entry"
    old_payload = old_payloads[-1]
    assert old_payload["pruned"]["reason"] == "superseded_by"
    assert old_payload["pruned"]["by_entry_id"] == "new"


@pytest.mark.regression
def test_judge_merge_records_backlink_on_new_entry(stub_diary, force_threshold, force_judge, monkeypatch):
    force_threshold(0.0)

    monkeypatch.setattr(
        diary_module,
        "_call_judge_llm",
        lambda *, payload, settings: '{"matches":[{"entry_id":"old","action":"merge","note":"related"}]}',
    )

    stub_diary["entries"] = [
        _entry_with_contradictions(
            entry_id="new",
            contradictions=["related earlier theme"],
            summary="New thoughts on the project",
            day="2026-06-02",
        ),
        _entry(entry_id="old", summary="Earlier thoughts on the project", importance=0.7),
    ]
    diary_module.run_sleeping_consolidation(character_id="char-1")

    new_payload = next(
        u["payload"] for u in stub_diary["upserts"] if u["summary"] == "New thoughts on the project"
    )
    assert "old" in (new_payload.get("merged_from") or [])
    # Old entry stays untouched (no pruned marker added by merge).
    old_payload = next(
        u["payload"] for u in stub_diary["upserts"] if u["summary"] == "Earlier thoughts on the project"
    )
    assert "pruned" not in old_payload


@pytest.mark.regression
def test_judge_unknown_entry_id_is_safely_ignored(stub_diary, force_threshold, force_judge, monkeypatch):
    force_threshold(0.0)

    monkeypatch.setattr(
        diary_module,
        "_call_judge_llm",
        lambda *, payload, settings: '{"matches":[{"entry_id":"nonexistent","action":"supersede","note":"x"}]}',
    )

    stub_diary["entries"] = [
        _entry_with_contradictions(entry_id="new", contradictions=["x"]),
    ]
    result = diary_module.run_sleeping_consolidation(character_id="char-1")
    assert result["entries_superseded"] == 0
    # The judge invocation is still recorded; only the application is skipped.
    assert result["judge_invocations"] == 1


@pytest.mark.regression
def test_judge_does_not_overwrite_user_archive(stub_diary, force_threshold, force_judge, monkeypatch):
    force_threshold(0.0)
    monkeypatch.setattr(
        diary_module,
        "_call_judge_llm",
        lambda *, payload, settings: '{"matches":[{"entry_id":"old","action":"supersede","note":"x"}]}',
    )

    user_archived = _entry(entry_id="old", summary="archived", importance=0.7,
                           pruned={"reason": "user_archived", "at": "earlier"})
    stub_diary["entries"] = [
        _entry_with_contradictions(entry_id="new", contradictions=["x"], summary="new"),
        user_archived,
    ]
    diary_module.run_sleeping_consolidation(character_id="char-1")
    old_payload = next(u["payload"] for u in stub_diary["upserts"] if u["summary"] == "archived")
    assert old_payload["pruned"]["reason"] == "user_archived"
