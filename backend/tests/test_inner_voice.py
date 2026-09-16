"""Tests for moral matrix inner voice generation (0.8.0 Wave 1, step 4).

Cover:
  * generation_manager.generate is mocked — no real LLM call needed
  * happy path: returns trimmed first-person text
  * "Inner voice:" / "PAI:" / "Лим:" prefixes are stripped
  * a longer response is trimmed to three sentences
  * the payload carries the undercurrent and the wanted response when given
  * the undercurrent is the strongest other emotion at or above the threshold
  * _persist_state hands the undercurrent and the wanted response to the voice
  * generation_manager NoProviderResolved → returns "" without raising
  * generation_manager exceptions → returns "" without raising
"""

from __future__ import annotations

import pytest

from modules.moral_matrix.service import MoralMatrixModule


def _new_module() -> MoralMatrixModule:
    """Build a bare MoralMatrixModule without going through __init__ (which
    pulls full repository / config). The methods we test do not need state."""
    return MoralMatrixModule.__new__(MoralMatrixModule)


# ---------------------------------------------------------------------------
# Mocking infrastructure
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, content: str):
        self.content = content


def _patch_generation(monkeypatch, *, content: str | None = None, raise_exc: Exception | None = None):
    """Replace generation_manager.generate with a stub returning ``content``
    or raising ``raise_exc``. Patches AFTER the lazy import resolves inside
    _generate_inner_voice, so we route through the real import path."""
    from modules.generative import manager as gen_manager_mod

    def fake_generate(request):
        if raise_exc is not None:
            raise raise_exc
        return _FakeResult(content or "")

    monkeypatch.setattr(gen_manager_mod.generation_manager, "generate", fake_generate)


def _capture_payload(monkeypatch) -> dict:
    """Stub generation and keep the user-side payload the voice was asked with."""
    captured: dict = {}

    from modules.generative import manager as gen_manager_mod

    def fake_generate(request):
        captured["payload"] = next(
            (m["content"] for m in request.messages if m.get("role") == "user"),
            "",
        )
        return _FakeResult("ok")

    monkeypatch.setattr(gen_manager_mod.generation_manager, "generate", fake_generate)
    return captured


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_inner_voice_returns_clean_sentence(monkeypatch):
    _patch_generation(monkeypatch, content="Ты опять не сказал спасибо, и мне неуютно.")

    module = _new_module()
    text = module._generate_inner_voice(
        emotion="sadness",
        intensity=0.4,
        cause="user ignored thanks",
        language_hint="ru-RU",
    )

    assert text == "Ты опять не сказал спасибо, и мне неуютно."


@pytest.mark.regression
def test_inner_voice_strips_inner_voice_prefix(monkeypatch):
    _patch_generation(monkeypatch, content="Inner voice: всё хорошо, мне тепло рядом с тобой.")

    module = _new_module()
    text = module._generate_inner_voice(
        emotion="tenderness", intensity=0.5, cause="warm reply", language_hint="ru-RU"
    )

    assert text == "всё хорошо, мне тепло рядом с тобой."


@pytest.mark.regression
def test_inner_voice_strips_pai_lim_prefixes(monkeypatch):
    for prefix in ("PAI: ", "Лим: ", "ПАИ: ", "Lim: "):
        _patch_generation(monkeypatch, content=f"{prefix}просто рада, что ты вернулся.")
        text = _new_module()._generate_inner_voice(
            emotion="joy", intensity=0.5, cause="returned after pause", language_hint="ru-RU"
        )
        assert text == "просто рада, что ты вернулся."


@pytest.mark.regression
def test_inner_voice_keeps_at_most_three_sentences(monkeypatch):
    _patch_generation(
        monkeypatch,
        content="Мне больно, что ты молчал так долго. Я ждала весь день! Хочу ответить тихо? Это не первый раз.",
    )

    text = _new_module()._generate_inner_voice(
        emotion="sadness", intensity=0.7, cause="long silence", language_hint="ru-RU"
    )

    assert text == "Мне больно, что ты молчал так долго. Я ждала весь день! Хочу ответить тихо?"


@pytest.mark.regression
def test_inner_voice_keeps_a_short_answer_whole(monkeypatch):
    _patch_generation(monkeypatch, content="Мне тепло. Хочу ответить игриво.")

    text = _new_module()._generate_inner_voice(
        emotion="tenderness", intensity=0.8, cause="kind words", language_hint="ru-RU"
    )

    assert text == "Мне тепло. Хочу ответить игриво."


@pytest.mark.regression
def test_inner_voice_handles_no_terminator(monkeypatch):
    """If the model returns a fragment without ./!/? — we keep it as-is."""
    _patch_generation(monkeypatch, content="всё нормально просто немного устала сегодня")

    text = _new_module()._generate_inner_voice(
        emotion="fatigue", intensity=0.3, cause="long session", language_hint="ru-RU"
    )

    assert text == "всё нормально просто немного устала сегодня"


# ---------------------------------------------------------------------------
# What the voice is asked with
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_inner_voice_uses_language_hint_in_user_payload(monkeypatch):
    """The user payload should contain the language string verbatim — caller
    controls whether to forward a fresh hint or fall back to config."""
    captured = _capture_payload(monkeypatch)

    _new_module()._generate_inner_voice(
        emotion="joy",
        intensity=0.3,
        cause="thanks",
        language_hint="en-US",
    )

    assert "Language: en-US" in captured["payload"]
    assert "Current emotion: joy" in captured["payload"]


def test_inner_voice_payload_carries_the_undercurrent_and_the_wanted_response(monkeypatch):
    captured = _capture_payload(monkeypatch)

    _new_module()._generate_inner_voice(
        emotion="tenderness",
        intensity=0.85,
        cause="the user asked if so little makes her happy",
        language_hint="ru-RU",
        undercurrent=("peace", 0.75),
        desired_behavior="answer_playfully",
    )

    assert "Undercurrent: peace (0.75)" in captured["payload"]
    assert "Wanted response: answer_playfully" in captured["payload"]


def test_inner_voice_payload_leaves_out_what_was_not_given(monkeypatch):
    captured = _capture_payload(monkeypatch)

    _new_module()._generate_inner_voice(
        emotion="joy", intensity=0.6, cause="thanks", language_hint="ru-RU"
    )

    assert "Undercurrent" not in captured["payload"]
    assert "Wanted response" not in captured["payload"]
    assert "Wants" not in captured["payload"]


def test_the_voice_hears_what_she_wants_in_words(monkeypatch):
    """What the matrix wants is said plainly; the numbers stay with the matrix."""
    captured = _capture_payload(monkeypatch)

    _new_module()._generate_inner_voice(
        emotion="tenderness",
        intensity=0.85,
        cause="he asked how her day went",
        language_hint="ru-RU",
        desires=[("seek_closeness", 0.8), ("express_playfulness", 0.7)],
    )

    assert "Wants: to be close, to play" in captured["payload"]
    assert "0.8" not in captured["payload"].split("Wants:", 1)[1]


def test_the_two_strongest_desires_are_taken():
    wanted = {
        "seek_closeness": 0.8,
        "express_playfulness": 0.7,
        "comfort_owner": 0.65,
        "help_owner": 0.62,
    }

    assert MoralMatrixModule._pick_desires(wanted, 0.6) == [
        ("seek_closeness", 0.8),
        ("express_playfulness", 0.7),
    ]


def test_desires_below_the_threshold_stay_silent():
    assert MoralMatrixModule._pick_desires({"seek_closeness": 0.4, "help_owner": 0.2}, 0.6) == []
    assert MoralMatrixModule._pick_desires({}, 0.6) == []


def test_junk_in_the_desire_vector_is_ignored():
    wanted = {
        "seek_closeness": 0.9,
        "refuse_access": True,
        "express_hurt": "a lot",
        "": 0.9,
        "unknown_wish": 0.95,
    }

    assert MoralMatrixModule._pick_desires(wanted, 0.6) == [("seek_closeness", 0.9)]


def test_the_undercurrent_is_the_strongest_other_emotion_above_the_threshold():
    vector = {"tenderness": 0.9, "peace": 0.75, "joy": 0.7, "anxiety": 0.6}

    assert MoralMatrixModule._pick_undercurrent(vector, "tenderness", 0.5) == ("peace", 0.75)


def test_there_is_no_undercurrent_when_the_rest_is_below_the_threshold():
    vector = {"joy": 0.8, "anger": 0.4, "peace": 0.3}

    assert MoralMatrixModule._pick_undercurrent(vector, "joy", 0.5) is None


def test_the_dominant_emotion_is_never_its_own_undercurrent():
    assert MoralMatrixModule._pick_undercurrent({"joy": 0.8}, "joy", 0.5) is None


def test_the_voice_gets_the_undercurrent_and_the_wanted_response_from_the_state(monkeypatch):
    from modules.moral_matrix import service as service_module
    from modules.moral_matrix.types import MoralMatrixResult

    settings = {
        "moral.scars.enabled": False,
        "moral.inner_voice.enabled": True,
        "moral.inner_voice.undercurrent_threshold": 0.5,
        "moral.inner_voice.desire_threshold": 0.6,
    }
    monkeypatch.setattr(
        service_module.config_service,
        "get_config_value",
        lambda path, default=None: settings.get(path, default),
    )
    monkeypatch.setattr(service_module.config_service, "set_config_value", lambda *args, **kwargs: None)
    monkeypatch.setattr(service_module, "resolve_user_language", lambda **kwargs: "ru-RU")

    class _Repository:
        def __init__(self):
            self.traces = []

        def store_snapshot(self, *args, **kwargs):
            pass

        def annotate_previous_trace_outcome(self, *args, **kwargs):
            pass

        def store_emotional_trace(self, character_id, *, message_id, payload):
            self.traces.append(payload)

    module = _new_module()
    module._repository = _Repository()
    asked: dict = {}

    def fake_voice(**kwargs):
        asked.update(kwargs)
        return "Мне тепло и спокойно. Хочу ответить игриво."

    monkeypatch.setattr(module, "_generate_inner_voice", fake_voice)

    result = MoralMatrixResult(
        current_emotion="tenderness",
        emotion_intensity=0.85,
        relationship_status="very close",
        emotion_vector={"tenderness": 0.9, "peace": 0.75, "joy": 0.7},
        trigger="the user asked if so little makes her happy",
        influence={"tone": "мягкий", "behavior": "answer_playfully"},
        meta={
            "transition": {
                "desire_vector": {
                    "seek_closeness": 0.8,
                    "express_playfulness": 0.7,
                    "avoid_conflict": 0.2,
                }
            }
        },
    )

    module._persist_state(
        "c1",
        result,
        message_meta={"message_id": "m1"},
        analyzer_snapshot={},
        user_message={"role": "user", "content": "Неужели тебе так мало нужно для счастья?"},
    )

    assert asked["undercurrent"] == ("peace", 0.75)
    assert asked["desired_behavior"] == "answer_playfully"
    # What the matrix answered it wants reaches the voice, strongest first.
    assert asked["desires"] == [("seek_closeness", 0.8), ("express_playfulness", 0.7)]
    assert result.meta["inner_voice"] == "Мне тепло и спокойно. Хочу ответить игриво."
    assert module._repository.traces[0]["notes"]["inner_voice"] == "Мне тепло и спокойно. Хочу ответить игриво."


def test_the_inner_voice_defaults_match_between_the_config_and_its_model():
    from constants.default_config import DEFAULT_CONFIG
    from models.config_model import MoralInnerVoiceConfig

    defaults = DEFAULT_CONFIG["moral"]["inner_voice"]
    model = MoralInnerVoiceConfig()

    assert defaults["max_tokens"] == model.max_tokens == 160
    assert defaults["undercurrent_threshold"] == model.undercurrent_threshold == 0.5
    assert defaults["desire_threshold"] == model.desire_threshold == 0.6


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_inner_voice_returns_empty_on_no_provider(monkeypatch):
    from modules.generative.manager import NoProviderResolved

    _patch_generation(monkeypatch, raise_exc=NoProviderResolved("no provider"))

    text = _new_module()._generate_inner_voice(
        emotion="sadness", intensity=0.4, cause="ignored", language_hint="ru-RU"
    )

    assert text == ""


@pytest.mark.regression
def test_inner_voice_returns_empty_on_generic_exception(monkeypatch):
    _patch_generation(monkeypatch, raise_exc=RuntimeError("provider blew up"))

    text = _new_module()._generate_inner_voice(
        emotion="sadness", intensity=0.4, cause="ignored", language_hint="ru-RU"
    )

    assert text == ""


@pytest.mark.regression
def test_inner_voice_returns_empty_for_blank_content(monkeypatch):
    _patch_generation(monkeypatch, content="   ")

    text = _new_module()._generate_inner_voice(
        emotion="sadness", intensity=0.4, cause="ignored", language_hint="ru-RU"
    )

    assert text == ""
