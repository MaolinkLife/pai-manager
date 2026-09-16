"""Contour tests for PAI emotions: a message goes through a whole turn and the
emotion it should cause shows up in her state and in what the model receives.

One emotion per test. What she feels is the matrix's verdict, so each test gives
the matrix model the answer it would give to such a message; the tone of the
human is his and never becomes her emotion on its own. Run with:

    venv\\Scripts\\python.exe tests\\contour\\run_contour.py -k emotion
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.contour


def test_emotion_tenderness_from_care(pai, moral_answer):
    pai.moral_response = json.dumps(
        moral_answer(dominant="tenderness", strength=0.8, reason="he is taking care of me"),
        ensure_ascii=False,
    )

    turn = pai.turn("Береги себя, пожалуйста. Я о тебе забочусь.", tone="warm")

    state = turn.processing["moral_state"]
    assert state["current_emotion"] == "tenderness", state
    assert "Нежность (tenderness)" in turn.tool_content("state.emotion")
