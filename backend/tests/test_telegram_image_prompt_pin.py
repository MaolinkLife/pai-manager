"""What the Telegram bridge hands the image generator, pinned before 3в-3.

Generation in the social modules is not touched now.
The bridge runs on a user account, not a bot; one mistake and a picture lands in
a group. The chat's image prompt stage is being rebuilt, and these tests make
sure the three Telegram requests still reach the generator exactly as before:
the prompt builder's text for the image command, the composer's prompt for the
two tool calls that ask for visual intent.

The requests below copy modules/telegram/service.py (image command, test
image, take photo). The chat model, the composer's plan, the generator and
vision are fakes.
"""

import asyncio
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from modules.generative.manager import generation_manager
from modules.synthesis import image_check, media_pipeline
from modules.synthesis.media_pipeline import MediaPipelineRequest, media_generation_pipeline
from modules.synthesis.types import ImageGenerationResult, SynthesisModelInfo
from modules.visual_intent_composer import VisualIntentPlan, VisualProfile, visual_intent_composer_service
from modules.visual_profile_store import visual_profile_store_service
from modules.visual_prompt_builder import visual_prompt_builder_service

pytestmark = pytest.mark.regression

PROFILE = VisualProfile(character_name="lim_test", appearance_textarea="adult anime woman, blue hair")
BUILDER_PROMPT = "prompt written by the telegram prompt builder"
COMPOSED_PROMPT = "prompt assembled by the composer"
PLAN = VisualIntentPlan(
    visual_intent="mood share",
    subject_mode="self",
    distance="portrait",
    setting="purple_cyan_neon_room",
    purpose="mood_share",
    generator_mode="self_portrait",
    confidence=0.7,
    reasoning_summary="pinned plan",
)


def _png():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def bridge(monkeypatch):
    state = {"prompts": [], "composed": []}

    original_config = image_check.config_service.get_config_value
    overrides = {
        "synthesis.image_check": {
            "relevance": {"enabled": False, "threshold": 0.6, "reroll": False},
            "quality": {"enabled": False, "threshold": 0.82, "reroll": False},
            "max_generations": 1,
        },
        "synthesis.prompting": {},
        "moral.enabled": False,
    }

    def get_config_value(path, default=None, *args, **kwargs):
        if path in overrides:
            return overrides[path]
        return original_config(path, default, *args, **kwargs)

    monkeypatch.setattr(image_check.config_service, "get_config_value", get_config_value)
    monkeypatch.setattr(visual_profile_store_service, "load_profile", lambda *a, **k: PROFILE)
    monkeypatch.setattr(visual_profile_store_service, "persist_profile", lambda profile: None)
    monkeypatch.setattr(visual_profile_store_service, "persist_generated_anchor_if_missing", lambda generated: None)
    monkeypatch.setattr(media_pipeline, "get_active_character_name", lambda *a, **k: "lim_test")
    monkeypatch.setattr(media_pipeline, "should_release_resources", lambda *a, **k: False)

    class TelegramModel:
        def generate(self, request):
            content = json.dumps(
                {"positive_prompt": BUILDER_PROMPT, "negative_prompt": "", "needs_image_description": False}
            )
            return SimpleNamespace(content=content, reasoning="", provider="ollama", raw={}, metadata={})

    monkeypatch.setitem(generation_manager._providers, "ollama", TelegramModel())

    def compose(payload):
        state["composed"].append(payload)
        return PLAN

    monkeypatch.setattr(visual_intent_composer_service, "compose", compose)
    monkeypatch.setattr(visual_prompt_builder_service, "build_prompt_pair", lambda **kwargs: (COMPOSED_PROMPT, ""))

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

    class FakeVisualModule:
        def describe_media_attachments(self, media):
            return {"items": [{"description": "a picture"}]}

    monkeypatch.setattr(media_pipeline, "VisualModule", FakeVisualModule)
    return state


def _telegram_request(**fields):
    base = dict(
        mode="sandbox_forced",
        negative_prompt="",
        llm_provider="ollama",
        llm_model="",
        llm_options={"temperature": 0.45, "num_predict": 900},
        image_provider="auto",
        image_model="image_gen_test",
        use_prompt_builder=True,
        character_name="lim_test",
        metadata={"allow_scenario_controls": True},
    )
    base.update(fields)
    return MediaPipelineRequest(**base)


def _run(request):
    return asyncio.run(media_generation_pipeline.run_image(request))


def test_the_image_command_draws_the_prompt_builder_text(bridge):
    _run(
        _telegram_request(
            prompt="нарисуй кота",
            scenario_key="telegram_command",
            review_generated_image=False,
            source="telegram_image_command",
        )
    )

    assert bridge["prompts"] == [BUILDER_PROMPT]
    assert bridge["composed"] == []


@pytest.mark.parametrize(
    "fields",
    [
        dict(
            prompt="a test image",
            scenario_key="telegram_tool",
            system_prompt="You are reviewing an image that will be sent in Telegram by the character.",
            review_generated_image=True,
            use_visual_intent=True,
            source="telegram_test_image",
        ),
        dict(
            prompt="a photo of the evening",
            scenario_key="telegram_tool",
            system_prompt="Review the generated image for a Telegram reply and answer briefly.",
            review_generated_image=False,
            use_visual_intent=True,
            source="telegram_take_photo",
        ),
    ],
)
def test_the_tool_calls_with_visual_intent_draw_the_composer_prompt(bridge, fields):
    _run(_telegram_request(**fields))

    assert bridge["prompts"] == [COMPOSED_PROMPT]
    [payload] = bridge["composed"]
    assert payload.visual_profile.appearance_textarea == PROFILE.appearance_textarea
    assert (payload.emotion_state, payload.recent_context, payload.world_state, payload.self_expression_context) == (
        {},
        {},
        {},
        {},
    )
