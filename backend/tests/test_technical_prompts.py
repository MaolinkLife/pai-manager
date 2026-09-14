"""Technical prompts are preset in the config and editable from the UI.

An empty field means the built-in text; a template
broken in the settings falls back to the built-in one and the journal says so.
Compliance tab: validator, confidence, self-watcher reflection.
Memory tab: contradiction judge, day summary, diary.
Moral matrix tab: the matrix prompt, inner voice.
Core and analyzer tabs: orchestrator, instructor schema, analyzer prompt.
Vision tab: attached pictures, the screen, generated pictures.
"""

from datetime import date, datetime, timezone

import pytest

from constants.default_config import DEFAULT_CONFIG
from constants.prompts import (
    COGNITIVE_ANALYSIS_PROMPT,
    CONFIDENCE_ESTIMATION_PROMPT,
    DECISION_LAYER_ORCHESTRATOR_PROMPT,
    IMAGE_SCENE_FORMAT_PROMPT,
    INSTRUCTOR_BUILD_SCHEMA_PROMPT,
    MEDIA_IMAGE_PROMPT_BUILDER_SYSTEM_PROMPT,
    MEDIA_IMAGE_PROMPT_BUILDER_USER_TEMPLATE,
    SYNTHESIS_IMAGE_CHECK_DESCRIBE_PROMPT,
    SYNTHESIS_IMAGE_CHECK_SYSTEM_PROMPT,
    SYNTHESIS_IMAGE_CHECK_USER_TEMPLATE,
    DAILY_ACTIVITY_DIARY_SYSTEM_PROMPT,
    DAILY_ACTIVITY_DIARY_USER_PROMPT_TEMPLATE,
    MEMORY_JUDGE_CONTRADICTION_PROMPT,
    MORAL_INNER_VOICE_PROMPT,
    MORAL_MATRIX_PROVIDER_PROMPT,
    SELF_WATCHER_REFLECTION_PROMPT,
    SHORT_TERM_DAILY_SUMMARY_SYSTEM_PROMPT,
    SHORT_TERM_DAILY_SUMMARY_TASK_PROMPT,
    VALIDATOR_COMPLIANCE_PROMPT,
    VISION_ATTACHMENT_PROMPT,
    VISION_GENERATED_IMAGE_PROMPT,
    VISION_SCREEN_PROMPT,
)
from modules.generative.manager import generation_manager
from modules.system import config as config_service
from modules.system import technical_prompts
from modules.system.technical_prompts import configured_prompt, filled_prompt

pytestmark = pytest.mark.regression

PRESET_PROMPTS = [
    ("validator.system_prompt", VALIDATOR_COMPLIANCE_PROMPT),
    ("confidence.system_prompt", CONFIDENCE_ESTIMATION_PROMPT),
    ("self_watcher.reflection_prompt", SELF_WATCHER_REFLECTION_PROMPT),
    ("memory.consolidation.judge.system_prompt", MEMORY_JUDGE_CONTRADICTION_PROMPT),
    ("memory.short_term.summary_system_prompt", SHORT_TERM_DAILY_SUMMARY_SYSTEM_PROMPT),
    ("memory.short_term.summary_task_prompt", SHORT_TERM_DAILY_SUMMARY_TASK_PROMPT),
    ("memory.diary.system_prompt", DAILY_ACTIVITY_DIARY_SYSTEM_PROMPT),
    ("memory.diary.user_template", DAILY_ACTIVITY_DIARY_USER_PROMPT_TEMPLATE),
    ("moral.system_prompt", MORAL_MATRIX_PROVIDER_PROMPT),
    ("moral.inner_voice.system_prompt", MORAL_INNER_VOICE_PROMPT),
    ("decision_layer.orchestrator_prompt", DECISION_LAYER_ORCHESTRATOR_PROMPT),
    ("decision_layer.instructor.build_schema", INSTRUCTOR_BUILD_SCHEMA_PROMPT),
    ("analyzer.system_prompt", COGNITIVE_ANALYSIS_PROMPT),
    ("vision.attachment_prompt", VISION_ATTACHMENT_PROMPT),
    ("vision.generated_image_prompt", VISION_GENERATED_IMAGE_PROMPT),
    ("vision.screen_prompt", VISION_SCREEN_PROMPT),
    ("synthesis.image_check.describe_prompt", SYNTHESIS_IMAGE_CHECK_DESCRIBE_PROMPT),
    ("synthesis.image_check.system_prompt", SYNTHESIS_IMAGE_CHECK_SYSTEM_PROMPT),
    ("synthesis.image_check.user_template", SYNTHESIS_IMAGE_CHECK_USER_TEMPLATE),
    ("synthesis.image_scene.format_prompt", IMAGE_SCENE_FORMAT_PROMPT),
    ("synthesis.prompting.image_prompt_builder_system_prompt", MEDIA_IMAGE_PROMPT_BUILDER_SYSTEM_PROMPT),
    ("synthesis.prompting.image_prompt_builder_user_template", MEDIA_IMAGE_PROMPT_BUILDER_USER_TEMPLATE),
]


def _value(tree, path):
    for part in path.split("."):
        tree = tree[part]
    return tree


class _Answer:
    def __init__(self, content):
        self.content = content
        self.reasoning = ""


@pytest.fixture
def settings(monkeypatch):
    values = {}
    monkeypatch.setattr(
        config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: values.get(path, default),
    )
    return values


@pytest.fixture
def journal(monkeypatch):
    events = []
    monkeypatch.setattr(
        technical_prompts,
        "log_audit_entry",
        lambda event, message, status=None, details=None, **kwargs: events.append((event, details or {})),
    )
    return events


@pytest.fixture
def model(monkeypatch):
    requests = []

    def answer_with(content):
        def generate(request):
            requests.append(request)
            return _Answer(content)

        monkeypatch.setattr(generation_manager, "generate", generate)
        return requests

    return answer_with


# --- the setting ------------------------------------------------------------


@pytest.mark.parametrize("path, built_in", PRESET_PROMPTS)
def test_the_defaults_carry_the_built_in_prompt(path, built_in):
    assert _value(DEFAULT_CONFIG, path) == built_in


@pytest.mark.parametrize("path, built_in", PRESET_PROMPTS)
def test_reset_to_default_gets_the_built_in_prompt(path, built_in):
    from routes.config_routes import get_default_config

    assert _value(get_default_config(), path) == built_in


def test_an_edited_prompt_is_used(settings):
    settings["validator.system_prompt"] = "judge strictly"

    assert configured_prompt("validator.system_prompt", "built-in") == "judge strictly"


@pytest.mark.parametrize("stored", [None, "", "   \n", 42])
def test_an_empty_prompt_is_the_built_in_one(settings, stored):
    settings["validator.system_prompt"] = stored

    assert configured_prompt("validator.system_prompt", "built-in") == "built-in"


def test_an_edited_template_gets_its_placeholders(settings, journal):
    settings["self_watcher.reflection_prompt"] = "Reflect in {language}."

    text = filled_prompt("self_watcher.reflection_prompt", "Built-in {language}.", language="ru-RU")

    assert text == "Reflect in ru-RU."
    assert journal == []


@pytest.mark.parametrize("broken", ["Reflect in {language", "Reflect about {mood}", "Reflect {0}"])
def test_a_broken_template_falls_back_and_is_journaled(settings, journal, broken):
    settings["self_watcher.reflection_prompt"] = broken

    text = filled_prompt("self_watcher.reflection_prompt", "Built-in {language}.", language="ru-RU")

    assert text == "Built-in ru-RU."
    [(event, details)] = journal
    assert event == "technical_prompt_template_invalid"
    assert details["path"] == "self_watcher.reflection_prompt"


# --- the modules ask with it ------------------------------------------------


def test_the_validator_asks_with_the_edited_prompt(settings, model):
    from modules.validator import validate_output

    settings.update({"validator.enabled": True, "validator.system_prompt": "judge strictly"})
    requests = model('{"compliance": 1.0, "violations": []}')

    result = validate_output(output="hi", instructions="say hi")

    assert result.skipped is False
    assert requests[0].messages[0] == {"role": "system", "content": "judge strictly"}


def test_confidence_asks_with_the_edited_prompt(settings, model):
    from modules.confidence import estimate_confidence

    settings.update({"confidence.enabled": True, "confidence.system_prompt": "estimate strictly"})
    requests = model('{"confidence": 0.9}')

    result = estimate_confidence(user_message="hi", assistant_output="hey")

    assert result.skipped is False
    assert requests[0].messages[0] == {"role": "system", "content": "estimate strictly"}


def test_the_nightly_reflection_asks_with_the_edited_prompt(settings, model, monkeypatch):
    from modules.self_watcher import service as self_watcher_service

    settings.update(
        {
            "self_watcher": {"enabled": True, "nightly_reflection_enabled": True},
            "self_watcher.reflection_prompt": "Думай о себе, язык: {language}.",
        }
    )
    monkeypatch.setattr(
        self_watcher_service.self_watcher_repository,
        "list_recent",
        lambda **kwargs: [
            {
                "pai_predicted_emotion": "joy",
                "pai_predicted_valence": "positive",
                "user_actual_tone": "anger",
                "user_actual_valence": "negative",
                "mismatch_score": 0.8,
            }
        ],
    )
    monkeypatch.setattr("modules.system.user.resolve_user_language", lambda **kwargs: "ru-RU")
    requests = model("Я заметила, что путаю игру с серьёзностью.")

    text = self_watcher_service.record_nightly_reflection(character_id="character", day=date(2026, 9, 13))

    assert text == "Я заметила, что путаю игру с серьёзностью."
    assert requests[0].messages[0] == {"role": "system", "content": "Думай о себе, язык: ru-RU."}


def test_the_memory_judge_asks_with_the_edited_prompt(settings, monkeypatch):
    from modules.memory import diary

    settings["memory.consolidation.judge.system_prompt"] = "judge the memories"
    sent = []

    def chat(messages, options, model=None):
        sent.append(messages)
        return {"message": {"content": '{"matches": []}'}}

    monkeypatch.setattr("modules.ollama.client.chat", chat)

    answer = diary._call_judge_llm(
        payload={"new_entry": {}},
        settings={"provider": "ollama", "model": "", "temperature": 0.0, "max_tokens": 64, "request_timeout": 5},
    )

    assert answer == '{"matches": []}'
    assert sent[0][0] == {"role": "system", "content": "judge the memories"}


def test_the_diary_asks_with_the_edited_prompts(settings, model):
    from modules.memory import diary

    settings.update(
        {
            "memory.diary.system_prompt": "Write the diary in {language}.",
            "memory.diary.user_template": "{day} / {language} / {stats_json} / {transcript}",
        }
    )
    requests = model('{"mood": "calm", "summary": "a quiet day"}')

    diary._summarize_activity(day=date(2026, 9, 13), stats={"messages": 2}, transcript="user: hi", language="ru-RU")

    system, user = requests[0].messages
    assert system == {"role": "system", "content": "Write the diary in ru-RU."}
    assert user == {"role": "user", "content": '2026-09-13 / ru-RU / {"messages": 2} / user: hi'}


def test_the_day_summary_asks_with_the_edited_prompts(settings, model):
    from modules.memory import short_term

    settings.update(
        {
            "memory.short_term.summary_system_prompt": "Summarize the day as JSON.",
            "memory.short_term.summary_task_prompt": "What stayed with you today?",
        }
    )
    requests = model('{"summary": "a warm talk", "themes": ["coffee"]}')

    summary, themes = short_term._generate_day_summary("user: hi", datetime(2026, 9, 13, tzinfo=timezone.utc))

    assert (summary, themes) == ("a warm talk", ["coffee"])
    system, user = requests[0].messages
    assert system == {"role": "system", "content": "Summarize the day as JSON."}
    assert "What stayed with you today?" in user["content"]


def test_the_inner_voice_asks_with_the_edited_prompt(settings, model):
    from modules.moral_matrix.service import MoralMatrixModule

    settings["moral.inner_voice.system_prompt"] = "Say in one sentence why you feel it."
    requests = model("Мне тепло, потому что ты вернулся.")

    text = MoralMatrixModule.__new__(MoralMatrixModule)._generate_inner_voice(
        emotion="joy",
        intensity=0.6,
        cause="the user came back",
        language_hint="ru-RU",
    )

    assert text == "Мне тепло, потому что ты вернулся."
    assert requests[0].messages[0] == {"role": "system", "content": "Say in one sentence why you feel it."}


def test_the_orchestrator_asks_with_the_edited_prompt(settings, monkeypatch):
    import asyncio

    from core import decision_layer as decision_layer_module
    from core.decision_layer import DecisionLayer

    settings.update(
        {
            "decision_layer.orchestrator_prompt": "Route this message.",
            "decision_layer.providers.ollama": {"model": "router:test"},
        }
    )
    sent = []

    def chat_with_tools(messages, options, model, tools=None, tool_choice=None):
        sent.append(messages)
        return {"message": {"content": '{"needs_vision": false}'}}

    monkeypatch.setattr(decision_layer_module.ollama_client, "chat_with_tools", chat_with_tools)
    monkeypatch.setattr(decision_layer_module.ollama_client, "release_model", lambda **kwargs: None)
    monkeypatch.setattr(decision_layer_module, "log_audit_entry", lambda *args, **kwargs: None)

    asyncio.run(DecisionLayer.__new__(DecisionLayer)._make_llm_decisions({}, {"content": "look at this"}))

    assert sent[0][0] == {"role": "system", "content": "Route this message."}


# --- vision -----------------------------------------------------------------


class _SeeingProvider:
    def __init__(self):
        self.prompts = []

    def is_ready(self):
        return True

    def describe_image(self, image, prompt):
        self.prompts.append(prompt)
        return {"summary": "a red square", "status": "success"}


def _visual_module(provider):
    from modules.vision.visual_module import VisualModule

    module = VisualModule.__new__(VisualModule)
    module.provider_name = "test"
    module.provider = provider
    return module


def test_stored_vision_settings_get_the_built_in_prompts(monkeypatch):
    monkeypatch.setattr(config_service, "_load_user_tts_settings_from_db", lambda user_uuid: None)
    monkeypatch.setattr(
        config_service,
        "_load_user_vision_settings_from_db",
        lambda user_uuid: {"enabled": True, "screen_prompt": "my screen prompt"},
    )
    config = {}

    config_service._apply_split_settings_overrides(config, "owner")

    assert config["vision"]["attachment_prompt"] == VISION_ATTACHMENT_PROMPT
    assert config["vision"]["generated_image_prompt"] == VISION_GENERATED_IMAGE_PROMPT
    assert config["vision"]["screen_prompt"] == "my screen prompt"


def test_an_attached_picture_is_described_with_the_edited_prompt(settings, monkeypatch):
    import base64
    import io

    from PIL import Image

    from modules.vision import visual_module

    monkeypatch.setattr(visual_module, "log_audit_entry", lambda *args, **kwargs: None)
    settings.update({"vision.enabled": True, "vision.attachment_prompt": "Say what they sent."})
    picture = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(picture, format="PNG")
    provider = _SeeingProvider()

    result = _visual_module(provider).describe_media_attachments(
        [{"category": "image", "data": base64.b64encode(picture.getvalue()).decode()}]
    )

    assert result["prompt"] == "Say what they sent."
    assert provider.prompts == ["Say what they sent."]


def test_the_screen_is_described_with_the_edited_prompt(settings, monkeypatch):
    import numpy as np

    from modules.vision import service as vision_service_module
    from modules.vision import visual_module

    monkeypatch.setattr(visual_module, "log_audit_entry", lambda *args, **kwargs: None)
    settings.update(
        {
            "vision.enabled": True,
            "vision.screen_capture_enabled": True,
            "vision.screen_prompt": "Say what is on the screen.",
        }
    )

    class _Buffer:
        def get_latest_frames(self, n):
            return [(1757770000.0, np.zeros((8, 8, 3), dtype=np.uint8))]

    class _Service:
        def __init__(self):
            self.buffer = _Buffer()

    monkeypatch.setattr(vision_service_module, "VisionService", _Service)
    provider = _SeeingProvider()

    snapshot = _visual_module(provider).describe_screen_snapshot()

    assert snapshot["prompt"] == "Say what is on the screen."
    assert provider.prompts == ["Say what is on the screen."]


def test_a_generated_picture_is_described_with_the_edited_prompt(settings):
    from modules.generative import conversation

    settings["vision.generated_image_prompt"] = "Describe what you drew."

    assert conversation._generated_image_describe_prompt() == "Describe what you drew."


# --- media -------------------------------------------------------------------


def test_the_image_prompt_builder_asks_with_the_edited_prompts(settings, journal):
    from modules.synthesis import media_pipeline

    settings.update(
        {
            "synthesis.prompting.image_prompt_builder_system_prompt": "Compose an image prompt.",
            "synthesis.prompting.image_prompt_builder_user_template": "Context:\n{tool_context}",
        }
    )

    system, user = media_pipeline._image_prompt_builder_prompts("time: evening")

    assert (system, user) == ("Compose an image prompt.", "Context:\ntime: evening")
    assert journal == []


def test_a_broken_image_prompt_builder_template_falls_back_and_is_journaled(settings, journal):
    from modules.synthesis import media_pipeline

    settings["synthesis.prompting.image_prompt_builder_user_template"] = "Context: {tool_context"

    _, user = media_pipeline._image_prompt_builder_prompts("time: evening")

    assert user == MEDIA_IMAGE_PROMPT_BUILDER_USER_TEMPLATE.format(tool_context="time: evening")
    [(event, details)] = journal
    assert details["path"] == "synthesis.prompting.image_prompt_builder_user_template"
