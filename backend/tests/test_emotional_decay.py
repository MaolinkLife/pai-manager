"""Tests for EmotionalTrace decay (0.8.0 Wave 1, step 1).

Cover:
  * decay_emotional_traces decreases intensity proportionally to days elapsed
  * persistence_floor clamps intensity from below
  * resolved=True traces are not touched
  * idempotency: running twice on the same day is a no-op for the second call
  * last_decayed_at is bumped even when value already at floor (so we don't
    re-scan dead rows every night)
  * loop_initiative._run_emotional_decay respects moral.decay.enabled

DB writes go to a temporary SQLite via SessionLocal — same engine the prod
code uses, so the migration is exercised end-to-end. Tests clean up after
themselves.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from models.models import EmotionalTrace
from modules.database.core import SessionLocal, engine
from modules.moral_matrix.repository import MoralMatrixRepository


CHARACTER_ID = "decay-test-character"


@pytest.fixture(autouse=True)
def _cleanup_decay_traces():
    """Remove anything created by this test from emotional_traces after each run."""
    yield
    with SessionLocal() as session:
        session.query(EmotionalTrace).filter(
            EmotionalTrace.character_id == CHARACTER_ID
        ).delete()
        session.commit()


def _insert_trace(
    *,
    intensity: float,
    days_ago: int,
    decay_rate: float = 0.05,
    persistence_floor: float = 0.0,
    resolved: bool = False,
    last_decayed_at=None,
) -> str:
    """Insert a trace with controlled timestamps. Returns the row id."""
    trace_id = str(uuid.uuid4())
    created = datetime.now(timezone.utc) - timedelta(days=days_ago)
    with SessionLocal() as session:
        session.add(
            EmotionalTrace(
                id=trace_id,
                character_id=CHARACTER_ID,
                trigger_role="assistant",
                primary_emotion="sadness",
                intensity=intensity,
                emotion_vector="{}",
                decay_rate=decay_rate,
                persistence_floor=persistence_floor,
                resolved=resolved,
                last_decayed_at=last_decayed_at,
                created_at=created,
            )
        )
        session.commit()
    return trace_id


def _fetch(trace_id: str) -> EmotionalTrace:
    with SessionLocal() as session:
        return session.query(EmotionalTrace).filter(EmotionalTrace.id == trace_id).one()


# ---------------------------------------------------------------------------
# Core decay behaviour
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_decay_reduces_intensity_proportionally_to_days():
    trace_id = _insert_trace(intensity=0.8, days_ago=10, decay_rate=0.05)
    repo = MoralMatrixRepository()
    result = repo.decay_emotional_traces(character_id=CHARACTER_ID, global_rate=0.05)

    assert result["updated"] == 1
    assert result["floored"] == 0

    row = _fetch(trace_id)
    # 0.8 - 0.05 * 10 = 0.3, within float tolerance.
    assert row.intensity == pytest.approx(0.3, abs=1e-6)
    assert row.last_decayed_at is not None


@pytest.mark.regression
def test_decay_respects_persistence_floor():
    trace_id = _insert_trace(intensity=0.4, days_ago=30, decay_rate=0.05, persistence_floor=0.2)
    repo = MoralMatrixRepository()
    result = repo.decay_emotional_traces(character_id=CHARACTER_ID, global_rate=0.05)

    assert result["floored"] == 1
    row = _fetch(trace_id)
    # Without floor 0.4 - 1.5 = -1.1. With floor 0.2.
    assert row.intensity == pytest.approx(0.2, abs=1e-6)


@pytest.mark.regression
def test_decay_skips_resolved_traces():
    trace_id = _insert_trace(intensity=0.7, days_ago=10, resolved=True)
    repo = MoralMatrixRepository()
    result = repo.decay_emotional_traces(character_id=CHARACTER_ID, global_rate=0.05)

    assert result["scanned"] == 0  # resolved excluded from query
    row = _fetch(trace_id)
    assert row.intensity == pytest.approx(0.7, abs=1e-6)


@pytest.mark.regression
def test_decay_per_row_rate_overrides_global():
    trace_id = _insert_trace(intensity=0.8, days_ago=4, decay_rate=0.10)
    repo = MoralMatrixRepository()
    repo.decay_emotional_traces(character_id=CHARACTER_ID, global_rate=0.50)

    row = _fetch(trace_id)
    # Should use row's 0.10, not the global 0.50: 0.8 - 0.10 * 4 = 0.4.
    assert row.intensity == pytest.approx(0.4, abs=1e-6)


@pytest.mark.regression
def test_decay_is_idempotent_when_run_twice_same_day():
    trace_id = _insert_trace(intensity=0.8, days_ago=10)
    repo = MoralMatrixRepository()

    first = repo.decay_emotional_traces(character_id=CHARACTER_ID, global_rate=0.05)
    second = repo.decay_emotional_traces(character_id=CHARACTER_ID, global_rate=0.05)

    assert first["updated"] == 1
    # Second pass: last_decayed_at is "now", so days_elapsed ≈ 0 → no change.
    assert second["updated"] == 0
    row = _fetch(trace_id)
    assert row.intensity == pytest.approx(0.3, abs=1e-6)


@pytest.mark.regression
def test_decay_bumps_last_decayed_for_floored_rows():
    """A trace already at floor should still get last_decayed_at updated,
    otherwise the worker would re-scan it every night for nothing."""
    trace_id = _insert_trace(
        intensity=0.0,
        days_ago=5,
        persistence_floor=0.0,
    )
    repo = MoralMatrixRepository()
    repo.decay_emotional_traces(character_id=CHARACTER_ID, global_rate=0.05)

    row = _fetch(trace_id)
    assert row.last_decayed_at is not None


@pytest.mark.regression
def test_decay_uses_last_decayed_at_when_available():
    """If last_decayed_at exists, days_elapsed is measured from it, not created_at."""
    six_days_ago = datetime.now(timezone.utc) - timedelta(days=6)
    two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
    trace_id = _insert_trace(
        intensity=0.6,
        days_ago=6,
        last_decayed_at=two_days_ago,
        decay_rate=0.05,
    )
    repo = MoralMatrixRepository()
    repo.decay_emotional_traces(character_id=CHARACTER_ID, global_rate=0.05)

    row = _fetch(trace_id)
    # 2 days since last decay, not 6: 0.6 - 0.05 * 2 = 0.5.
    assert row.intensity == pytest.approx(0.5, abs=1e-6)


# ---------------------------------------------------------------------------
# loop_initiative wrapper
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_run_emotional_decay_respects_disabled_flag(monkeypatch):
    """When moral.decay.enabled is False, the worker must skip without touching rows."""
    from loops import loop_initiative

    # Set up a row that would otherwise decay.
    trace_id = _insert_trace(intensity=0.7, days_ago=5)

    def _cfg(path, default=None, user_uuid=None):
        if path == "moral.decay.enabled":
            return False
        return default

    monkeypatch.setattr("modules.system.config.get_config_value", _cfg)

    loop_initiative._run_emotional_decay(character_id=CHARACTER_ID, day_iso="2026-06-08")

    row = _fetch(trace_id)
    assert row.intensity == pytest.approx(0.7, abs=1e-6)
    assert row.last_decayed_at is None


@pytest.mark.regression
def test_run_emotional_decay_invokes_repository_when_enabled(monkeypatch):
    from loops import loop_initiative

    trace_id = _insert_trace(intensity=0.7, days_ago=5)

    def _cfg(path, default=None, user_uuid=None):
        if path == "moral.decay.enabled":
            return True
        if path == "moral.decay.global_rate":
            return 0.05
        return default

    monkeypatch.setattr("modules.system.config.get_config_value", _cfg)

    loop_initiative._run_emotional_decay(character_id=CHARACTER_ID, day_iso="2026-06-08")

    row = _fetch(trace_id)
    # 0.7 - 0.05 * 5 = 0.45.
    assert row.intensity == pytest.approx(0.45, abs=1e-6)
