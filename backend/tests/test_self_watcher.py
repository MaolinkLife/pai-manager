"""Tests for Self-Watcher / Meta-cognition (0.9.0 Wave 2, §3.7).

Coverage:
  Classifier:
    * classify_valence: positive labels (RU + EN)
    * classify_valence: negative labels
    * unknown / empty → neutral
  Mismatch scorer:
    * same valence → 0
    * opposite valence (pos vs neg) → ≥ 0.6 scaled by intensity
    * one-side neutral → mild mismatch in [0.2, 0.6]
  Repository:
    * insert + list_recent round-trip
    * list_recent filters by character_id and time window
  Service.check_expectation:
    * disabled → skipped(disabled)
    * no previous prediction → skipped(no_previous_prediction)
    * no user tone → skipped(no_user_tone)
    * below threshold → skipped(below_threshold), NO db write
    * above threshold → recorded=True, event_id present
    * never raises on garbage inputs
  Service.record_nightly_reflection:
    * disabled → None
    * no events → None
    * with events + stub LLM → returns prose, prefix stripping
    * LLM error → None (never raises)
"""

from __future__ import annotations

from datetime import date as date_cls, datetime, timezone

import pytest
from sqlalchemy import text

from modules.database.core import engine, _ensure_expectation_events_table
from modules.self_watcher import (
    check_expectation,
    classify_valence,
    record_nightly_reflection,
    score_mismatch,
)
from modules.self_watcher.repository import SelfWatcherRepository


_TEST_CHAR_PREFIX = "self-watcher-test-"


@pytest.fixture(autouse=True)
def _cleanup():
    _ensure_expectation_events_table()
    yield
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM expectation_events WHERE character_id LIKE :pat"
            ),
            {"pat": f"{_TEST_CHAR_PREFIX}%"},
        )


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_classify_valence_positive_labels():
    assert classify_valence("joy") == "positive"
    assert classify_valence("радость") == "positive"
    assert classify_valence("Tenderness") == "positive"
    assert classify_valence("нежность") == "positive"


@pytest.mark.regression
def test_classify_valence_negative_labels():
    assert classify_valence("anger") == "negative"
    assert classify_valence("обида") == "negative"
    assert classify_valence("Frustrated") == "negative"
    assert classify_valence("тревога") == "negative"


@pytest.mark.regression
def test_classify_valence_unknown_defaults_neutral():
    assert classify_valence("") == "neutral"
    assert classify_valence(None) == "neutral"  # type: ignore[arg-type]
    assert classify_valence("contemplative") == "neutral"
    assert classify_valence("философское") == "neutral"


# ---------------------------------------------------------------------------
# Mismatch scorer
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_score_matching_valences_is_zero():
    assert score_mismatch(
        predicted_valence="positive", actual_valence="positive"
    ) == 0.0
    assert score_mismatch(
        predicted_valence="negative", actual_valence="negative"
    ) == 0.0


@pytest.mark.regression
def test_score_opposite_valences_high():
    s = score_mismatch(
        predicted_valence="positive",
        actual_valence="negative",
        predicted_intensity=0.8,
        actual_intensity=0.8,
    )
    assert s >= 0.6
    assert s <= 1.0


@pytest.mark.regression
def test_score_neutral_vs_emotional_is_mild():
    s = score_mismatch(
        predicted_valence="neutral",
        actual_valence="negative",
        actual_intensity=0.7,
    )
    assert 0.2 <= s <= 0.6


@pytest.mark.regression
def test_score_empty_inputs_returns_zero():
    assert score_mismatch(predicted_valence="", actual_valence="positive") == 0.0
    assert score_mismatch(predicted_valence="positive", actual_valence="") == 0.0


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_repository_insert_and_list():
    repo = SelfWatcherRepository()
    cid = f"{_TEST_CHAR_PREFIX}roundtrip"
    entry_id = repo.insert(
        character_id=cid,
        prev_assistant_message_id="m-prev",
        triggering_user_message_id="m-cur",
        pai_predicted_emotion="joy",
        pai_predicted_valence="positive",
        user_actual_tone="frustration",
        user_actual_valence="negative",
        mismatch_score=0.85,
        notes="test note",
    )
    assert entry_id is not None

    rows = repo.list_recent(character_id=cid)
    assert any(row["id"] == entry_id for row in rows)
    matched = next(row for row in rows if row["id"] == entry_id)
    assert matched["pai_predicted_emotion"] == "joy"
    assert matched["user_actual_valence"] == "negative"
    assert float(matched["mismatch_score"]) == pytest.approx(0.85)


@pytest.mark.regression
def test_repository_list_filters_by_character():
    repo = SelfWatcherRepository()
    cid_a = f"{_TEST_CHAR_PREFIX}A"
    cid_b = f"{_TEST_CHAR_PREFIX}B"
    repo.insert(
        character_id=cid_a,
        prev_assistant_message_id=None,
        triggering_user_message_id=None,
        pai_predicted_emotion="joy",
        pai_predicted_valence="positive",
        user_actual_tone="anger",
        user_actual_valence="negative",
        mismatch_score=0.8,
    )
    repo.insert(
        character_id=cid_b,
        prev_assistant_message_id=None,
        triggering_user_message_id=None,
        pai_predicted_emotion="joy",
        pai_predicted_valence="positive",
        user_actual_tone="anger",
        user_actual_valence="negative",
        mismatch_score=0.8,
    )

    rows_a = repo.list_recent(character_id=cid_a)
    rows_b = repo.list_recent(character_id=cid_b)
    assert all(r["character_id"] == cid_a for r in rows_a)
    assert all(r["character_id"] == cid_b for r in rows_b)


# ---------------------------------------------------------------------------
# Service.check_expectation
# ---------------------------------------------------------------------------


def _enable_self_watcher(monkeypatch, *, threshold: float = 0.5):
    from modules.system import config as config_service

    def _fake_get(key, default=None):
        if key == "self_watcher":
            return {
                "enabled": True,
                "mismatch_threshold": threshold,
                "nightly_reflection_enabled": True,
                "lookback_days": 7,
                "max_events_in_cluster": 20,
                "llm_max_tokens": 220,
                "llm_temperature": 0.5,
            }
        return default

    monkeypatch.setattr(config_service, "get_config_value", _fake_get)


@pytest.mark.regression
def test_check_expectation_disabled(monkeypatch):
    from modules.system import config as config_service

    monkeypatch.setattr(
        config_service,
        "get_config_value",
        lambda key, default=None: {"enabled": False} if key == "self_watcher" else default,
    )
    r = check_expectation(
        character_id=f"{_TEST_CHAR_PREFIX}d",
        prev_assistant_meta={"pai_predicted_emotion": "joy"},
        prev_assistant_message_id="m1",
        current_user_tone="frustration",
    )
    assert r.skipped is True
    assert r.skip_reason == "disabled"


@pytest.mark.regression
def test_check_expectation_no_previous_prediction(monkeypatch):
    _enable_self_watcher(monkeypatch)
    r = check_expectation(
        character_id=f"{_TEST_CHAR_PREFIX}no-prev",
        prev_assistant_meta={},
        prev_assistant_message_id=None,
        current_user_tone="frustration",
    )
    assert r.skipped is True
    assert r.skip_reason == "no_previous_prediction"


@pytest.mark.regression
def test_check_expectation_no_user_tone(monkeypatch):
    _enable_self_watcher(monkeypatch)
    r = check_expectation(
        character_id=f"{_TEST_CHAR_PREFIX}no-tone",
        prev_assistant_meta={"pai_predicted_emotion": "joy"},
        prev_assistant_message_id="m1",
        current_user_tone="",
    )
    assert r.skipped is True
    assert r.skip_reason == "no_user_tone"


@pytest.mark.regression
def test_check_expectation_below_threshold_skipped(monkeypatch):
    _enable_self_watcher(monkeypatch, threshold=0.95)
    # Positive vs negative would score ~0.6 — below 0.95 threshold.
    r = check_expectation(
        character_id=f"{_TEST_CHAR_PREFIX}low",
        prev_assistant_meta={
            "pai_predicted_emotion": "joy",
            "pai_predicted_valence": "positive",
            "pai_predicted_intensity": 0.3,
        },
        prev_assistant_message_id="m1",
        current_user_tone="anger",
        current_user_intensity=0.3,
    )
    assert r.skipped is True
    assert r.skip_reason == "below_threshold"
    assert r.recorded is False


@pytest.mark.regression
def test_check_expectation_records_on_mismatch(monkeypatch):
    _enable_self_watcher(monkeypatch, threshold=0.3)
    cid = f"{_TEST_CHAR_PREFIX}rec"
    r = check_expectation(
        character_id=cid,
        prev_assistant_meta={
            "pai_predicted_emotion": "joy",
            "pai_predicted_valence": "positive",
            "pai_predicted_intensity": 0.7,
        },
        prev_assistant_message_id="prev-1",
        current_user_tone="anger",
        current_user_intensity=0.8,
        triggering_user_message_id="user-1",
    )
    assert r.recorded is True
    assert r.event_id is not None
    assert r.mismatch_score >= 0.6
    assert r.pai_predicted_emotion == "joy"
    assert r.user_actual_valence == "negative"


@pytest.mark.regression
def test_check_expectation_never_raises_on_garbage(monkeypatch):
    _enable_self_watcher(monkeypatch)
    # All possible bad shapes
    for bad_meta in (None, "not a dict", 42, []):
        r = check_expectation(
            character_id=f"{_TEST_CHAR_PREFIX}garbage",
            prev_assistant_meta=bad_meta,  # type: ignore[arg-type]
            prev_assistant_message_id=None,
            current_user_tone="anger",
        )
        assert r.skipped is True


# ---------------------------------------------------------------------------
# Service.record_nightly_reflection
# ---------------------------------------------------------------------------


class _StubResult:
    def __init__(self, content: str) -> None:
        self.content = content
        self.reasoning = ""


@pytest.mark.regression
def test_nightly_reflection_disabled_returns_none(monkeypatch):
    from modules.system import config as config_service

    monkeypatch.setattr(
        config_service,
        "get_config_value",
        lambda key, default=None: {"enabled": False} if key == "self_watcher" else default,
    )
    assert record_nightly_reflection(
        character_id=f"{_TEST_CHAR_PREFIX}d", day=date_cls(2026, 6, 9)
    ) is None


@pytest.mark.regression
def test_nightly_reflection_no_events_returns_none(monkeypatch):
    _enable_self_watcher(monkeypatch)
    assert record_nightly_reflection(
        character_id=f"{_TEST_CHAR_PREFIX}empty", day=date_cls(2026, 6, 9)
    ) is None


@pytest.mark.regression
def test_nightly_reflection_with_events_returns_prose(monkeypatch):
    _enable_self_watcher(monkeypatch, threshold=0.1)
    cid = f"{_TEST_CHAR_PREFIX}nightly"

    # Seed a couple of events.
    repo = SelfWatcherRepository()
    for _ in range(3):
        repo.insert(
            character_id=cid,
            prev_assistant_message_id=None,
            triggering_user_message_id=None,
            pai_predicted_emotion="joy",
            pai_predicted_valence="positive",
            user_actual_tone="anger",
            user_actual_valence="negative",
            mismatch_score=0.8,
        )

    from modules.generative.manager import generation_manager

    monkeypatch.setattr(
        generation_manager,
        "generate",
        lambda req: _StubResult(
            "Reflection: I keep reading laughs as agreement when sometimes they "
            "are just diplomatic noise."
        ),
    )

    text_out = record_nightly_reflection(character_id=cid, day=date_cls(2026, 6, 9))
    assert text_out is not None
    # Prefix should be stripped
    assert not text_out.lower().startswith("reflection:")
    assert "diplomatic noise" in text_out


@pytest.mark.regression
def test_nightly_reflection_llm_error_returns_none(monkeypatch):
    _enable_self_watcher(monkeypatch, threshold=0.1)
    cid = f"{_TEST_CHAR_PREFIX}err"
    repo = SelfWatcherRepository()
    repo.insert(
        character_id=cid,
        prev_assistant_message_id=None,
        triggering_user_message_id=None,
        pai_predicted_emotion="joy",
        pai_predicted_valence="positive",
        user_actual_tone="anger",
        user_actual_valence="negative",
        mismatch_score=0.8,
    )

    from modules.generative.manager import generation_manager

    def _boom(req):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(generation_manager, "generate", _boom)
    assert record_nightly_reflection(character_id=cid, day=date_cls(2026, 6, 9)) is None
