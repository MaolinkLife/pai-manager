"""Contour tests for the moral matrix: every emotion it names is her emotion.

A whole turn runs on the throwaway PAI with the matrix model answering what the
test says. The emotion of that answer must reach her state, the stored trace and
snapshot, the matrix screen, the inner voice and the block the speaking model
gets, for each emotion of the pool. The code must not pull her back to
tenderness on its own, and the matrix must get her state as it was stored, in
the shape its prompt describes, instead of a state the stored traces already
pushed towards the old emotion.

Run with:

    venv\\Scripts\\python.exe tests\\contour\\run_contour.py -k matrix_emotions
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from constants.moral import DEFAULT_EMOTIONAL_STATE

pytestmark = pytest.mark.contour

EMOTIONS = list(DEFAULT_EMOTIONAL_STATE)


def matrix_answer(dominant: str, strength: float = 0.8, reason: str = "the message") -> str:
    """The matrix model's answer, in the structure the configured matrix prompt asks for."""
    new_state = {name: 0.05 for name in EMOTIONS}
    new_state[dominant] = strength
    return json.dumps(
        {
            "emotional_reaction": {
                "reaction_summary": reason,
                "dominant_shift": dominant,
                "shift_strength": strength,
                "shift_reason": reason,
            },
            "state_update": {"recommended_new_state": new_state},
            "behavior_formation": {
                "desired_behavior": "answer_calmly",
                "desire_vector": {},
                "response_constraints": [],
                "notes_for_generator": [],
            },
        },
        ensure_ascii=False,
    )


@pytest.fixture(autouse=True)
def owner_context(pai):
    """The live chat route turns on the owner context before the pipeline; so does a turn here."""
    from modules.system.service import activate_user_context, reset_user_context

    token = activate_user_context(pai.owner_uuid)
    yield
    reset_user_context(token)


@pytest.fixture
def voice(pai, monkeypatch):
    """The inner voice is on; its model says which emotion it was given."""
    from modules.generative import manager as generation_module
    from modules.system import config as config_service

    config_service.set_config_value("moral.inner_voice.enabled", True, user_uuid=pai.owner_uuid)
    asked: list[str] = []

    def generate(request):
        if (request.metadata or {}).get("mode") != "moral_inner_voice":
            raise RuntimeError("generation is not available in contour tests")
        payload = next(m["content"] for m in request.messages if m.get("role") == "user")
        asked.append(payload)
        emotion = payload.split("Current emotion: ", 1)[1].splitlines()[0]
        return SimpleNamespace(content=f"Сейчас во мне {emotion}.")

    monkeypatch.setattr(generation_module.generation_manager, "generate", generate)
    return asked


def matrix_screen() -> dict:
    from routes import moral_routes

    return asyncio.run(moral_routes.get_moral_state(SimpleNamespace(headers={}), limit=12))["state"]


@pytest.mark.parametrize("emotion", EMOTIONS)
def test_the_emotion_the_matrix_names_reaches_everything_that_shows_it(pai, voice, emotion):
    pai.moral_response = matrix_answer(emotion)

    turn = pai.turn("Расскажи, как прошёл твой день.")

    assert turn.processing["moral_state"]["current_emotion"] == emotion
    # Stored under her own character: the one the matrix screen reads.
    [(trace_emotion,)] = pai.fetch(
        "SELECT primary_emotion FROM emotional_traces WHERE character_id = :character_id "
        "ORDER BY created_at DESC LIMIT 1",
        character_id=pai.character_id,
    )
    [(mood,)] = pai.fetch(
        "SELECT mood FROM moral_state_snapshots WHERE character_id = :character_id "
        "ORDER BY created_at DESC LIMIT 1",
        character_id=pai.character_id,
    )
    assert (trace_emotion, mood) == (emotion, emotion)
    assert matrix_screen()["current_emotion"] == emotion
    assert f"Current emotion: {emotion}" in voice[-1]
    assert turn.tool_content("state.emotion").startswith(f"Сейчас во мне {emotion}.")


def settle(pai, emotion: str, strength: float, text: str, tone: str = "neutral") -> None:
    """Let the matrix put her into a state she carries into the next turn."""
    pai.moral_response = matrix_answer(emotion, strength, "the conversation so far")
    pai.turn(text, tone=tone)


def her_vector(pai) -> dict:
    [(stored,)] = pai.fetch(
        "SELECT emotion_vector FROM emotional_traces WHERE character_id = :character_id "
        "ORDER BY created_at DESC LIMIT 1",
        character_id=pai.character_id,
    )
    return json.loads(stored or "{}")


def test_the_matrix_decides_her_state_not_the_tone_of_the_message(pai):
    settle(pai, "peace", 0.3, "Тихий вечер, просто сидим.")
    pai.moral_response = matrix_answer("hurt", 0.7, "a harsh word out of nowhere")

    turn = pai.turn("Отстань, ты бесполезная.", tone="angry")

    # The human is angry; what she feels about it is the matrix's verdict, not a mirror of his tone.
    assert turn.processing["moral_state"]["current_emotion"] == "hurt"


def test_a_warm_tone_alone_does_not_raise_her_tenderness(pai):
    settle(pai, "peace", 0.2, "Просто болтаем ни о чём.")
    pai.moral_response = matrix_answer("curiosity", 0.6, "an interesting question")

    turn = pai.turn("Слушай, а расскажи, как ты это делаешь?", tone="warm")

    assert turn.processing["moral_state"]["current_emotion"] == "curiosity"
    # The warmth is his; it must not become her tenderness on the way.
    assert her_vector(pai).get("tenderness", 0.0) <= 0.2


def test_without_a_verdict_her_state_does_not_follow_the_tone(pai):
    settle(pai, "peace", 0.2, "Просто болтаем ни о чём.")
    # The matrix model says nothing: with no verdict, nothing about her has changed.
    pai.moral_response = None

    turn = pai.turn("Ты умница, спасибо тебе за всё.", tone="warm")

    assert turn.processing["moral_state"]["current_emotion"] == "peace"
    assert her_vector(pai).get("tenderness", 0.0) <= 0.2


def test_after_a_strong_emotion_a_neutral_message_does_not_bring_tenderness_back(pai):
    pai.moral_response = matrix_answer("anger", 0.9, "an insult")
    pai.turn("Ты бесполезная.", tone="angry")
    # The matrix model is silent now: what follows is the code's own reaction.
    pai.moral_response = None

    turn = pai.turn("Ладно. Который час?")

    assert turn.processing["moral_state"]["current_emotion"] != "tenderness"


def test_the_matrix_gets_her_state_as_stored_and_not_pushed_to_tenderness(pai, monkeypatch):
    for index in range(6):
        pai.moral_response = matrix_answer("tenderness", 0.9, "kind words")
        pai.turn(f"Ты у меня самая лучшая, правда {index}.", tone="warm")

    received: list[dict] = []

    def moral_model_chat(messages, *_args, **_kwargs):
        received.append(json.loads(messages[1]["content"]))
        return {"message": {"content": matrix_answer("hurt", 0.7, "a harsh word")}}

    monkeypatch.setattr("modules.moral_matrix.providers.ollama.ollama_client.chat", moral_model_chat)

    turn = pai.turn("Отстань, ты меня бесишь.", tone="angry")

    [matrix_input] = received
    # The input its prompt describes, plus the analyzer's read of the human.
    assert set(matrix_input) == {
        "currentState",
        "lastState",
        "activePing",
        "userMessage",
        "userAnalysis",
        "memoryState",
    }
    assert matrix_input["userMessage"] == "Отстань, ты меня бесишь."
    # The tone belongs to the human and is named as his, not as her feeling.
    assert matrix_input["userAnalysis"]["tone"] == "angry"
    # Her state before this message, exactly as the last turn stored it: the
    # traces of the tender evening do not push tenderness any higher.
    assert matrix_input["currentState"]["emotion"] == "tenderness"
    assert matrix_input["currentState"]["emotion_vector"]["tenderness"] == pytest.approx(0.9)
    recent = matrix_input["memoryState"]["recent_traces"]
    assert recent and all(trace["primary_emotion"] == "tenderness" for trace in recent)
    assert turn.processing["moral_state"]["current_emotion"] == "hurt"
