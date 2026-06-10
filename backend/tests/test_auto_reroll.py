"""Tests for the joint auto-reroll cycle (Validator + LanguageGuard).

Coverage:
  _reroll_reasons:
    * validator unacceptable → ['validator'] (gated by on_validator)
    * language_guard not ok → ['language_guard'] (gated by on_language_guard)
    * skipped / passing payloads → []
  _build_reroll_hint:
    * mentions expected language and violations
  _run_compliance_pipeline_with_reroll:
    * disabled → no regeneration even when checks fail
    * enabled + failing first candidate + passing second → content replaced,
      reroll log recorded, checks re-ran on the new candidate
    * retry still failing → last candidate kept, attempts == max_attempts
    * empty retry content → previous output kept
    * generation error during retry → previous output kept, never raises
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

import modules.generative.conversation as conv


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _config(overrides: Dict[str, Any]):
    def fake_get(key: str, default: Any = None):
        if key in overrides:
            return overrides[key]
        return default

    return fake_get


@pytest.fixture()
def quiet_checks(monkeypatch):
    """Neutralise the non-gating checks so tests focus on the reroll cycle."""
    monkeypatch.setattr(
        conv, "_maybe_run_confidence", lambda **kwargs: {"skipped": True}
    )
    monkeypatch.setattr(
        conv, "_maybe_run_factuality", lambda **kwargs: {"skipped": True}
    )
    monkeypatch.setattr(
        conv, "_maybe_run_self_watcher", lambda **kwargs: {"skipped": True}
    )


class _StubResult:
    def __init__(self, content: str, provider: str = "stub"):
        self.content = content
        self.reasoning = ""
        self.provider = provider
        self.metadata = {"stub": True}


# ---------------------------------------------------------------------------
# _reroll_reasons / _build_reroll_hint
# ---------------------------------------------------------------------------


def test_reasons_validator_failure(monkeypatch):
    monkeypatch.setattr(conv.config_service, "get_config_value", _config({}))
    reasons = conv._reroll_reasons({"acceptable": False, "compliance": 0.2}, {"ok": True})
    assert reasons == ["validator"]


def test_reasons_language_failure(monkeypatch):
    monkeypatch.setattr(conv.config_service, "get_config_value", _config({}))
    reasons = conv._reroll_reasons(
        {"acceptable": True}, {"ok": False, "detected": "latin", "expected": "ru-RU"}
    )
    assert reasons == ["language_guard"]


def test_reasons_respect_gates(monkeypatch):
    monkeypatch.setattr(
        conv.config_service,
        "get_config_value",
        _config({"auto_reroll.on_validator": False, "auto_reroll.on_language_guard": False}),
    )
    reasons = conv._reroll_reasons({"acceptable": False}, {"ok": False})
    assert reasons == []


def test_reasons_skipped_payloads(monkeypatch):
    monkeypatch.setattr(conv.config_service, "get_config_value", _config({}))
    assert conv._reroll_reasons({"skipped": True}, {"skipped": True}) == []
    assert conv._reroll_reasons({}, {}) == []
    assert conv._reroll_reasons({"acceptable": True}, {"ok": True}) == []


def test_hint_contains_language_and_violations():
    hint = conv._build_reroll_hint(
        ["validator", "language_guard"],
        {"violations": ["no emoji allowed", "too long"]},
        {"detected": "latin", "expected": "ru-RU"},
    )
    assert "ru-RU" in hint
    assert "no emoji allowed" in hint
    assert "latin" in hint


# ---------------------------------------------------------------------------
# _run_compliance_pipeline_with_reroll
# ---------------------------------------------------------------------------


def _run(monkeypatch, *, config: Dict[str, Any], validator_seq, language_seq, retry_results):
    """Drive the pipeline with scripted check results and retry outputs."""
    monkeypatch.setattr(conv.config_service, "get_config_value", _config(config))

    validator_iter = iter(validator_seq)
    language_iter = iter(language_seq)
    monkeypatch.setattr(
        conv, "_maybe_run_validator", lambda **kwargs: next(validator_iter)
    )
    monkeypatch.setattr(
        conv, "_maybe_run_language_guard", lambda **kwargs: next(language_iter)
    )

    calls = []

    class _StubManager:
        def generate(self, request):
            calls.append(request)
            outcome = retry_results[len(calls) - 1]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr(conv, "generation_manager", _StubManager())

    outcome = conv._run_compliance_pipeline_with_reroll(
        decision_context={},
        last_user_message={"content": "привет"},
        assistant_content="original reply",
        assistant_reasoning="",
        provider="orig-provider",
        metadata={"orig": True},
        history=[],
        chat_history=[{"role": "system", "content": "persona"}],
        request_options={"temperature": 0.7},
    )
    return outcome, calls


def test_disabled_no_regeneration(monkeypatch, quiet_checks):
    outcome, calls = _run(
        monkeypatch,
        config={"auto_reroll.enabled": False},
        validator_seq=[{"acceptable": False, "violations": ["x"]}],
        language_seq=[{"ok": True}],
        retry_results=[],
    )
    assert outcome["assistant_content"] == "original reply"
    assert outcome["reroll"] is None
    assert calls == []


def test_reroll_replaces_content(monkeypatch, quiet_checks):
    outcome, calls = _run(
        monkeypatch,
        config={"auto_reroll.enabled": True, "auto_reroll.max_attempts": 2},
        validator_seq=[
            {"acceptable": False, "violations": ["broke rule"]},
            {"acceptable": True, "compliance": 0.9},
        ],
        language_seq=[{"ok": True}, {"ok": True}],
        retry_results=[_StubResult("fixed reply", provider="retry-provider")],
    )
    assert outcome["assistant_content"] == "fixed reply"
    assert outcome["provider"] == "retry-provider"
    assert outcome["reroll"]["attempts"] == 1
    assert outcome["compliance"]["validator"]["acceptable"] is True
    assert len(calls) == 1
    # Corrective hint travels as a trailing system message with the previous
    # attempt right before it.
    retry_messages = calls[0].messages
    assert retry_messages[-2]["role"] == "assistant"
    assert retry_messages[-2]["content"] == "original reply"
    assert "[QUALITY RETRY]" in retry_messages[-1]["content"]


def test_reroll_keeps_last_failing_candidate(monkeypatch, quiet_checks):
    outcome, calls = _run(
        monkeypatch,
        config={"auto_reroll.enabled": True, "auto_reroll.max_attempts": 1},
        validator_seq=[
            {"acceptable": False, "violations": ["a"]},
            {"acceptable": False, "violations": ["still bad"]},
        ],
        language_seq=[{"ok": True}, {"ok": True}],
        retry_results=[_StubResult("second try")],
    )
    assert outcome["assistant_content"] == "second try"
    assert outcome["reroll"]["attempts"] == 1
    assert outcome["compliance"]["validator"]["acceptable"] is False
    assert len(calls) == 1


def test_reroll_empty_retry_keeps_previous(monkeypatch, quiet_checks):
    outcome, calls = _run(
        monkeypatch,
        config={"auto_reroll.enabled": True, "auto_reroll.max_attempts": 2},
        validator_seq=[{"acceptable": False, "violations": ["x"]}],
        language_seq=[{"ok": True}],
        retry_results=[_StubResult("")],
    )
    assert outcome["assistant_content"] == "original reply"
    assert outcome["reroll"] is None
    assert len(calls) == 1


def test_reroll_generation_error_never_raises(monkeypatch, quiet_checks):
    outcome, calls = _run(
        monkeypatch,
        config={"auto_reroll.enabled": True, "auto_reroll.max_attempts": 2},
        validator_seq=[{"acceptable": False, "violations": ["x"]}],
        language_seq=[{"ok": True}],
        retry_results=[RuntimeError("provider down")],
    )
    assert outcome["assistant_content"] == "original reply"
    assert outcome["reroll"] is None
    assert len(calls) == 1
