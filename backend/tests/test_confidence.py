"""Tests for confidence estimation (0.9.0 Wave 2, §3.8).

Coverage:
  * estimate_confidence returns skipped when disabled
  * estimate_confidence returns skipped for empty output / empty user message
  * estimate_confidence parses well-formed JSON
  * tolerates fenced markdown ```json blocks
  * tolerates JSON wrapped in prose
  * malformed JSON → skipped(parse_error), never raises
  * out-of-range float gets clamped to [0, 1]
  * non-numeric confidence field → skipped(parse_error)
  * ConfidenceResult.is_low truth table (incl. skipped → False)
  * _maybe_run_confidence in conversation:
      - disabled → skipped payload, no audit warning, no runtime_meta update
      - high score → INFO audit, no warning
      - low score → WARNING audit
      - empty user message → skipped(empty_user_message)
"""

from __future__ import annotations

import pytest

from modules.confidence import estimate_confidence, get_confidence_threshold
from modules.confidence.types import ConfidenceResult
from modules.confidence import service as confidence_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubResult:
    def __init__(self, content: str) -> None:
        self.content = content
        self.reasoning = ""


def _enable(monkeypatch, *, threshold: float = 0.5):
    from modules.system import config as config_service

    def _fake_get(key, default=None):
        if key == "confidence.enabled":
            return True
        if key == "confidence.threshold":
            return threshold
        if key == "confidence.max_tokens":
            return 64
        if key == "confidence.temperature":
            return 0.0
        if key == "confidence.user_char_limit":
            return 2000
        if key == "confidence.output_char_limit":
            return 4000
        return default

    monkeypatch.setattr(config_service, "get_config_value", _fake_get)


def _stub_llm(monkeypatch, response_text: str):
    from modules.generative.manager import generation_manager

    monkeypatch.setattr(
        generation_manager,
        "generate",
        lambda req: _StubResult(response_text),
    )


# ---------------------------------------------------------------------------
# Service unit
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_estimate_disabled_returns_skipped(monkeypatch):
    from modules.system import config as config_service
    monkeypatch.setattr(
        config_service,
        "get_config_value",
        lambda key, default=None: (False if key == "confidence.enabled" else default),
    )
    r = estimate_confidence(user_message="hi", assistant_output="hey")
    assert r.skipped is True
    assert r.skip_reason == "disabled"


@pytest.mark.regression
def test_estimate_empty_output_skipped(monkeypatch):
    _enable(monkeypatch)
    r = estimate_confidence(user_message="hi", assistant_output="")
    assert r.skipped is True
    assert r.skip_reason == "empty_output"


@pytest.mark.regression
def test_estimate_empty_user_message_skipped(monkeypatch):
    _enable(monkeypatch)
    r = estimate_confidence(user_message="", assistant_output="reply")
    assert r.skipped is True
    assert r.skip_reason == "empty_user_message"


@pytest.mark.regression
def test_estimate_parses_well_formed_json(monkeypatch):
    _enable(monkeypatch)
    _stub_llm(monkeypatch, '{"confidence": 0.82}')
    r = estimate_confidence(user_message="what is 2+2?", assistant_output="4")
    assert r.skipped is False
    assert r.score == pytest.approx(0.82)


@pytest.mark.regression
def test_estimate_tolerates_fenced_json(monkeypatch):
    _enable(monkeypatch)
    _stub_llm(monkeypatch, "```json\n{\"confidence\": 0.45}\n```")
    r = estimate_confidence(user_message="q", assistant_output="a")
    assert r.score == pytest.approx(0.45)
    assert r.skipped is False


@pytest.mark.regression
def test_estimate_recovers_json_from_prose(monkeypatch):
    _enable(monkeypatch)
    _stub_llm(
        monkeypatch,
        "Sure, here is my estimate: {\"confidence\": 0.9} hope that helps.",
    )
    r = estimate_confidence(user_message="q", assistant_output="a")
    assert r.score == pytest.approx(0.9)


@pytest.mark.regression
def test_estimate_malformed_json_returns_skipped(monkeypatch):
    _enable(monkeypatch)
    _stub_llm(monkeypatch, "I think 0.7 is fine, no JSON sorry")
    r = estimate_confidence(user_message="q", assistant_output="a")
    assert r.skipped is True
    assert r.skip_reason == "parse_error"


@pytest.mark.regression
def test_estimate_clamps_out_of_range(monkeypatch):
    _enable(monkeypatch)
    _stub_llm(monkeypatch, '{"confidence": 1.7}')
    r = estimate_confidence(user_message="q", assistant_output="a")
    assert r.score == 1.0

    _stub_llm(monkeypatch, '{"confidence": -0.5}')
    r = estimate_confidence(user_message="q", assistant_output="a")
    assert r.score == 0.0


@pytest.mark.regression
def test_estimate_non_numeric_field_skipped(monkeypatch):
    _enable(monkeypatch)
    _stub_llm(monkeypatch, '{"confidence": "high"}')
    r = estimate_confidence(user_message="q", assistant_output="a")
    assert r.skipped is True
    assert r.skip_reason == "parse_error"


@pytest.mark.regression
def test_is_low_truth_table():
    assert ConfidenceResult(score=0.4).is_low(0.5) is True
    assert ConfidenceResult(score=0.6).is_low(0.5) is False
    assert ConfidenceResult(score=0.5).is_low(0.5) is False  # equal is not low
    # skipped is never low
    assert ConfidenceResult(skipped=True).is_low(0.99) is False


@pytest.mark.regression
def test_get_confidence_threshold_clamps(monkeypatch):
    from modules.system import config as config_service
    monkeypatch.setattr(
        config_service,
        "get_config_value",
        lambda key, default=None: 1.7 if key == "confidence.threshold" else default,
    )
    assert get_confidence_threshold() == 1.0


# ---------------------------------------------------------------------------
# Conversation integration
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_maybe_run_confidence_disabled_returns_skipped(monkeypatch):
    from modules.generative import conversation
    from modules.system import config as config_service

    monkeypatch.setattr(
        config_service,
        "get_config_value",
        lambda key, default=None: (False if key == "confidence.enabled" else default),
    )

    payload = conversation._maybe_run_confidence(
        last_user_message={"content": "hi"},
        assistant_content="hey",
    )
    assert payload.get("skipped") is True
    assert payload.get("skip_reason") == "disabled"


@pytest.mark.regression
def test_maybe_run_confidence_high_emits_info(monkeypatch):
    from modules.generative import conversation
    _enable(monkeypatch, threshold=0.5)
    _stub_llm(monkeypatch, '{"confidence": 0.85}')

    payload = conversation._maybe_run_confidence(
        last_user_message={"id": "msg-1", "content": "how are you"},
        assistant_content="I am doing well, thank you for asking.",
    )
    assert payload["skipped"] is False
    assert payload["score"] == pytest.approx(0.85)
    assert payload["low"] is False
    assert payload["threshold"] == pytest.approx(0.5)


@pytest.mark.regression
def test_maybe_run_confidence_low_emits_warning(monkeypatch):
    from modules.generative import conversation
    _enable(monkeypatch, threshold=0.5)
    _stub_llm(monkeypatch, '{"confidence": 0.2}')

    payload = conversation._maybe_run_confidence(
        last_user_message={"id": "msg-2", "content": "what year did pluto get reclassified"},
        assistant_content="It was 1932, I'm sure.",
    )
    assert payload["low"] is True
    assert payload["score"] == pytest.approx(0.2)


@pytest.mark.regression
def test_maybe_run_confidence_empty_user_skipped(monkeypatch):
    from modules.generative import conversation
    _enable(monkeypatch, threshold=0.5)

    payload = conversation._maybe_run_confidence(
        last_user_message={"content": ""},
        assistant_content="some output text",
    )
    assert payload["skipped"] is True
    assert payload["skip_reason"] == "empty_user_message"
