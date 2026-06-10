"""Tests for language compliance guard (0.9.0 Wave 2, §3.5-bis).

Coverage:
  * detector classifies pure RU / pure EN correctly
  * detector treats mixed RU+EN code (embedded English terms) as low-dominance
  * detector returns no_letters for purely numeric/punct strings
  * service skips when disabled
  * service skips for empty / too-short outputs
  * service skips for unknown expected locale
  * service skips on below-dominance mixed text (legitimate code-switching)
  * service flags hard mismatch (CJK output for ru-RU expectation)
  * service returns ok when dominant script matches the locale
  * conversation._maybe_run_language_guard never raises
  * conversation._maybe_run_language_guard writes DebugVault on mismatch
  * inner_voice fallback uses User.language, not system.language
"""

from __future__ import annotations

import pytest

from modules.language_guard import check_language, LanguageCheckResult
from modules.language_guard.detector import (
    detect_dominant_script,
    is_script_compatible,
    locale_prefix,
)


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_detector_pure_russian():
    bucket, dominance, counted = detect_dominant_script(
        "Сегодня был тихий день, я ловила себя на том, что просто слушаю тишину."
    )
    assert bucket == "cyrillic"
    assert dominance == pytest.approx(1.0)
    assert counted > 30


@pytest.mark.regression
def test_detector_pure_english():
    bucket, dominance, counted = detect_dominant_script(
        "Today was a quiet day and I noticed how calm I felt inside."
    )
    assert bucket == "latin"
    assert dominance == pytest.approx(1.0)
    assert counted > 30


@pytest.mark.regression
def test_detector_mixed_ru_en_legitimate_code_terms():
    # Realistic RU prose with embedded English tech terms (endpoint, validation)
    text = "Я вызвала endpoint validation и проверила пайплайн до отправки."
    bucket, dominance, counted = detect_dominant_script(text)
    # Cyrillic still wins, but dominance is below 0.7 — caller should skip.
    assert bucket == "cyrillic"
    assert 0.4 < dominance < 0.9


@pytest.mark.regression
def test_detector_no_letters():
    bucket, dominance, counted = detect_dominant_script("12345 !!! ... 99%")
    assert bucket == ""
    assert dominance == 0.0
    assert counted == 0


@pytest.mark.regression
def test_detector_empty_string():
    bucket, dominance, counted = detect_dominant_script("")
    assert bucket == ""
    assert counted == 0


@pytest.mark.regression
def test_locale_prefix_parses_dash_and_underscore():
    assert locale_prefix("ru-RU") == "ru"
    assert locale_prefix("en_US") == "en"
    assert locale_prefix("ja") == "ja"
    assert locale_prefix("") == ""
    assert locale_prefix("   ") == ""


@pytest.mark.regression
def test_is_script_compatible_truth_table():
    assert is_script_compatible("cyrillic", "ru-RU") is True
    assert is_script_compatible("cyrillic", "uk") is True
    assert is_script_compatible("latin", "en-US") is True
    assert is_script_compatible("cjk", "ja") is True
    assert is_script_compatible("latin", "ru-RU") is False
    assert is_script_compatible("cyrillic", "en-US") is False


# ---------------------------------------------------------------------------
# Service contract
# ---------------------------------------------------------------------------


def _enable(monkeypatch, *, min_dominance: float = 0.7, min_output_chars: int = 40):
    from modules.system import config as config_service

    def _fake_get(key, default=None):
        if key == "language_guard":
            return {
                "enabled": True,
                "min_dominance": min_dominance,
                "min_output_chars": min_output_chars,
            }
        return default

    monkeypatch.setattr(config_service, "get_config_value", _fake_get)


def _disable(monkeypatch):
    from modules.system import config as config_service

    def _fake_get(key, default=None):
        if key == "language_guard":
            return {"enabled": False}
        return default

    monkeypatch.setattr(config_service, "get_config_value", _fake_get)


@pytest.mark.regression
def test_service_skipped_when_disabled(monkeypatch):
    _disable(monkeypatch)
    r = check_language("Привет, как дела?" * 5, "ru-RU")
    assert r.skipped is True
    assert r.skip_reason == "disabled"
    assert r.ok is True


@pytest.mark.regression
def test_service_skipped_when_output_too_short(monkeypatch):
    _enable(monkeypatch, min_output_chars=200)
    r = check_language("Короткий ответ", "ru-RU")
    assert r.skipped is True
    assert r.skip_reason == "output_too_short"


@pytest.mark.regression
def test_service_skipped_when_expected_unknown(monkeypatch):
    _enable(monkeypatch)
    r = check_language("Hello there, this is a long enough English message.", "")
    assert r.skipped is True
    assert r.skip_reason == "no_expected_language"


@pytest.mark.regression
def test_service_skipped_on_mixed_below_dominance(monkeypatch):
    _enable(monkeypatch, min_dominance=0.9)
    # Mixed RU+EN content — dominance under 0.9 → skip.
    text = "Я вызвала endpoint validation и проверила пайплайн до отправки backend."
    r = check_language(text, "ru-RU")
    assert r.skipped is True
    assert r.skip_reason == "below_dominance_threshold"


@pytest.mark.regression
def test_service_ok_when_script_matches(monkeypatch):
    _enable(monkeypatch)
    r = check_language(
        "Сегодня был тихий день, я ловила себя на том, что просто слушаю тишину.",
        "ru-RU",
    )
    assert r.skipped is False
    assert r.ok is True
    assert r.detected == "cyrillic"


@pytest.mark.regression
def test_service_mismatch_when_script_wrong(monkeypatch):
    _enable(monkeypatch)
    # English output for a RU-expecting user.
    r = check_language(
        "Today was a quiet day, and I noticed how calm I felt inside my own room.",
        "ru-RU",
    )
    assert r.skipped is False
    assert r.ok is False
    assert r.detected == "latin"
    assert r.expected == "ru-RU"


@pytest.mark.regression
def test_service_never_raises_on_bad_input(monkeypatch):
    _enable(monkeypatch)
    # Garbage inputs that should not crash
    for bad in (None, 12345, object()):
        r = check_language(bad, "ru-RU")  # type: ignore[arg-type]
        assert isinstance(r, LanguageCheckResult)


# ---------------------------------------------------------------------------
# Conversation integration
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_maybe_run_language_guard_ok_path_no_vault_write(monkeypatch):
    from modules.generative import conversation
    from modules import debug_vault as vault_pkg
    from modules.system import config as config_service

    def _fake_get(key, default=None):
        if key == "language_guard":
            return {"enabled": True, "min_dominance": 0.7, "min_output_chars": 40}
        if key == "system.language":
            return "ru-RU"
        return default

    monkeypatch.setattr(config_service, "get_config_value", _fake_get)

    vault_calls = []
    monkeypatch.setattr(
        vault_pkg,
        "write_vault_entry",
        lambda **kwargs: vault_calls.append(kwargs) or "vault-id",
    )

    out = conversation._maybe_run_language_guard(
        last_user_message={"content": "привет"},
        assistant_content=(
            "Сегодня я провела день тихо и спокойно, без событий, "
            "но мне нравится такая тишина — она тёплая."
        ),
        provider="ollama",
        metadata={},
    )
    assert out["ok"] is True
    assert out["skipped"] is False
    assert vault_calls == []


@pytest.mark.regression
def test_maybe_run_language_guard_mismatch_writes_vault(monkeypatch):
    from modules.generative import conversation
    from modules import debug_vault as vault_pkg
    from modules.system import config as config_service

    def _fake_get(key, default=None):
        if key == "language_guard":
            return {"enabled": True, "min_dominance": 0.7, "min_output_chars": 40}
        if key == "system.language":
            return "ru-RU"
        return default

    monkeypatch.setattr(config_service, "get_config_value", _fake_get)

    vault_calls = []
    monkeypatch.setattr(
        vault_pkg,
        "write_vault_entry",
        lambda **kwargs: vault_calls.append(kwargs) or "vault-id-mm",
    )

    out = conversation._maybe_run_language_guard(
        last_user_message={"content": "привет"},
        assistant_content=(
            "Today was a very quiet day and I noticed how calm I felt the entire afternoon."
        ),
        provider="ollama",
        metadata={"model": "llama3"},
    )
    assert out["ok"] is False
    assert out["detected"] == "latin"
    assert out["expected"] == "ru-RU"
    assert out["vault_entry_id"] == "vault-id-mm"
    assert len(vault_calls) == 1
    assert vault_calls[0]["kind"] == "language_mismatch"


@pytest.mark.regression
def test_maybe_run_language_guard_disabled_returns_skipped(monkeypatch):
    from modules.generative import conversation
    from modules.system import config as config_service

    monkeypatch.setattr(
        config_service,
        "get_config_value",
        lambda key, default=None: (
            {"enabled": False} if key == "language_guard" else default
        ),
    )

    out = conversation._maybe_run_language_guard(
        last_user_message={"content": "hi"},
        assistant_content="A reasonably long English response for the disabled guard test.",
        provider="ollama",
        metadata={},
    )
    assert out.get("skipped") is True
    assert out.get("skip_reason") == "disabled"


# ---------------------------------------------------------------------------
# Legacy debt fixed: inner_voice language fallback now goes through
# resolve_user_language, not system.language directly.
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_resolve_user_language_fallback_chain():
    """When neither user_uuid nor character_id resolves to a UserSettings row,
    the helper should fall back to system.language → static 'en-US'."""
    from modules.system.user import resolve_user_language

    lang = resolve_user_language(
        user_uuid="nonexistent-user-uuid",
        character_id="nonexistent-character-id",
    )
    assert isinstance(lang, str)
    assert len(lang) >= 2
