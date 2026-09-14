"""Who is in the picture, and who writes its prompt.

The rules:
- a proactive image is always her, as a selfie;
- a request about her («сделай изображение себя», «чем ты занята, покажешь?»)
  is her as well;
- «сделай изображение» without a subject is the composer's weighted dice;
- anything else is only what was asked: no appearance anchor, no selfie pose,
  no time or season. A ready prompt written in the chat is a base the model
  improves; a one-to-one prompt belongs to the synthesis hub;
- time and season go only into images of her;
- the pose comes from the persona settings; with none set, the model composes
  the selfie itself.

How the roles split: the composer decides and supplies, the model writes the
scene, the composer puts the appearance anchor first, word for word. A broken
model answer falls back to the composer's template for her and to the request
text for anything else. The composer runs before generation, not inside the
generator: the hub never passes through it, and a reroll's refined prompt
reaches the generator.

The chat model, the image generator, vision, the judge and DebugVault are fakes.
The clock runs from a winter evening.
"""

import asyncio
import io
import json
from types import SimpleNamespace

import pytest
from freezegun import freeze_time
from PIL import Image

from constants.prompts import IMAGE_SCENE_FORMAT_PROMPT
from modules.generative import conversation
from modules.generative.manager import generation_manager
from modules.synthesis import image_check, media_pipeline
from modules.synthesis.media_pipeline import MediaPipelineRequest, media_generation_pipeline
from modules.synthesis.types import ImageGenerationResult, SynthesisModelInfo
from modules.visual_history_cache import visual_history_cache_service
from modules.visual_intent_composer import VisualProfile, visual_intent_composer_service
from modules.visual_profile_store import visual_profile_store_service

pytestmark = pytest.mark.regression

ANCHOR = "adult anime woman, long deep blue hair with vibrant pink gradient tips, bright purple eyes"
# Every entry of the composer's built-in selfie pool frames the shot this way.
BUILT_IN_POSE = "front-facing smartphone camera POV"
WINTER_EVENING_UTC = "2027-01-15 19:00:00"

# Biases that make the composer's dice land on her: only «сделай изображение»
# may roll them, so the rest of the tests stay deterministic.
PROFILE = VisualProfile(
    character_name="lim_test",
    appearance_textarea=ANCHOR,
    style_preset="anime",
    render_profile="default_anime",
    selfie_bias=1.0,
    environment_bias=0.0,
    symbolic_bias=0.0,
)
# A profile that leans away from her as far as it can.
AWAY_FROM_HER = PROFILE.model_copy(update={"selfie_bias": 0.0, "environment_bias": 1.0, "symbolic_bias": 1.0})


def _png():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, format="PNG")
    return buffer.getvalue()


def _checks(**gates):
    config = {
        "relevance": {"enabled": False, "threshold": 0.6, "reroll": False},
        "quality": {"enabled": False, "threshold": 0.82, "reroll": False},
        "max_generations": 1,
    }
    for name, value in gates.items():
        config[name] = {**config[name], **value} if isinstance(value, dict) else value
    return config


@pytest.fixture
def world(monkeypatch):
    state = {
        "profile": PROFILE,
        "model_answer": None,
        "model_content": None,
        "model_raises": False,
        "model_calls": [],
        "format_prompt": "",
        "prompts": [],
        "checks": _checks(),
        "verdicts": [],
        "vault": [],
        "failures": [],
    }
    visual_history_cache_service._history.clear()

    original_config = image_check.config_service.get_config_value
    overrides = {
        "synthesis.image_check": lambda: state["checks"],
        "synthesis.image_scene.format_prompt": lambda: state["format_prompt"],
        "synthesis.prompting": lambda: {},
        "moral.enabled": lambda: False,
    }

    def get_config_value(path, default=None, *args, **kwargs):
        if path in overrides:
            return overrides[path]()
        return original_config(path, default, *args, **kwargs)

    monkeypatch.setattr(image_check.config_service, "get_config_value", get_config_value)

    monkeypatch.setattr(visual_profile_store_service, "load_profile", lambda *a, **k: state["profile"])
    monkeypatch.setattr(visual_profile_store_service, "persist_profile", lambda profile: None)
    monkeypatch.setattr(visual_profile_store_service, "persist_generated_anchor_if_missing", lambda generated: None)
    monkeypatch.setattr(conversation, "get_active_character_name", lambda *a, **k: "lim_test")
    monkeypatch.setattr("modules.system.service.get_active_character_name", lambda *a, **k: "lim_test")

    def chat_model(request):
        state["model_calls"].append(request)
        if state["model_raises"]:
            raise RuntimeError("the chat model is unavailable")
        content = state["model_content"] if state["model_content"] is not None else json.dumps(state["model_answer"])
        return SimpleNamespace(content=content, provider="fake_chat", raw={}, reasoning="", metadata={})

    monkeypatch.setattr(generation_manager, "generate", chat_model)

    service = media_pipeline.synthesis_service

    def generate_once(*, request, model, provider_name):
        state["prompts"].append(request.prompt)
        return ImageGenerationResult(provider="core", image_bytes=_png(), model_id="image_gen_test")

    monkeypatch.setattr(
        service,
        "_resolve_target_model",
        lambda request: SynthesisModelInfo(
            model_id="image_gen_test", label="test", family="sdxl", source="test", installed=True
        ),
    )
    monkeypatch.setattr(service, "_generate_once", generate_once)
    monkeypatch.setattr("modules.synthesis.service.should_release_resources", lambda *a, **k: False)
    monkeypatch.setattr(
        service,
        "refine_prompts_from_feedback",
        lambda **kwargs: (f"refined: {kwargs['feedback']}", kwargs["previous_negative"]),
    )

    monkeypatch.setattr(
        image_check, "_describe_with_vision", lambda image_bytes, prompt=None: {"summary": "a picture", "status": "success"}
    )
    monkeypatch.setattr(image_check, "_judge_with_model", lambda system, user: json.dumps(state["verdicts"].pop(0)))
    monkeypatch.setattr(image_check, "_save_attempt_image", lambda folder, batch, attempt: None)
    monkeypatch.setattr(
        "modules.debug_vault.service.write_vault_entry", lambda **entry: state["vault"].append(entry) or "vault-1"
    )

    class FakeVisualModule:
        def describe_image(self, image, prompt):
            return {"summary": "a picture", "status": "success"}

    monkeypatch.setattr(conversation, "VisualModule", FakeVisualModule)

    with freeze_time(WINTER_EVENING_UTC, tick=True):
        yield state
    visual_history_cache_service._history.clear()


def chat_image(world, user_text, answer=None):
    """The main chat decided to attach an image to its reply."""
    world["model_answer"] = answer
    decision_context = {"image_generation": {"enabled": True, "reason": "test"}, "system_prompt": "base"}
    asyncio.run(
        conversation._prepare_main_chat_image_context(
            decision_context=decision_context,
            last_user_message={"content": user_text},
            memory_context={},
        )
    )
    return world["prompts"]


def proactive_image(world, message, monkeypatch, answer=None):
    """The initiative wrote first and attaches a selfie to its message."""
    from modules.initiative import service as initiative

    world["model_answer"] = answer

    async def send_message(payload):
        return None

    monkeypatch.setattr("modules.storage.service.save_media_for_message", lambda message_id, media: None)
    monkeypatch.setattr("modules.memory.history.get_message_by_id", lambda message_id: {"media": []})
    monkeypatch.setattr("core.websocket_manager.manager.send_message", send_message)
    monkeypatch.setattr(
        initiative,
        "log_audit_entry",
        lambda event, message, status=None, details=None, **kwargs: world["failures"].append(details)
        if event == "initiative_selfie_failed"
        else None,
    )

    asyncio.run(initiative._attach_selfie("initiative-message", message))
    assert not world["failures"], world["failures"]
    return world["prompts"]


def _is_her(prompt):
    return prompt.startswith(ANCHOR)


def _has_time_and_season(prompt):
    lowered = prompt.lower()
    return "winter" in lowered and ("evening" in lowered or "night" in lowered)


def _model_input(world):
    [call] = world["model_calls"]
    return call.messages[0]["content"], call.messages[-1]["content"]


# --- proactive: always her, as a selfie --------------------------------------


def test_a_proactive_image_is_always_her_even_when_the_profile_leans_away(world, monkeypatch):
    world["profile"] = AWAY_FROM_HER

    for _ in range(10):
        proactive_image(
            world, "Я сегодня решила прогуляться по городу", monkeypatch,
            answer={"subject": "self", "prompt": "walking through the city streets", "negative_prompt": ""},
        )

    assert len(world["prompts"]) == 10
    assert all(_is_her(prompt) for prompt in world["prompts"]), world["prompts"]


def test_a_proactive_image_carries_her_situation_time_and_season(world, monkeypatch):
    [prompt] = proactive_image(
        world, "Я сегодня решила прогуляться по городу", monkeypatch,
        answer={"subject": "self", "prompt": "walking through the city streets", "negative_prompt": ""},
    )

    assert _is_her(prompt), prompt
    assert "walking through the city streets" in prompt
    assert _has_time_and_season(prompt), prompt
    _, user = _model_input(world)
    assert '"subject_is_decided": "self"' in user


# --- a request about her --------------------------------------------------------


@pytest.mark.parametrize("user_text", ["Сделай изображение себя", "Чем ты сейчас занята, покажешь?"])
def test_a_request_about_her_is_her_in_the_scene_the_model_wrote(world, user_text):
    [prompt] = chat_image(
        world, user_text, {"subject": "self", "prompt": "reading a book by the window", "negative_prompt": ""}
    )

    assert _is_her(prompt), prompt
    assert "reading a book by the window" in prompt
    assert _has_time_and_season(prompt), prompt


def test_without_a_pose_in_the_persona_settings_the_model_composes_the_selfie(world):
    [prompt] = chat_image(world, "Сделай изображение себя", {"subject": "self", "prompt": "reading a book"})

    assert BUILT_IN_POSE not in prompt, prompt
    _, user = _model_input(world)
    assert "compose it yourself as a selfie" in user


def test_a_pose_set_in_the_persona_settings_is_put_in(world):
    world["profile"] = PROFILE.model_copy(
        update={
            "selfie_composition_pool_override": (
                "selfie_composition_pool:\n  - id: hallway\n    weight: 1\n    prompt: mirror selfie in the hallway\n"
            )
        }
    )

    [prompt] = chat_image(world, "Сделай изображение себя", {"subject": "self", "prompt": "reading a book"})

    assert _is_her(prompt) and "mirror selfie in the hallway" in prompt, prompt
    assert BUILT_IN_POSE not in prompt
    _, user = _model_input(world)
    assert "set separately" in user


# --- anything else: only what was asked ---------------------------------------


@pytest.mark.parametrize(
    "user_text, scene",
    [
        ("Нарисуй трёх девушек на диване, лиса и кролика", "three anime girls on a couch with a fox and a rabbit"),
        ("Сделай изображение осени", "autumn park with falling golden leaves"),
        # A ready prompt in the chat is a base the model improves.
        ("Сделай изображение по промпту: castle on a cliff", "castle on a cliff at sunset, dramatic clouds, masterpiece"),
    ],
)
def test_anything_else_is_only_what_was_asked(world, user_text, scene):
    [prompt] = chat_image(world, user_text, {"subject": "other", "prompt": scene, "negative_prompt": ""})

    assert prompt == scene


# --- no subject: the composer's dice -------------------------------------------


def test_an_image_without_a_subject_may_land_on_her(world):
    [prompt] = chat_image(world, "Сделай изображение", {"subject": "free", "prompt": "a quiet moment", "negative_prompt": ""})

    assert _is_her(prompt), prompt
    assert "a quiet moment" in prompt
    _, user = _model_input(world)
    assert "the character herself" in user


def test_an_image_without_a_subject_that_lands_elsewhere_has_no_anchor(world):
    world["profile"] = AWAY_FROM_HER.model_copy(update={"allow_self_images": False})

    [prompt] = chat_image(world, "Сделай изображение", {"subject": "free", "prompt": "a quiet moment", "negative_prompt": ""})

    assert ANCHOR not in prompt and BUILT_IN_POSE not in prompt, prompt
    assert "a quiet moment" in prompt


# --- a broken model answer -------------------------------------------------------


def test_an_empty_scene_about_her_falls_back_to_the_composer_template(world):
    [prompt] = chat_image(world, "Сделай изображение себя", {"subject": "self", "prompt": "", "negative_prompt": ""})

    assert _is_her(prompt) and BUILT_IN_POSE in prompt, prompt


def test_an_empty_scene_for_anything_else_falls_back_to_the_request(world):
    [prompt] = chat_image(world, "Сделай изображение осени", {"subject": "other", "prompt": "", "negative_prompt": ""})

    assert prompt == "Сделай изображение осени"


def test_without_the_chat_model_the_request_itself_is_drawn(world):
    world["model_raises"] = True

    [prompt] = chat_image(world, "Нарисуй трёх девушек на диване")

    assert prompt == "Нарисуй трёх девушек на диване"


def test_an_answer_the_system_cannot_read_draws_the_request_itself(world):
    world["model_content"] = "Here is a lovely prompt: three girls on a couch"

    [prompt] = chat_image(world, "Нарисуй трёх девушек на диване")

    assert prompt == "Нарисуй трёх девушек на диване"


def test_without_the_model_a_proactive_image_is_still_her(world, monkeypatch):
    world["model_raises"] = True

    [prompt] = proactive_image(world, "Я сегодня решила прогуляться по городу", monkeypatch)

    assert _is_her(prompt) and BUILT_IN_POSE in prompt, prompt


# --- the answer format ------------------------------------------------------------


def test_the_answer_format_comes_from_the_settings(world):
    world["format_prompt"] = "Return JSON: subject, prompt."

    chat_image(world, "Сделай изображение осени", {"subject": "other", "prompt": "autumn park"})

    system, _ = _model_input(world)
    assert system.endswith("Return JSON: subject, prompt.")


def test_an_empty_answer_format_means_the_built_in_one(world):
    chat_image(world, "Сделай изображение осени", {"subject": "other", "prompt": "autumn park"})

    system, _ = _model_input(world)
    assert system.endswith(IMAGE_SCENE_FORMAT_PROMPT)


# --- reroll and DebugVault --------------------------------------------------------


def test_a_reroll_sends_the_refined_prompt_to_the_generator(world):
    world["checks"] = _checks(relevance={"enabled": True, "reroll": True}, max_generations=2)
    world["verdicts"] = [{"relevance": 0.2, "feedback": "add the fox"}, {"relevance": 0.9}]
    scene = "three anime girls on a couch"

    prompts = chat_image(world, "Нарисуй трёх девушек на диване, лиса и кролика", {"subject": "other", "prompt": scene})

    assert prompts == [scene, "refined: add the fox"]


def test_a_reroll_of_her_keeps_the_anchor_first(world):
    world["checks"] = _checks(relevance={"enabled": True, "reroll": True}, max_generations=2)
    world["verdicts"] = [{"relevance": 0.2, "feedback": "add a book"}, {"relevance": 0.9}]

    prompts = chat_image(world, "Сделай изображение себя", {"subject": "self", "prompt": "reading on the sofa"})

    assert len(prompts) == 2, prompts
    assert prompts[1].startswith(ANCHOR) and "refined: add a book" in prompts[1], prompts[1]


def test_debug_vault_records_the_prompt_the_generator_drew(world):
    world["checks"] = _checks(relevance={"enabled": True})
    world["verdicts"] = [{"relevance": 0.2, "mismatches": ["no book"]}]

    [drawn] = chat_image(world, "Сделай изображение себя", {"subject": "self", "prompt": "reading a book by the window"})

    [entry] = world["vault"]
    [attempt] = entry["context"]["attempts"]
    assert attempt["prompt"] == drawn


# --- the synthesis hub --------------------------------------------------------------


def test_a_hub_prompt_never_passes_through_the_composer(world, monkeypatch):
    calls = []
    monkeypatch.setattr(visual_intent_composer_service, "compose", lambda payload: calls.append("compose"))
    monkeypatch.setattr(
        visual_intent_composer_service,
        "ensure_appearance_anchor",
        lambda profile: calls.append("anchor") or (profile, None),
    )

    asyncio.run(
        media_generation_pipeline.run_image(
            MediaPipelineRequest(
                mode="direct",
                manual_prompt=True,
                prompt="castle on a cliff",
                image_provider="core",
                image_model="image_gen_test",
                source="api_synthesis",
                metadata={"allow_scenario_controls": False},
            )
        )
    )

    assert world["prompts"] == ["castle on a cliff"]
    assert calls == []
