"""Tests for the LLM-as-judge output validator (0.9.0 Wave 2, §3.5 step 1).

Mocks generation_manager — no real LLM call. Covers:
  * default disabled → ValidationResult(skipped=True, reason='disabled')
  * empty output → skipped without LLM call (no_output)
  * happy path: JSON response parsed into compliance + violations
  * tolerates fenced and prose-wrapped JSON
  * coerces compliance to [0,1], filters non-string violations
  * NoProviderResolved → skipped (no_provider), no exception
  * generic exception → skipped (generate_error), no exception
  * malformed response → skipped (parse_error), no exception
  * is_acceptable() respects threshold + skipped semantics
  * input truncation limits the prompt size
  * get_compliance_threshold reads DB config
"""

from __future__ import annotations

import pytest

from modules.validator import service as validator_service
from modules.validator import validate_output
from modules.validator.types import ValidationResult


class _FakeResult:
    def __init__(self, content: str):
        self.content = content


@pytest.fixture
def enable_validator(monkeypatch):
    """Force validator.enabled = True regardless of DB state."""
    monkeypatch.setattr(validator_service, "_is_enabled", lambda: True)


def _stub_generation(monkeypatch, *, content: str | None = None, exc: Exception | None = None):
    from modules.generative import manager as gen_mod

    def _fake(request):
        if exc is not None:
            raise exc
        return _FakeResult(content or "")

    monkeypatch.setattr(gen_mod.generation_manager, "generate", _fake)


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_disabled_by_default_returns_skipped(monkeypatch):
    # Force disabled regardless of the live DB config — the operator may
    # have validator.enabled=true in their instance, the test must not
    # depend on it.
    monkeypatch.setattr(validator_service, "_is_enabled", lambda: False)
    result = validate_output(output="hi", instructions="say hi")
    assert result.skipped is True
    assert result.skip_reason == "disabled"
    assert result.is_acceptable(threshold=0.99) is True  # skipped = pass


@pytest.mark.regression
def test_empty_output_skipped_without_llm_call(enable_validator, monkeypatch):
    called = {"n": 0}

    def _should_not_call(request):
        called["n"] += 1
        return _FakeResult("{}")

    from modules.generative import manager as gen_mod
    monkeypatch.setattr(gen_mod.generation_manager, "generate", _should_not_call)

    result = validate_output(output="  ", instructions="anything")
    assert result.skipped is True
    assert result.skip_reason == "empty_output"
    assert called["n"] == 0


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_returns_score_and_violations(enable_validator, monkeypatch):
    _stub_generation(
        monkeypatch,
        content='{"compliance": 0.4, "violations": ["used forbidden word", "ignored hard directive"]}',
    )
    result = validate_output(output="bad text", instructions="don't use X; MUST do Y")
    assert result.skipped is False
    assert result.compliance == pytest.approx(0.4)
    assert result.violations == ["used forbidden word", "ignored hard directive"]


@pytest.mark.regression
def test_tolerates_code_fence(enable_validator, monkeypatch):
    _stub_generation(
        monkeypatch,
        content='```json\n{"compliance": 0.9, "violations": []}\n```',
    )
    result = validate_output(output="ok", instructions="say ok")
    assert result.compliance == pytest.approx(0.9)
    assert result.violations == []


@pytest.mark.regression
def test_tolerates_prose_around_json(enable_validator, monkeypatch):
    _stub_generation(
        monkeypatch,
        content='Here is my judgment: {"compliance": 0.85, "violations": ["minor tone drift"]} hope this helps.',
    )
    result = validate_output(output="x", instructions="y")
    assert result.compliance == pytest.approx(0.85)
    assert result.violations == ["minor tone drift"]


# ---------------------------------------------------------------------------
# Coercion
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_compliance_clamped_to_range(enable_validator, monkeypatch):
    _stub_generation(
        monkeypatch,
        content='{"compliance": 1.7, "violations": []}',
    )
    assert validate_output(output="x", instructions="y").compliance == 1.0

    _stub_generation(
        monkeypatch,
        content='{"compliance": -0.4, "violations": []}',
    )
    assert validate_output(output="x", instructions="y").compliance == 0.0


@pytest.mark.regression
def test_violations_filters_non_strings_and_empties(enable_validator, monkeypatch):
    _stub_generation(
        monkeypatch,
        content='{"compliance": 0.5, "violations": ["real", "", null, "  ", "another"]}',
    )
    result = validate_output(output="x", instructions="y")
    # null in JSON, empty/whitespace strings get dropped; real ones kept.
    assert result.violations == ["real", "another"]


@pytest.mark.regression
def test_invalid_compliance_value_defaults_to_zero(enable_validator, monkeypatch):
    _stub_generation(
        monkeypatch,
        content='{"compliance": "high", "violations": ["x"]}',
    )
    result = validate_output(output="x", instructions="y")
    assert result.compliance == 0.0


# ---------------------------------------------------------------------------
# Error paths — never raise
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_no_provider_returns_skipped(enable_validator, monkeypatch):
    from modules.generative.manager import NoProviderResolved
    _stub_generation(monkeypatch, exc=NoProviderResolved("no llm available"))
    result = validate_output(output="x", instructions="y")
    assert result.skipped is True
    assert result.skip_reason == "no_provider"


@pytest.mark.regression
def test_generic_exception_returns_skipped(enable_validator, monkeypatch):
    _stub_generation(monkeypatch, exc=RuntimeError("network down"))
    result = validate_output(output="x", instructions="y")
    assert result.skipped is True
    assert result.skip_reason == "generate_error"


@pytest.mark.regression
def test_malformed_response_returns_skipped_parse_error(enable_validator, monkeypatch):
    _stub_generation(monkeypatch, content="this is not json and has no braces")
    result = validate_output(output="x", instructions="y")
    assert result.skipped is True
    assert result.skip_reason == "parse_error"


@pytest.mark.regression
def test_empty_llm_response_returns_skipped(enable_validator, monkeypatch):
    _stub_generation(monkeypatch, content="")
    result = validate_output(output="x", instructions="y")
    assert result.skipped is True
    assert result.skip_reason == "empty_response"


# ---------------------------------------------------------------------------
# Acceptance semantics
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_is_acceptable_respects_threshold():
    result = ValidationResult(compliance=0.75, violations=[])
    assert result.is_acceptable(threshold=0.7) is True
    assert result.is_acceptable(threshold=0.8) is False


@pytest.mark.regression
def test_skipped_counts_as_acceptable_at_any_threshold():
    result = ValidationResult(skipped=True, skip_reason="disabled")
    assert result.is_acceptable(threshold=0.99) is True
    assert result.is_acceptable(threshold=0.0) is True


# ---------------------------------------------------------------------------
# Truncation + threshold getter
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_long_inputs_get_truncated_in_prompt(enable_validator, monkeypatch):
    captured = {}

    def _fake(request):
        captured["user"] = next(
            (m["content"] for m in request.messages if m.get("role") == "user"), ""
        )
        return _FakeResult('{"compliance": 1.0, "violations": []}')

    from modules.generative import manager as gen_mod
    monkeypatch.setattr(gen_mod.generation_manager, "generate", _fake)

    huge_output = "X" * 50_000
    huge_instructions = "Y" * 50_000
    validate_output(output=huge_output, instructions=huge_instructions)

    assert "[…truncated]" in captured["user"]
    # Sanity: total prompt size is much smaller than 100KB — limits kicked in.
    assert len(captured["user"]) < 20_000


@pytest.mark.regression
def test_get_compliance_threshold_reads_config(monkeypatch):
    monkeypatch.setattr(
        validator_service.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: 0.42 if path == "validator.threshold" else default,
    )
    assert validator_service.get_compliance_threshold() == 0.42


@pytest.mark.regression
def test_get_compliance_threshold_clamps_invalid_values(monkeypatch):
    monkeypatch.setattr(
        validator_service.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: "not-a-number" if path == "validator.threshold" else default,
    )
    # Falls back to default (0.7).
    assert validator_service.get_compliance_threshold() == pytest.approx(0.7)
