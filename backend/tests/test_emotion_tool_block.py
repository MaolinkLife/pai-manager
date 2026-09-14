"""What the speaking model receives about her feelings (the `state.emotion` tool block).

The matrix keeps the numbers for itself; the model gets meaning. With an inner
voice the block speaks in first person; without one it falls back to a compact
description of the state, still without numbers. The response the matrix wants
is a wish, not a hard directive.
"""

from __future__ import annotations

import asyncio

import pytest

from constants.moral import BEHAVIORAL_RECOMMENDATIONS
from core.instructor import Instructor
from modules.moral_matrix.service import MoralMatrixModule


pytestmark = pytest.mark.regression


def _emotion_block(moral_state: dict) -> str:
    instructor = Instructor()
    instructor._build_environment_tool_content = lambda: "Date: 14 Sep 2026\nTime: 17:04:00"
    messages = asyncio.run(
        instructor.format_for_api(
            system_prompt="base",
            user_message={"id": "u1", "content": "hello", "history": []},
            moral_state=moral_state,
        )
    )
    tool = next(
        item for item in messages if item.get("role") == "tool" and item.get("name") == "state.emotion"
    )
    return str(tool.get("content") or "")


def _state(**extra) -> dict:
    state = {
        "current_emotion": "tenderness",
        "emotion_intensity": 0.85,
        "relationship_status": "very close",
        "metrics": {"trust": 1.0, "stability": 0.93},
        "trigger": "The user's affectionate surprise confirms PAI's feeling of being enough.",
        "narrative": "PAI feels a warm swell of validation.",
        "influence": {"initiative": 0.128, "tone": "мягкий", "reaction_delay": "-0.1s", "behavior": "answer_playfully"},
        "associated_events": ["message:u1"],
        "affective_state": {"label": "Нежность"},
        "recommendations": ["Keep it warm but not overwhelming"],
        "hard_directives": ["system:lower_tone"],
    }
    state.update(extra)
    return state


def test_the_block_speaks_with_the_inner_voice():
    voice = "Мне очень тепло и спокойно: ты спросил так ласково. Хочу ответить игриво."

    block = _emotion_block(_state(meta={"inner_voice": voice}))

    assert block.startswith(voice)
    assert "Recommendations:\n- Keep it warm but not overwhelming" in block
    assert "- system:lower_tone" in block
    assert "message:u1" in block
    for analysis in ("Why this state changed", "Self-expression guidance", "PAI feels", "Behavior influence"):
        assert analysis not in block
    for number in ("intensity=", "trust=", "initiative=", "reaction_delay", "0.85"):
        assert number not in block


def test_without_the_inner_voice_the_block_describes_the_state_without_numbers():
    block = _emotion_block(_state())

    assert "Нежность (tenderness)" in block
    assert "strength=strong" in block
    assert "relationship=very close" in block
    assert "Why this state changed: The user's affectionate surprise" in block
    assert "tone=мягкий" in block
    assert "behavior=answer_playfully" in block
    for number in ("intensity=", "metrics", "trust=", "initiative=", "reaction_delay", "0.85"):
        assert number not in block


@pytest.mark.parametrize(
    ("intensity", "word"),
    [(0.2, "slight"), (0.5, "noticeable"), (0.7, "strong")],
)
def test_the_strength_is_given_in_words(intensity, word):
    assert f"strength={word}" in _emotion_block(_state(emotion_intensity=intensity))


def test_the_wanted_response_is_not_a_hard_directive():
    transition = MoralMatrixModule()._normalize_structured_answer(
        {
            "emotional_reaction": {
                "dominant_shift": "tenderness",
                "shift_strength": 0.85,
                "shift_reason": "kind words",
            },
            "behavior_formation": {
                "desired_behavior": "answer_playfully",
                "response_constraints": ["Keep it warm but not overwhelming"],
            },
        }
    )

    assert transition["hard_directives"] == []
    assert transition["state"]["influence"]["behavior"] == "answer_playfully"
    assert transition["soft_recommendations"] == ["Keep it warm but not overwhelming"]


def test_the_matrix_recommendations_come_first():
    transition = {"soft_recommendations": ["Keep it warm but not overwhelming", "  "]}

    assert MoralMatrixModule._pick_recommendations(transition, "tenderness") == [
        "Keep it warm but not overwhelming"
    ]


@pytest.mark.parametrize("transition", [None, {}, {"soft_recommendations": []}])
def test_without_matrix_recommendations_the_emotion_table_is_used(transition):
    assert MoralMatrixModule._pick_recommendations(transition, "tenderness") == list(
        BEHAVIORAL_RECOMMENDATIONS["tenderness"]
    )
