"""A generated image is looked at and scored against what was asked.

Vision describes the result, a judge scores
relevance to the request (on by default, 0.60) and strict quality (off by
default, 0.82). Below a threshold the image is still delivered unless reroll
is on, and every such request leaves one DebugVault entry with all attempts.
A check that cannot run says why and never counts as a pass.

Vision, the judge, image generation and DebugVault are fakes here.
"""

import asyncio
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from constants.paths import STORAGE_DIR
from modules.synthesis import image_check, media_pipeline
from modules.synthesis.image_check import (
    CheckedAttempt,
    ImageCheckSettings,
    check_generated_image,
    record_low_results,
)
from modules.synthesis.media_pipeline import MediaPipelineRequest, MediaPipelineResult
from modules.synthesis.types import ImageGenerationResult

pytestmark = pytest.mark.regression

REQUEST = "Lim reading a book by the window"
DESCRIPTION = "An anime woman sits by a window holding an open book, evening light."


def _png(color="red"):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _settings(**overrides):
    config = {
        "relevance": {"enabled": True, "threshold": 0.6, "reroll": False},
        "quality": {"enabled": False, "threshold": 0.82, "reroll": False},
        "max_generations": 2,
    }
    for key, value in overrides.items():
        if isinstance(value, dict):
            config[key] = {**config[key], **value}
        else:
            config[key] = value
    return config


@pytest.fixture
def check_config(monkeypatch):
    state = {"config": _settings()}
    original = image_check.config_service.get_config_value

    def get_config_value(path, default=None, user_uuid=None):
        if path == "synthesis.image_check":
            return state["config"]
        return original(path, default, user_uuid=user_uuid)

    monkeypatch.setattr(image_check.config_service, "get_config_value", get_config_value)
    return state


def _described(summary=DESCRIPTION, status="success"):
    return lambda image_bytes, prompt=None: {"summary": summary, "status": status}


def _judge(*verdicts, calls=None):
    answers = list(verdicts)

    def judge(system, user):
        if calls is not None:
            calls.append(user)
        return json.dumps(answers.pop(0))

    return judge


# --- settings -------------------------------------------------------------


def test_defaults_check_relevance_only_and_generate_once(check_config):
    check_config["config"] = {}

    settings = ImageCheckSettings.from_config()

    assert (settings.relevance.enabled, settings.relevance.threshold) == (True, 0.6)
    assert (settings.quality.enabled, settings.quality.threshold) == (False, 0.82)
    assert settings.max_generations == 2
    assert settings.generations_allowed() == 1


def test_generations_are_allowed_only_while_an_enabled_check_may_reroll(check_config):
    check_config["config"] = _settings(quality={"reroll": True}, max_generations=3)
    assert ImageCheckSettings.from_config().generations_allowed() == 1  # quality is off

    check_config["config"] = _settings(relevance={"reroll": True}, max_generations=3)
    assert ImageCheckSettings.from_config().generations_allowed() == 3


def test_thresholds_and_generations_stay_in_range(check_config):
    check_config["config"] = _settings(relevance={"threshold": 0.01}, quality={"threshold": 7}, max_generations=99)

    settings = ImageCheckSettings.from_config()

    assert (settings.relevance.threshold, settings.quality.threshold) == (0.1, 1.0)
    assert settings.max_generations == image_check.MAX_GENERATIONS_CAP


def test_check_prompts_come_from_the_settings_and_an_empty_field_means_built_in(check_config):
    check_config["config"] = _settings(describe_prompt="  ", system_prompt="Judge strictly.", user_template="R={request}")

    settings = ImageCheckSettings.from_config()

    assert settings.describe_prompt == image_check.SYNTHESIS_IMAGE_CHECK_DESCRIBE_PROMPT
    assert settings.system_prompt == "Judge strictly."
    assert settings.user_template == "R={request}"


# --- the check ------------------------------------------------------------


def test_relevance_below_threshold_is_low(check_config):
    result = check_generated_image(
        _png(),
        request_text=REQUEST,
        prompt="anime woman, window",
        settings=ImageCheckSettings.from_config(),
        describe=_described(),
        judge=_judge({"relevance": 0.42, "quality": None, "mismatches": ["no book"], "feedback": "add a book"}),
    )

    assert result.status == "low"
    assert (result.relevance, result.quality, result.failed) == (0.42, None, ["relevance"])
    assert result.mismatches == ["no book"] and result.feedback == "add a book"
    assert result.description == DESCRIPTION


def test_the_judge_is_asked_only_for_enabled_scores(check_config):
    calls = []
    check_config["config"] = _settings(quality={"enabled": True})

    result = check_generated_image(
        _png(),
        request_text=REQUEST,
        prompt="p",
        settings=ImageCheckSettings.from_config(),
        describe=_described(),
        judge=_judge({"relevance": 0.9, "quality": 0.5}, calls=calls),
    )

    assert "Scores: relevance, quality" in calls[0]
    assert REQUEST in calls[0] and DESCRIPTION in calls[0]
    assert (result.status, result.failed) == ("low", ["quality"])


def test_vision_and_the_judge_get_the_prompts_from_the_settings(check_config, monkeypatch):
    check_config["config"] = _settings(
        describe_prompt="Say what is drawn.",
        system_prompt="Judge strictly.",
        user_template="Only {scores} for: {request} / {description}",
    )
    seen = {}

    def describe(image_bytes, prompt):
        seen["describe_prompt"] = prompt
        return {"summary": DESCRIPTION, "status": "success"}

    def judge(system, user):
        seen["system"], seen["user"] = system, user
        return json.dumps({"relevance": 0.9})

    monkeypatch.setattr(image_check, "_describe_with_vision", describe)

    result = check_generated_image(
        _png(), request_text=REQUEST, prompt="p", settings=ImageCheckSettings.from_config(), judge=judge,
    )

    assert result.status == "passed"
    assert seen["describe_prompt"] == "Say what is drawn."
    assert seen["system"] == "Judge strictly."
    assert seen["user"] == f"Only relevance for: {REQUEST} / {DESCRIPTION}"


@pytest.mark.parametrize("template", ["{unknown} {request}", "{request", "{0}", "{request.missing}"])
def test_a_broken_template_falls_back_to_the_built_in_one_and_says_so(check_config, monkeypatch, template):
    from modules.system import technical_prompts

    check_config["config"] = _settings(user_template=template)
    events = []
    monkeypatch.setattr(
        technical_prompts, "log_audit_entry",
        lambda event, message, status=None, details=None, **kwargs: events.append((event, status, details)),
    )
    calls = []

    result = check_generated_image(
        _png(), request_text=REQUEST, prompt="p", settings=ImageCheckSettings.from_config(),
        describe=_described(), judge=_judge({"relevance": 0.9}, calls=calls),
    )

    assert result.status == "passed"
    assert "Scores: relevance" in calls[0] and REQUEST in calls[0]
    [(event, status, details)] = events
    assert (event, status) == ("technical_prompt_template_invalid", image_check.AuditStatus.WARNING)
    assert details["path"] == "synthesis.image_check.user_template"


def test_a_passed_image(check_config):
    result = check_generated_image(
        _png(), request_text=REQUEST, prompt="p", settings=ImageCheckSettings.from_config(),
        describe=_described(), judge=_judge({"relevance": 0.91}),
    )

    assert (result.status, result.failed) == ("passed", [])


def test_a_verdict_in_code_fences_is_read(check_config):
    result = check_generated_image(
        _png(), request_text=REQUEST, prompt="p", settings=ImageCheckSettings.from_config(),
        describe=_described(), judge=lambda system, user: '```json\n{"relevance": 0.7}\n```',
    )

    assert result.relevance == 0.7


@pytest.mark.parametrize(
    "describe, judge, reason_part",
    [
        (_described("Visual module not available: ollama is unavailable", status="not_ready"), None, "vision could not describe"),
        (_described(), "raise", "judge model is unavailable"),
        (_described(), "not json", "not valid JSON"),
        (_described(), '{"quality": 0.9}', "no relevance score"),
    ],
)
def test_a_check_that_cannot_run_says_why_and_never_passes(check_config, describe, judge, reason_part):
    def judge_fn(system, user):
        if judge == "raise":
            raise RuntimeError("no provider resolved")
        return judge

    result = check_generated_image(
        _png(), request_text=REQUEST, prompt="p", settings=ImageCheckSettings.from_config(),
        describe=describe, judge=judge_fn,
    )

    assert result.status == "not_checked"
    assert reason_part in result.reason
    assert result.relevance is None and result.quality is None


def test_checks_switched_off_do_not_look_at_the_image(check_config):
    check_config["config"] = _settings(relevance={"enabled": False})

    def describe(image_bytes):
        raise AssertionError("vision must not be asked")

    result = check_generated_image(
        _png(), request_text=REQUEST, prompt="p", settings=ImageCheckSettings.from_config(), describe=describe,
    )

    assert result.status == "disabled"


# --- DebugVault -----------------------------------------------------------


@pytest.fixture
def vault(monkeypatch):
    entries = []
    from modules.debug_vault import service as vault_service

    def write_vault_entry(**kwargs):
        entries.append(kwargs)
        return f"vault-{len(entries)}"

    monkeypatch.setattr(vault_service, "write_vault_entry", write_vault_entry)
    return entries


def _attempt(number, status, relevance, prompt="p"):
    return CheckedAttempt(
        attempt=number,
        prompt=prompt,
        negative_prompt="blurry",
        image_bytes=_png(),
        check=image_check.ImageCheckResult(
            status=status, description=DESCRIPTION, relevance=relevance,
            failed=["relevance"] if status == "low" else [], mismatches=["no book"] if status == "low" else [],
        ),
    )


def test_a_low_result_leaves_one_entry_with_the_image(check_config, vault):
    entry_id = record_low_results(
        [_attempt(1, "low", 0.42, prompt="anime woman, window")],
        request_text=REQUEST, model_id="image_gen_test", provider="core", source="main_chat",
        settings=ImageCheckSettings.from_config(),
    )

    assert entry_id == "vault-1"
    [entry] = vault
    assert entry["kind"] == "image_check_low"
    assert "relevance 0.42 < 0.60" in entry["summary"] and "delivered below threshold" in entry["summary"]
    context = entry["context"]
    assert (context["model_id"], context["request"], context["thresholds"]) == ("image_gen_test", REQUEST, {"relevance": 0.6})
    [attempt] = context["attempts"]
    assert attempt["prompt"] == "anime woman, window" and attempt["relevance"] == 0.42
    assert (Path(STORAGE_DIR) / attempt["image_path"]).is_file()
    assert entry["violations"] == ["no book"]


def test_passed_results_leave_no_entry(check_config, vault):
    entry_id = record_low_results(
        [_attempt(1, "passed", 0.9)],
        request_text=REQUEST, model_id="m", provider="core", source="test", settings=ImageCheckSettings.from_config(),
    )

    assert entry_id is None and vault == []


# --- the media pipeline, whole run (smoke) --------------------------------


@pytest.fixture
def pipeline(monkeypatch, check_config, vault):
    state = {"prompts": [], "refined": [], "judge_calls": [], "verdicts": [], "describe": _described()}

    def generate_image(request):
        state["prompts"].append(request.prompt)
        return ImageGenerationResult(provider="core", image_bytes=_png(), model_id="image_gen_test")

    def refine(**kwargs):
        state["refined"].append(kwargs["feedback"])
        return f"refined: {kwargs['feedback']}", kwargs["previous_negative"]

    def judge(system, user):
        state["judge_calls"].append(user)
        return json.dumps(state["verdicts"].pop(0))

    monkeypatch.setattr(media_pipeline.synthesis_service, "generate_image", generate_image)
    monkeypatch.setattr(media_pipeline.synthesis_service, "refine_prompts_from_feedback", refine)
    monkeypatch.setattr(
        image_check, "_describe_with_vision", lambda image_bytes, prompt=None: state["describe"](image_bytes)
    )
    monkeypatch.setattr(image_check, "_judge_with_model", judge)

    def run():
        request = MediaPipelineRequest(
            mode="direct", prompt=REQUEST, image_provider="core", image_model="image_gen_test", source="test",
        )
        return asyncio.run(media_pipeline.media_generation_pipeline.run_image(request))

    state["run"] = run
    return state


def test_a_low_image_is_delivered_and_recorded(pipeline, vault):
    pipeline["verdicts"] = [{"relevance": 0.3, "mismatches": ["no book"], "feedback": "add a book"}]

    result = pipeline["run"]()

    assert len(pipeline["prompts"]) == 1
    assert result.image_bytes
    assert result.vision_description == DESCRIPTION
    meta = result.metadata["image_check"]
    assert (meta["status"], meta["generations"], meta["vault_entry_id"]) == ("low", 1, "vault-1")
    assert len(vault) == 1 and len(vault[0]["context"]["attempts"]) == 1


def test_a_passed_image_leaves_no_entry(pipeline, vault):
    pipeline["verdicts"] = [{"relevance": 0.9}]

    result = pipeline["run"]()

    assert result.metadata["image_check"]["status"] == "passed"
    assert result.metadata["image_check"]["vault_entry_id"] is None
    assert vault == []


def test_reroll_generates_again_from_the_feedback_until_it_passes(pipeline, check_config, vault):
    check_config["config"] = _settings(relevance={"reroll": True}, max_generations=3)
    pipeline["verdicts"] = [{"relevance": 0.3, "feedback": "add a book"}, {"relevance": 0.8}]

    result = pipeline["run"]()

    assert pipeline["prompts"][1] == "refined: add a book"
    assert result.image_prompt == "refined: add a book"
    meta = result.metadata["image_check"]
    assert (meta["status"], meta["generations"]) == ("passed", 2)
    [entry] = vault
    assert entry["context"]["delivered_attempt"] == 2
    assert len(entry["context"]["attempts"]) == 2
    assert "passed on attempt 2" in entry["summary"]


def test_rerolls_stop_at_the_generation_limit(pipeline, check_config, vault):
    check_config["config"] = _settings(relevance={"reroll": True}, max_generations=2)
    pipeline["verdicts"] = [{"relevance": 0.3, "feedback": "add a book"}, {"relevance": 0.2, "feedback": "still no book"}]

    result = pipeline["run"]()

    assert len(pipeline["prompts"]) == 2
    assert result.metadata["image_check"]["status"] == "low"
    [entry] = vault
    assert len(entry["context"]["attempts"]) == 2 and "delivered below threshold" in entry["summary"]


def test_a_hand_written_prompt_is_neither_checked_nor_regenerated(pipeline, check_config, vault):
    check_config["config"] = _settings(relevance={"reroll": True}, max_generations=3)
    request = MediaPipelineRequest(
        mode="direct", manual_prompt=True, prompt=REQUEST, image_provider="core", image_model="image_gen_test", source="synthesis_hub",
    )

    result = asyncio.run(media_pipeline.media_generation_pipeline.run_image(request))

    assert len(pipeline["prompts"]) == 1
    assert result.metadata["image_check"]["status"] == "disabled"
    assert pipeline["judge_calls"] == [] and vault == []


def test_every_check_result_is_written_to_the_audit_log(check_config, monkeypatch):
    events = []
    monkeypatch.setattr(
        image_check, "log_audit_entry",
        lambda event, message, status=None, details=None, **kwargs: events.append((event, status, details or {})),
    )

    check_generated_image(
        _png(), request_text=REQUEST, prompt="p", settings=ImageCheckSettings.from_config(),
        describe=_described(), judge=_judge({"relevance": 0.2, "mismatches": ["no book"]}),
    )

    [(status, details)] = [(status, details) for event, status, details in events if event == "synthesis_image_checked"]
    assert details["scores"] == {"relevance": 0.2} and details["failed"] == ["relevance"]
    assert status == image_check.AuditStatus.WARNING


def test_without_vision_the_image_is_delivered_unchecked(pipeline, check_config, vault):
    check_config["config"] = _settings(relevance={"reroll": True})
    pipeline["describe"] = _described("Visual module not available: ollama is unavailable", status="not_ready")

    result = pipeline["run"]()

    assert len(pipeline["prompts"]) == 1
    meta = result.metadata["image_check"]
    assert meta["status"] == "not_checked" and "ollama is unavailable" in meta["reason"]
    assert pipeline["judge_calls"] == [] and vault == []
    assert result.vision_description == ""


# --- main chat uses the description of the check (smoke) ------------------


def _pipeline_result(description):
    return MediaPipelineResult(
        provider="core", model="image_gen_test", content="Image generated.", media=[], image_bytes=_png(),
        mime_type="image/png", image_base64="", image_prompt="p", negative_prompt="", image_parameters={},
        vision_description=description,
    )


def _prepare_chat_image(monkeypatch, description, vision_summary=None):
    from modules.generative import conversation

    async def run_image(request, trace_hook=None):
        return _pipeline_result(description)

    class FakeVisualModule:
        def __init__(self):
            if vision_summary is None:
                raise AssertionError("vision must not be asked twice")

        def describe_image(self, image, prompt):
            return {"summary": vision_summary, "status": "success"}

    monkeypatch.setattr(conversation, "_build_main_chat_image_prompt", lambda **kwargs: json.dumps({"prompt": REQUEST, "negative_prompt": ""}))
    monkeypatch.setattr(conversation.media_generation_pipeline, "run_image", run_image)
    monkeypatch.setattr(conversation, "VisualModule", FakeVisualModule)
    decision_context = {"image_generation": {"enabled": True, "reason": "test"}, "system_prompt": "base"}
    asyncio.run(
        conversation._prepare_main_chat_image_context(
            decision_context=decision_context,
            last_user_message={"content": "нарисуй себя за книгой"},
            memory_context={},
        )
    )
    return decision_context


def test_main_chat_reuses_the_description_of_the_check(monkeypatch):
    decision_context = _prepare_chat_image(monkeypatch, DESCRIPTION)

    assert decision_context["generated_image_context"]["description"] == DESCRIPTION
    assert DESCRIPTION in decision_context["system_prompt"]


def test_main_chat_asks_vision_itself_when_the_check_did_not_describe(monkeypatch):
    decision_context = _prepare_chat_image(monkeypatch, "", vision_summary="a girl with a book")

    assert decision_context["generated_image_context"]["description"] == "a girl with a book"
