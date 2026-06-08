"""Tests for the forgiveness mechanism (0.8.0 Wave 1, step 2).

Cover:
  * register_forgiveness reduces target intensity by delta_intensity
  * persistence_floor clamps the resulting intensity
  * crossing the floor flips resolved=True and triggered_resolve in the event
  * delta beyond (intensity - floor) is clipped; applied < requested
  * resolved=True traces are excluded from "unresolved negative" candidates
  * fetch_forgiveness_events filters by trace_id when given
  * service-level heuristic: warm tone + recent negative trace → softened
  * service-level heuristic: warm tone + no candidates → no-op
  * service-level heuristic: neutral tone → no-op
  * disabled config short-circuits the whole pass
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from models.models import EmotionalTrace, ForgivenessEvent
from modules.database.core import SessionLocal
from modules.moral_matrix.repository import MoralMatrixRepository
from modules.moral_matrix import service as service_mod


CHARACTER_ID = "forgiveness-test-character"


@pytest.fixture(autouse=True)
def _cleanup_traces():
    yield
    with SessionLocal() as session:
        session.query(ForgivenessEvent).filter(
            ForgivenessEvent.character_id == CHARACTER_ID
        ).delete()
        session.query(EmotionalTrace).filter(
            EmotionalTrace.character_id == CHARACTER_ID
        ).delete()
        session.commit()


def _insert_trace(
    *,
    intensity: float = 0.8,
    primary_emotion: str = "sadness",
    persistence_floor: float = 0.0,
    resolved: bool = False,
    days_ago: int = 1,
) -> str:
    trace_id = str(uuid.uuid4())
    created = datetime.now(timezone.utc) - timedelta(days=days_ago)
    with SessionLocal() as session:
        session.add(
            EmotionalTrace(
                id=trace_id,
                character_id=CHARACTER_ID,
                trigger_role="assistant",
                primary_emotion=primary_emotion,
                intensity=intensity,
                emotion_vector="{}",
                persistence_floor=persistence_floor,
                resolved=resolved,
                created_at=created,
            )
        )
        session.commit()
    return trace_id


def _fetch_trace(trace_id: str) -> EmotionalTrace:
    with SessionLocal() as session:
        return session.query(EmotionalTrace).filter(EmotionalTrace.id == trace_id).one()


# ---------------------------------------------------------------------------
# register_forgiveness
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_register_forgiveness_reduces_intensity():
    trace_id = _insert_trace(intensity=0.8)
    repo = MoralMatrixRepository()
    result = repo.register_forgiveness(
        CHARACTER_ID,
        trace_id=trace_id,
        cause="warm message",
        compensating_action="user said sorry",
        delta_intensity=0.2,
    )

    assert result is not None
    assert result["delta_applied"] == pytest.approx(0.2)
    assert result["new_intensity"] == pytest.approx(0.6)
    assert result["triggered_resolve"] is False

    row = _fetch_trace(trace_id)
    assert row.intensity == pytest.approx(0.6)
    assert row.resolved is False


@pytest.mark.regression
def test_register_forgiveness_clamps_to_persistence_floor():
    """Delta beyond (intensity - floor) is clipped — emotion never goes below floor."""
    trace_id = _insert_trace(intensity=0.5, persistence_floor=0.3)
    repo = MoralMatrixRepository()
    result = repo.register_forgiveness(
        CHARACTER_ID,
        trace_id=trace_id,
        cause="very warm",
        compensating_action="extended care",
        delta_intensity=0.5,  # would push to -0.0 without floor
    )

    assert result["delta_applied"] == pytest.approx(0.2)  # only the remaining gap
    assert result["new_intensity"] == pytest.approx(0.3)
    assert result["triggered_resolve"] is True

    row = _fetch_trace(trace_id)
    assert row.intensity == pytest.approx(0.3)
    assert row.resolved is True


@pytest.mark.regression
def test_register_forgiveness_event_persists_with_applied_delta():
    trace_id = _insert_trace(intensity=0.4, persistence_floor=0.1)
    repo = MoralMatrixRepository()
    repo.register_forgiveness(
        CHARACTER_ID,
        trace_id=trace_id,
        cause="warmth",
        compensating_action="took a walk together",
        delta_intensity=0.15,
    )
    events = repo.fetch_forgiveness_events(CHARACTER_ID, trace_id=trace_id)
    assert len(events) == 1
    assert events[0]["delta_intensity"] == pytest.approx(0.15)
    assert events[0]["compensating_action"] == "took a walk together"


@pytest.mark.regression
def test_register_forgiveness_returns_none_for_missing_trace():
    repo = MoralMatrixRepository()
    assert (
        repo.register_forgiveness(
            CHARACTER_ID,
            trace_id="nonexistent",
            cause="x",
            compensating_action="x",
            delta_intensity=0.1,
        )
        is None
    )


@pytest.mark.regression
def test_register_forgiveness_rejects_non_positive_delta():
    trace_id = _insert_trace(intensity=0.5)
    repo = MoralMatrixRepository()
    assert (
        repo.register_forgiveness(
            CHARACTER_ID,
            trace_id=trace_id,
            cause="x",
            compensating_action="x",
            delta_intensity=0.0,
        )
        is None
    )


# ---------------------------------------------------------------------------
# fetch_unresolved_negative_traces
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_fetch_unresolved_negative_traces_filters_resolved():
    _insert_trace(intensity=0.5, primary_emotion="sadness", resolved=False, days_ago=1)
    resolved_id = _insert_trace(intensity=0.5, primary_emotion="sadness", resolved=True, days_ago=1)

    repo = MoralMatrixRepository()
    rows = repo.fetch_unresolved_negative_traces(
        CHARACTER_ID,
        emotions=["sadness"],
        within_days=30,
    )
    ids = [r["id"] for r in rows]
    assert resolved_id not in ids


@pytest.mark.regression
def test_fetch_unresolved_negative_traces_filters_emotions():
    sad_id = _insert_trace(primary_emotion="sadness")
    _insert_trace(primary_emotion="joy")  # positive — should not match

    repo = MoralMatrixRepository()
    rows = repo.fetch_unresolved_negative_traces(
        CHARACTER_ID,
        emotions=["sadness", "anger"],
    )
    ids = [r["id"] for r in rows]
    assert sad_id in ids
    assert len(ids) == 1


@pytest.mark.regression
def test_fetch_unresolved_negative_traces_respects_window():
    old_id = _insert_trace(primary_emotion="sadness", days_ago=60)
    fresh_id = _insert_trace(primary_emotion="sadness", days_ago=5)

    repo = MoralMatrixRepository()
    rows = repo.fetch_unresolved_negative_traces(
        CHARACTER_ID,
        emotions=["sadness"],
        within_days=30,
    )
    ids = [r["id"] for r in rows]
    assert fresh_id in ids
    assert old_id not in ids


# ---------------------------------------------------------------------------
# Service-level heuristic
# ---------------------------------------------------------------------------


@pytest.fixture
def force_forgiveness_cfg(monkeypatch):
    """Force a known forgiveness config regardless of DB state."""
    state = {
        "moral.forgiveness.enabled": True,
        "moral.forgiveness.compensating_tones": ["warm", "apologetic"],
        "moral.forgiveness.softenable_emotions": ["sadness", "resentment"],
        "moral.forgiveness.delta_per_event": 0.15,
        "moral.forgiveness.lookback_days": 30,
    }

    def _setter(**overrides):
        state.update(overrides)

    def _cfg(path, default=None, user_uuid=None):
        return state.get(path, default)

    monkeypatch.setattr(service_mod.config_service, "get_config_value", _cfg)
    return _setter


@pytest.mark.regression
def test_heuristic_warm_tone_softens_recent_negative(force_forgiveness_cfg):
    trace_id = _insert_trace(intensity=0.6, primary_emotion="sadness")

    module = service_mod.MoralMatrixModule.__new__(service_mod.MoralMatrixModule)
    module._repository = MoralMatrixRepository()

    module._apply_heuristic_forgiveness(
        character_id=CHARACTER_ID,
        analyzer_emotion={"primary": "warm", "secondary": []},
        user_message_text="Прости меня, я был не прав",
    )

    row = _fetch_trace(trace_id)
    assert row.intensity == pytest.approx(0.45, abs=1e-6)  # 0.6 - 0.15


@pytest.mark.regression
def test_heuristic_secondary_tone_also_matches(force_forgiveness_cfg):
    trace_id = _insert_trace(intensity=0.6, primary_emotion="sadness")

    module = service_mod.MoralMatrixModule.__new__(service_mod.MoralMatrixModule)
    module._repository = MoralMatrixRepository()

    module._apply_heuristic_forgiveness(
        character_id=CHARACTER_ID,
        analyzer_emotion={"primary": "neutral", "secondary": ["apologetic"]},
        user_message_text="ok",
    )

    row = _fetch_trace(trace_id)
    assert row.intensity == pytest.approx(0.45, abs=1e-6)


@pytest.mark.regression
def test_heuristic_neutral_tone_noop(force_forgiveness_cfg):
    trace_id = _insert_trace(intensity=0.6, primary_emotion="sadness")

    module = service_mod.MoralMatrixModule.__new__(service_mod.MoralMatrixModule)
    module._repository = MoralMatrixRepository()

    module._apply_heuristic_forgiveness(
        character_id=CHARACTER_ID,
        analyzer_emotion={"primary": "neutral", "secondary": []},
        user_message_text="hello",
    )

    row = _fetch_trace(trace_id)
    assert row.intensity == pytest.approx(0.6)


@pytest.mark.regression
def test_heuristic_no_candidates_noop(force_forgiveness_cfg):
    """No unresolved negative traces in window → nothing to soften."""
    # No traces inserted.
    module = service_mod.MoralMatrixModule.__new__(service_mod.MoralMatrixModule)
    module._repository = MoralMatrixRepository()

    # Should not raise.
    module._apply_heuristic_forgiveness(
        character_id=CHARACTER_ID,
        analyzer_emotion={"primary": "warm", "secondary": []},
        user_message_text="warm message",
    )


@pytest.mark.regression
def test_heuristic_disabled_short_circuits(force_forgiveness_cfg, monkeypatch):
    force_forgiveness_cfg(**{"moral.forgiveness.enabled": False})
    trace_id = _insert_trace(intensity=0.6, primary_emotion="sadness")

    module = service_mod.MoralMatrixModule.__new__(service_mod.MoralMatrixModule)
    module._repository = MoralMatrixRepository()

    module._apply_heuristic_forgiveness(
        character_id=CHARACTER_ID,
        analyzer_emotion={"primary": "warm", "secondary": []},
        user_message_text="warm message",
    )

    row = _fetch_trace(trace_id)
    assert row.intensity == pytest.approx(0.6)


@pytest.mark.regression
def test_heuristic_crossing_floor_marks_resolved(force_forgiveness_cfg):
    """Trace near the floor: forgiveness flips resolved=True."""
    trace_id = _insert_trace(intensity=0.20, primary_emotion="sadness", persistence_floor=0.10)

    module = service_mod.MoralMatrixModule.__new__(service_mod.MoralMatrixModule)
    module._repository = MoralMatrixRepository()

    module._apply_heuristic_forgiveness(
        character_id=CHARACTER_ID,
        analyzer_emotion={"primary": "warm", "secondary": []},
        user_message_text="thanks for being patient",
    )

    row = _fetch_trace(trace_id)
    assert row.intensity == pytest.approx(0.10)
    assert row.resolved is True
