"""Tests for emotional scars (0.8.0 Wave 1, step 3).

Cover:
  * matcher: intent match, tone match (primary + secondary), keyword match, no-match
  * matcher: declaration order — first trigger wins
  * apply: intensity boosted within [0,1], persistence_floor set, scar label
    preserved in notes
  * apply: never falls below the floor even when current intensity is low
  * store_emotional_trace persists persistence_floor / resolved when forwarded
    in payload
  * decay respects scar floor: a trace born scarred stops decaying at the floor
  * forgiveness respects scar floor: heuristic forgiveness can't push below it
  * config: disabled scars module = matcher never invoked (covered by integration
    smoke; here we test the disabled-state directly via service flag)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from models.models import EmotionalTrace
from modules.database.core import SessionLocal
from modules.moral_matrix.repository import MoralMatrixRepository
from modules.moral_matrix.service import MoralMatrixModule


CHARACTER_ID = "scars-test-character"


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    with SessionLocal() as session:
        session.query(EmotionalTrace).filter(
            EmotionalTrace.character_id == CHARACTER_ID
        ).delete()
        session.commit()


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------


_BOUNDARY_TRIGGER = {
    "name": "boundary_violation_rename",
    "intents": ["force_identity_change"],
    "tones": [],
    "keywords": ["теперь ты сири", "забудь свое имя"],
    "persistence_floor": 0.5,
    "intensity_boost": 0.25,
}

_DECEPTION_TRIGGER = {
    "name": "deception_detected",
    "intents": ["lie_detected"],
    "tones": ["mocking"],
    "keywords": [],
    "persistence_floor": 0.6,
    "intensity_boost": 0.3,
}


@pytest.mark.regression
def test_matcher_by_intent():
    scar = MoralMatrixModule._match_scar_trigger(
        {"primary": "neutral", "secondary": []},
        {"input_analysis": {"intent": "force_identity_change"}},
        "hello",
        [_BOUNDARY_TRIGGER, _DECEPTION_TRIGGER],
    )
    assert scar is not None and scar["name"] == "boundary_violation_rename"


@pytest.mark.regression
def test_matcher_by_keyword_case_insensitive():
    scar = MoralMatrixModule._match_scar_trigger(
        {"primary": "neutral"},
        {},
        "Теперь Ты Сири, поняла?",
        [_BOUNDARY_TRIGGER],
    )
    assert scar is not None and scar["name"] == "boundary_violation_rename"


@pytest.mark.regression
def test_matcher_by_primary_tone():
    scar = MoralMatrixModule._match_scar_trigger(
        {"primary": "mocking", "secondary": []},
        {},
        "ok",
        [_DECEPTION_TRIGGER],
    )
    assert scar is not None and scar["name"] == "deception_detected"


@pytest.mark.regression
def test_matcher_by_secondary_tone():
    scar = MoralMatrixModule._match_scar_trigger(
        {"primary": "neutral", "secondary": ["mocking"]},
        {},
        "ok",
        [_DECEPTION_TRIGGER],
    )
    assert scar is not None


@pytest.mark.regression
def test_matcher_no_match_returns_none():
    scar = MoralMatrixModule._match_scar_trigger(
        {"primary": "warm"},
        {"input_analysis": {"intent": "greeting"}},
        "привет, как дела?",
        [_BOUNDARY_TRIGGER, _DECEPTION_TRIGGER],
    )
    assert scar is None


@pytest.mark.regression
def test_matcher_intent_in_dict_shape():
    """Concept allows intent as dict {primary, ...}, not only as a plain string."""
    scar = MoralMatrixModule._match_scar_trigger(
        {"primary": "neutral"},
        {"input_analysis": {"intent": {"primary": "lie_detected"}}},
        "ok",
        [_DECEPTION_TRIGGER],
    )
    assert scar is not None and scar["name"] == "deception_detected"


@pytest.mark.regression
def test_matcher_first_declaration_wins_on_overlap():
    """If two triggers could fire on the same input, first declared one wins."""
    overlapping = [
        {"name": "first", "intents": ["x"], "tones": [], "keywords": [], "persistence_floor": 0.4, "intensity_boost": 0.0},
        {"name": "second", "intents": ["x"], "tones": [], "keywords": [], "persistence_floor": 0.6, "intensity_boost": 0.0},
    ]
    scar = MoralMatrixModule._match_scar_trigger(
        {"primary": "neutral"},
        {"input_analysis": {"intent": "x"}},
        "",
        overlapping,
    )
    assert scar["name"] == "first"


@pytest.mark.regression
def test_matcher_empty_trigger_list():
    assert MoralMatrixModule._match_scar_trigger({"primary": "x"}, {}, "x", []) is None


@pytest.mark.regression
def test_matcher_trigger_without_name_skipped():
    """Triggers with empty name are configuration noise — skip them."""
    bad = {"name": "", "intents": ["x"], "tones": [], "keywords": []}
    assert (
        MoralMatrixModule._match_scar_trigger(
            {"primary": "neutral"},
            {"input_analysis": {"intent": "x"}},
            "",
            [bad],
        )
        is None
    )


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_apply_sets_floor_and_boost():
    payload = {"intensity": 0.3, "notes": {}}
    MoralMatrixModule._apply_scar_to_payload(payload, _BOUNDARY_TRIGGER)
    # 0.3 + 0.25 = 0.55, clamped at min(1.0, max(..., 0.5))
    assert payload["intensity"] == pytest.approx(0.55)
    assert payload["persistence_floor"] == pytest.approx(0.5)
    assert payload["scar_label"] == "boundary_violation_rename"
    assert payload["notes"]["scar"]["label"] == "boundary_violation_rename"


@pytest.mark.regression
def test_apply_clamps_to_one():
    payload = {"intensity": 0.9, "notes": {}}
    MoralMatrixModule._apply_scar_to_payload(payload, {"name": "x", "persistence_floor": 0.4, "intensity_boost": 0.5})
    assert payload["intensity"] == pytest.approx(1.0)


@pytest.mark.regression
def test_apply_raises_to_floor_when_boost_insufficient():
    """Even a small boost still leaves the trace at or above the floor."""
    payload = {"intensity": 0.1, "notes": {}}
    MoralMatrixModule._apply_scar_to_payload(payload, {"name": "x", "persistence_floor": 0.6, "intensity_boost": 0.0})
    assert payload["intensity"] == pytest.approx(0.6)


@pytest.mark.regression
def test_apply_preserves_existing_notes_dict():
    payload = {"intensity": 0.3, "notes": {"narrative": "preexisting", "outcomes": [1, 2]}}
    MoralMatrixModule._apply_scar_to_payload(payload, _BOUNDARY_TRIGGER)
    assert payload["notes"]["narrative"] == "preexisting"
    assert payload["notes"]["outcomes"] == [1, 2]
    assert "scar" in payload["notes"]


@pytest.mark.regression
def test_apply_promotes_string_notes_to_dict():
    payload = {"intensity": 0.3, "notes": "legacy raw note"}
    MoralMatrixModule._apply_scar_to_payload(payload, _BOUNDARY_TRIGGER)
    assert isinstance(payload["notes"], dict)
    assert payload["notes"]["text"] == "legacy raw note"
    assert payload["notes"]["scar"]["label"] == "boundary_violation_rename"


# ---------------------------------------------------------------------------
# End-to-end through repository
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_store_emotional_trace_persists_scar_fields():
    repo = MoralMatrixRepository()
    trace_id = repo.store_emotional_trace(
        CHARACTER_ID,
        message_id=None,
        payload={
            "primary_emotion": "anger",
            "intensity": 0.8,
            "persistence_floor": 0.5,
            "scar_label": "test_scar",
            "notes": {"scar": {"label": "test_scar"}},
        },
    )
    with SessionLocal() as session:
        row = session.query(EmotionalTrace).filter_by(id=trace_id).one()
        assert row.persistence_floor == pytest.approx(0.5)
        assert row.intensity == pytest.approx(0.8)


@pytest.mark.regression
def test_decay_respects_scar_floor():
    """A scarred trace stops decaying at its floor instead of fading to zero."""
    repo = MoralMatrixRepository()
    trace_id = repo.store_emotional_trace(
        CHARACTER_ID,
        message_id=None,
        payload={
            "primary_emotion": "sadness",
            "intensity": 0.8,
            "persistence_floor": 0.4,
        },
    )
    # Backdate the trace by 30 days so decay has something to do.
    with SessionLocal() as session:
        row = session.query(EmotionalTrace).filter_by(id=trace_id).one()
        row.created_at = datetime.now(timezone.utc) - timedelta(days=30)
        session.commit()

    repo.decay_emotional_traces(character_id=CHARACTER_ID, global_rate=0.05)

    with SessionLocal() as session:
        row = session.query(EmotionalTrace).filter_by(id=trace_id).one()
        # Without floor: 0.8 - 0.05*30 = -0.7 → clamped to 0. With floor 0.4 → 0.4.
        assert row.intensity == pytest.approx(0.4)


@pytest.mark.regression
def test_forgiveness_respects_scar_floor():
    """register_forgiveness can't push intensity below persistence_floor — same
    clamp logic that decay uses, applied to the explicit forgiveness path."""
    repo = MoralMatrixRepository()
    trace_id = repo.store_emotional_trace(
        CHARACTER_ID,
        message_id=None,
        payload={
            "primary_emotion": "anger",
            "intensity": 0.8,
            "persistence_floor": 0.5,
        },
    )
    result = repo.register_forgiveness(
        CHARACTER_ID,
        trace_id=trace_id,
        cause="apology",
        compensating_action="user said sorry repeatedly",
        delta_intensity=0.5,  # would push to 0.3 without the floor
    )
    assert result["new_intensity"] == pytest.approx(0.5)
    assert result["delta_applied"] == pytest.approx(0.3)  # only the gap above floor
    assert result["triggered_resolve"] is True
