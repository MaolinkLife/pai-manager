"""The system knows whether it can see, and why not.

A vision model that also thinks declares
vision and thinking in Ollama's metadata. The probe let it reason, reasoning
spent the whole token budget, the answer came back empty and the model was
marked unavailable as "empty probe response". An image the user attached then
reached the assistant as nothing at all, so it believed no image was sent.

No probe is run at all now (models are not run to check what
they can do): readiness is what the metadata declares, and an unusable answer
names its exact reason when the image is described.
"""

import asyncio

import pytest
from PIL import Image

import modules.vision.providers.ollama_vision as ollama_vision
from core import decision_layer as decision_layer_module
from core.decision_layer import DecisionLayer
from core.instructor import Instructor
from modules.ollama import client as ollama_client
from modules.system.logger import AuditStatus
from modules.vision.providers.ollama_vision import OllamaVisionProvider
from modules.vision.visual_module import VisualModule

pytestmark = pytest.mark.regression

REASONING_EXHAUSTED = "reasoning used the whole token budget before any answer"


# --- the Ollama client ----------------------------------------------------


class FakeResponse:
    def __init__(self, status_code=200, data=None, text=""):
        self.status_code = status_code
        self._data = data or {}
        self.text = text
        self.reason = "error"

    def json(self):
        return self._data


@pytest.fixture
def ollama_post(monkeypatch):
    sent = []

    def install(response=None, error=None):
        def fake_post(url, *, payload, timeout, retries=2, retry_backoff_sec=0.6):
            sent.append(payload)
            if error:
                raise error
            return response

        monkeypatch.setattr(ollama_client, "_post_json_with_retries", fake_post)
        return sent

    return install


def test_chat_image_response_switches_reasoning_off_when_asked(ollama_post):
    sent = ollama_post(FakeResponse(data={"message": {"content": "a red square", "thinking": ""}, "done_reason": "stop"}))

    result = ollama_client.chat_image_response(
        [{"role": "user", "content": "look"}], "vision:test", options={"num_predict": 64, "__think": False}
    )

    assert sent[0]["think"] is False
    assert sent[0]["options"] == {"num_predict": 64}
    assert result == {"content": "a red square", "thinking": "", "done_reason": "stop"}


def test_chat_image_response_keeps_ollama_fields_of_an_empty_answer(ollama_post):
    ollama_post(FakeResponse(data={"message": {"content": "", "thinking": "let me think"}, "done_reason": "length"}))

    result = ollama_client.chat_image_response([], "vision:test")

    assert (result["content"], result["thinking"], result["done_reason"]) == ("", "let me think", "length")


@pytest.mark.parametrize(
    "response, error, expected",
    [
        (FakeResponse(data={"error": "model not found"}), None, "[ERROR] model not found"),
        (FakeResponse(status_code=500, text="boom"), None, "[ERROR] Ollama HTTP 500: boom"),
        (None, ConnectionError("refused"), "[ERROR] Visual model request failed: refused"),
    ],
)
def test_chat_image_keeps_its_error_strings(ollama_post, response, error, expected):
    ollama_post(response, error)

    assert ollama_client.chat_image([], "vision:test") == expected


# --- the vision provider --------------------------------------------------


@pytest.fixture
def audit(monkeypatch):
    events = []
    monkeypatch.setattr(
        ollama_vision,
        "log_audit_entry",
        lambda event, message, status=None, details=None, **kwargs: events.append((event, status, details or {})),
    )
    return events


@pytest.fixture
def ollama(monkeypatch):
    calls = []

    def install(*capabilities, answer=None, available=True):
        monkeypatch.setattr(ollama_vision.ollama_client, "is_available", lambda: available)
        monkeypatch.setattr(
            ollama_vision.ollama_client,
            "model_supports_vision",
            lambda model: {"supported": "vision" in capabilities, "capabilities": list(capabilities), "reason": "no vision in metadata"},
        )

        def fake_response(messages, model=None, options=None, keep_alive=None):
            calls.append(options)
            return answer

        monkeypatch.setattr(ollama_vision.ollama_client, "chat_image_response", fake_response)
        return calls

    return install


def _provider():
    return OllamaVisionProvider({"model": "vision:test", "max_tokens": 256})


def _describe():
    return _provider().describe_image(Image.new("RGB", (16, 16), "red"), "What is on the screen?")


def test_a_thinking_model_is_asked_not_to_reason(ollama, audit):
    calls = ollama("completion", "vision", "thinking", answer={"content": "red square", "thinking": "", "done_reason": "stop"})

    assert _describe()["status"] == "success"
    assert len(calls) == 1
    assert calls[0]["__think"] is False


def test_a_model_without_thinking_gets_the_request_unchanged(ollama, audit):
    calls = ollama("completion", "vision", answer={"content": "red square", "thinking": "", "done_reason": "stop"})

    assert _describe()["status"] == "success"
    assert "__think" not in calls[0]


@pytest.mark.parametrize(
    "answer, reason",
    [
        ({"content": "", "thinking": "hmm, a square...", "done_reason": "length"}, REASONING_EXHAUSTED),
        ({"content": "", "thinking": "", "done_reason": "length"}, "the token limit cut the answer before any text"),
        ({"content": "", "thinking": "", "done_reason": "stop"}, "the model returned an empty answer"),
        ({"error": "Ollama HTTP 500: boom"}, "Ollama HTTP 500: boom"),
    ],
)
def test_the_description_names_exactly_why_the_answer_is_unusable(ollama, audit, answer, reason):
    ollama("completion", "vision", "thinking", answer=answer)

    result = _describe()

    assert result["status"] == "error"
    assert reason in result["summary"]


def test_a_model_whose_metadata_declares_no_vision_is_not_asked(ollama, audit):
    calls = ollama("completion", "tools", answer={"content": "should not be asked"})
    provider = _provider()

    assert provider.is_ready() is False
    assert calls == []
    [details] = [details for event, _, details in audit if event == "vision_ollama_not_declared"]
    assert details["capabilities"] == ["completion", "tools"]


def test_ollama_switched_off_is_a_state_not_a_crash(ollama, audit):
    calls = ollama("completion", "vision", available=False, answer={"content": "unused"})
    provider = _provider()

    assert provider.is_ready() is False
    assert provider._last_probe_error == "ollama is unavailable"
    assert calls == []


def test_visual_module_reports_the_provider_reason():
    module = VisualModule.__new__(VisualModule)
    module.provider_name = "ollama_vision"
    module.provider = type("Provider", (), {"_last_probe_error": REASONING_EXHAUSTED})()

    assert module.unavailable_reason() == REASONING_EXHAUSTED


# --- the turn: decision layer and instructor (smoke) ----------------------


class NotReadyVision:
    def is_ready(self):
        return False

    def unavailable_reason(self):
        return REASONING_EXHAUSTED


@pytest.fixture
def layer(monkeypatch):
    settings = {
        "vision.enabled": True,
        "vision.screen_capture_enabled": True,
        "vision.active_provider": "ollama_vision",
    }
    monkeypatch.setattr(
        decision_layer_module.config_service,
        "get_config_value",
        lambda path, default=None: settings.get(path, default),
    )
    instance = DecisionLayer.__new__(DecisionLayer)
    instance._visual_module = NotReadyVision()
    instance._visual_module_failed = False
    return instance


def test_an_attached_image_is_not_lost_when_vision_cannot_look(layer):
    media = [{"category": "image", "name": "photo.png", "data": "aGVsbG8="}]

    context = asyncio.run(layer._collect_visual_context(media, {"needs_vision": True}))

    assert context["attachments"]["unavailable"] is True
    assert context["attachments"]["count"] == 1
    assert context["attachments"]["reason"] == REASONING_EXHAUSTED


def test_a_screen_request_says_the_eyes_are_off(layer):
    context = asyncio.run(layer._collect_visual_context([], {"needs_vision": True}, screen_allowed=True))

    assert context == {"screen": {"unavailable": True, "reason": REASONING_EXHAUSTED}}


def _vision_tool(monkeypatch, visual_context):
    instructor = Instructor()
    monkeypatch.setattr(instructor, "_build_environment_tool_content", lambda: "Time: 12:00")
    messages = asyncio.run(
        instructor.format_for_api(
            system_prompt="base",
            user_message={"id": "u1", "content": "что ты тут видишь?", "history": []},
            visual_context=visual_context,
        )
    )
    return "\n".join(m["content"] for m in messages if m.get("role") == "tool" and m.get("name") == "vision.context")


def test_the_assistant_is_told_it_could_not_look_at_the_attachment(monkeypatch):
    content = _vision_tool(
        monkeypatch,
        {"attachments": {"items": [], "count": 1, "unavailable": True, "reason": REASONING_EXHAUSTED}},
    )

    assert "attached 1 image" in content
    assert REASONING_EXHAUSTED in content
    assert "say so honestly" in content


def test_the_assistant_is_told_it_cannot_see_the_screen(monkeypatch):
    content = _vision_tool(monkeypatch, {"screen": {"unavailable": True, "reason": "ollama is unavailable"}})

    assert "cannot see the screen" in content
    assert "ollama is unavailable" in content


def test_a_described_attachment_still_reaches_the_assistant(monkeypatch):
    content = _vision_tool(
        monkeypatch,
        {"attachments": {"items": [{"name": "photo.png", "description": "a red square"}]}},
    )

    assert content == "photo.png: a red square"
