"""Tests for Validator + DebugVault integration in conversation.generate_standard
(0.9.0 Wave 2, §3.5+6 step 3).

We don't run the full generate_standard pipeline here — too much setup needed
for the streaming/storage/WS side. Instead we test the two glue helpers
directly:

  * _build_validator_instructions assembles system_prompt + hard directives
    in the priority order the validator prompt expects.
  * _maybe_run_validator routes the result correctly:
      - validator disabled / skipped → no DebugVault write
      - compliance ≥ threshold → no DebugVault write
      - compliance < threshold → DebugVault entry created with audit_logs mirror

write_vault_entry is mocked where convenient so we don't depend on the live
DB row count between tests.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from modules.generative import conversation
from modules.validator.types import ValidationResult


# ---------------------------------------------------------------------------
# _build_validator_instructions
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_instructions_combine_directives_then_system_prompt():
    text = conversation._build_validator_instructions(
        {
            "system_prompt": "You are PAI.",
            "moral_state": {"hard_directives": ["MUST avoid politics", "NEVER use word X"]},
        }
    )
    # Hard directives appear first because they outweigh the system prompt in
    # validator scoring.
    assert text.startswith("HARD DIRECTIVES")
    assert "- MUST avoid politics" in text
    assert "- NEVER use word X" in text
    assert "You are PAI." in text


@pytest.mark.regression
def test_instructions_skip_empty_directives_section():
    text = conversation._build_validator_instructions(
        {"system_prompt": "You are PAI.", "moral_state": {"hard_directives": []}}
    )
    assert "HARD DIRECTIVES" not in text
    assert text == "You are PAI."


@pytest.mark.regression
def test_instructions_handle_missing_moral_state():
    text = conversation._build_validator_instructions({"system_prompt": "P"})
    assert text == "P"


@pytest.mark.regression
def test_instructions_handle_blank_inputs():
    text = conversation._build_validator_instructions({})
    assert text == ""


# ---------------------------------------------------------------------------
# _maybe_run_validator
# ---------------------------------------------------------------------------


def _patch_validator_result(monkeypatch, result: ValidationResult) -> None:
    """Stub modules.validator.validate_output via the import inside _maybe_run_validator."""
    from modules import validator as validator_pkg
    monkeypatch.setattr(validator_pkg, "validate_output", lambda **kwargs: result)


def _patch_threshold(monkeypatch, value: float) -> None:
    from modules.validator import service as validator_service
    monkeypatch.setattr(
        validator_service,
        "get_compliance_threshold",
        lambda: value,
    )


@pytest.mark.regression
def test_maybe_run_validator_short_circuits_on_empty_instructions(monkeypatch):
    """No instructions → no LLM call, no vault write."""
    vault_calls = []

    from modules import debug_vault as vault_pkg
    monkeypatch.setattr(
        vault_pkg,
        "write_vault_entry",
        lambda **kwargs: vault_calls.append(kwargs) or "vault-id",
    )

    out = conversation._maybe_run_validator(
        decision_context={},
        last_user_message={"content": "hi"},
        assistant_content="bye",
        provider="ollama",
        metadata={},
    )
    assert out == {"skipped": True, "skip_reason": "empty_instructions"}
    assert vault_calls == []


@pytest.mark.regression
def test_maybe_run_validator_skipped_result_no_vault_write(monkeypatch):
    _patch_validator_result(
        monkeypatch,
        ValidationResult(skipped=True, skip_reason="disabled"),
    )
    vault_calls = []
    from modules import debug_vault as vault_pkg
    monkeypatch.setattr(
        vault_pkg,
        "write_vault_entry",
        lambda **kwargs: vault_calls.append(kwargs) or "vault-id",
    )

    out = conversation._maybe_run_validator(
        decision_context={"system_prompt": "You are PAI."},
        last_user_message={"content": "hi"},
        assistant_content="bye",
        provider="ollama",
        metadata={},
    )
    assert out["skipped"] is True
    assert vault_calls == []


@pytest.mark.regression
def test_maybe_run_validator_pass_no_vault_write(monkeypatch):
    _patch_validator_result(
        monkeypatch,
        ValidationResult(compliance=0.85, violations=[], skipped=False),
    )
    _patch_threshold(monkeypatch, 0.7)
    vault_calls = []
    from modules import debug_vault as vault_pkg
    monkeypatch.setattr(
        vault_pkg,
        "write_vault_entry",
        lambda **kwargs: vault_calls.append(kwargs) or "vault-id",
    )

    out = conversation._maybe_run_validator(
        decision_context={"system_prompt": "You are PAI."},
        last_user_message={"content": "hi"},
        assistant_content="ok output",
        provider="ollama",
        metadata={},
    )
    assert out["acceptable"] is True
    assert out["compliance"] == pytest.approx(0.85)
    assert vault_calls == []


@pytest.mark.regression
def test_maybe_run_validator_fail_writes_vault(monkeypatch):
    _patch_validator_result(
        monkeypatch,
        ValidationResult(
            compliance=0.3,
            violations=["used forbidden word", "ignored MUST"],
            skipped=False,
        ),
    )
    _patch_threshold(monkeypatch, 0.7)

    vault_calls = []
    from modules import debug_vault as vault_pkg
    monkeypatch.setattr(
        vault_pkg,
        "write_vault_entry",
        lambda **kwargs: vault_calls.append(kwargs) or "vault-id-123",
    )

    out = conversation._maybe_run_validator(
        decision_context={
            "system_prompt": "You are PAI.",
            "moral_state": {"hard_directives": ["MUST avoid X"]},
        },
        last_user_message={"id": "msg-42", "content": "user input"},
        assistant_content="bad output content",
        provider="ollama",
        metadata={"model": "llama3.2"},
    )

    assert out["acceptable"] is False
    assert out["compliance"] == pytest.approx(0.3)
    assert out["vault_entry_id"] == "vault-id-123"

    # Vault was called once with the right structured payload.
    assert len(vault_calls) == 1
    call = vault_calls[0]
    assert call["kind"] == "validation_failed"
    assert "Validator compliance" in call["summary"]
    assert call["violations"] == ["used forbidden word", "ignored MUST"]
    assert call["output"] == "bad output content"
    assert call["context"]["user_message_id"] == "msg-42"
    assert call["runtime_meta"]["compliance"] == pytest.approx(0.3)
    assert call["runtime_meta"]["threshold"] == pytest.approx(0.7)


@pytest.mark.regression
def test_maybe_run_validator_vault_failure_does_not_raise(monkeypatch):
    """If DebugVault write itself throws, validator integration must swallow it."""
    _patch_validator_result(
        monkeypatch,
        ValidationResult(compliance=0.3, violations=["x"], skipped=False),
    )
    _patch_threshold(monkeypatch, 0.7)

    def _explode(**kwargs):
        raise RuntimeError("vault on fire")

    from modules import debug_vault as vault_pkg
    monkeypatch.setattr(vault_pkg, "write_vault_entry", _explode)

    out = conversation._maybe_run_validator(
        decision_context={"system_prompt": "P"},
        last_user_message={"content": "hi"},
        assistant_content="bad",
        provider="ollama",
        metadata={},
    )
    # No exception escaped; result still tells us validator failed.
    assert out["acceptable"] is False
    assert "vault_entry_id" not in out  # never assigned
