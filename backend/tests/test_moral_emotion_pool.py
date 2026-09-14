"""The emotion pool is one agreement shared by the matrix, its config and the UI.

The emotion pool: the emotions of the matrix prompt plus
resentment from the concept; calm is the same as peace; laziness is not an
emotion. These tests keep every place that lists emotions in step.
"""

import json
import os
import re

import pytest

from constants import moral
from constants.default_config import DEFAULT_CONFIG
from modules.moral_matrix.service import MoralMatrixModule

pytestmark = pytest.mark.regression

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(os.path.dirname(BACKEND_DIR), "frontend")

AGREED_POOL = {
    "sadness",
    "tenderness",
    "joy",
    "jealousy",
    "happiness",
    "peace",
    "anger",
    "hurt",
    "disgust",
    "longing",
    "frustration",
    "anxiety",
    "confusion",
    "embarrassment",
    "pride",
    "resentment",
}


def test_pool_is_the_agreed_one():
    assert set(moral.DEFAULT_EMOTIONAL_STATE) == AGREED_POOL
    assert "laziness" not in moral.DEFAULT_EMOTIONAL_STATE


def test_every_emotion_is_defined_and_has_recommendations():
    for emotion in sorted(AGREED_POOL):
        definition = moral.EMOTIONAL_STATE_DEFINITIONS[emotion]
        assert definition["label_ru"] and definition["arises_when"] and definition["behavior"], emotion
        assert {"initiative", "tone", "reaction_delay"} <= set(definition["influence"]), emotion
        assert moral.BEHAVIORAL_RECOMMENDATIONS[emotion], emotion
        assert moral.EMOTION_MAP[emotion] == emotion


def test_polarity_of_the_new_emotions():
    assert {"anger", "hurt", "disgust"} <= moral.NEGATIVE_EMOTIONS
    assert "happiness" in moral.POSITIVE_EMOTIONS
    assert not moral.NEGATIVE_EMOTIONS & moral.POSITIVE_EMOTIONS


def test_every_synonym_leads_into_the_pool():
    stray = {
        label: target
        for label, target in moral.EMOTION_SYNONYMS.items()
        if target not in AGREED_POOL
    }
    assert not stray


@pytest.mark.parametrize(
    "label, expected",
    [
        ("calm", "peace"),
        ("hurt", "hurt"),
        ("offended", "hurt"),
        ("обида", "resentment"),
        ("anger", "anger"),
        ("гнев", "anger"),
        ("disgust", "disgust"),
        ("happy", "happiness"),
        ("laziness", ""),
        ("лень", ""),
        ("excited", ""),
        ("", ""),
    ],
)
def test_known_emotion_never_guesses(label, expected):
    assert MoralMatrixModule._known_emotion(label) == expected


def test_initial_state_in_config_covers_the_pool():
    vector = DEFAULT_CONFIG["moral"]["current_state"]["emotion_vector"]
    assert set(vector) == AGREED_POOL


def test_structured_answer_ignores_labels_outside_the_pool():
    transition = MoralMatrixModule()._normalize_structured_answer(
        {
            "emotional_reaction": {
                "dominant_shift": "laziness",
                "shift_strength": 0.9,
                "shift_reason": "устала",
            },
            "state_update": {
                "recommended_new_state": {"laziness": 0.9, "hurt": 0.6, "calm": 0.2},
            },
        }
    )
    assert transition["state"]["state"] == "hurt"
    assert transition["state"]["intensity"] == 0.6
    assert "laziness" not in transition["emotion_vector_target"]
    assert transition["emotion_vector_target"]["peace"] == 0.2


def _matrix_page_emotions() -> set:
    path = os.path.join(FRONTEND_DIR, "src", "app", "features", "matrix", "matrix.component.ts")
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    block = source.split("emotionBars", 1)[1].split("];", 1)[0]
    return set(re.findall(r"key:\s*'(\w+)'", block))


def test_matrix_page_shows_every_emotion_of_the_pool():
    assert _matrix_page_emotions() == AGREED_POOL


@pytest.mark.parametrize("locale", ["ru-RU", "en-US"])
def test_every_emotion_has_a_label(locale):
    path = os.path.join(FRONTEND_DIR, "src", "assets", "i18n", f"{locale}.json")
    with open(path, encoding="utf-8-sig") as handle:
        labels = json.load(handle)["matrix"]["emotions"]
    assert AGREED_POOL <= set(labels), sorted(AGREED_POOL - set(labels))
