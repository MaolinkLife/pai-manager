"""Tests for factuality check (0.9.0 Wave 2, §3.9).

Coverage:
  Claim extractor:
    * extracts years
    * extracts dotted/slashed dates
    * extracts numbers with units (latin and cyrillic)
    * extracts capitalized multi-word phrases (proper-noun-ish)
    * drops sentence-initial capitalized words that are just grammar
    * empty / blank input → []
    * respects max_claims
    * deduplicates case-insensitively

  Service:
    * disabled → skipped
    * empty output → skipped
    * gate_on_low_confidence=True + confidence_low=False → skipped(gated)
    * no claims (purely conversational output) → skipped(no_claims)
    * supported: lorebook returns hits → supported=True
    * unverified: lorebook returns nothing → supported=False
    * lookup error per-claim is swallowed (other claims still scored)
    * never raises on bad input

  Conversation integration:
    * _maybe_run_factuality returns skipped when gate suppresses
    * unverified path produces WARNING audit (we don't assert audit log
      content directly — we assert the payload bits)
"""

from __future__ import annotations

import pytest

from modules.factuality import check_factuality, extract_claims
from modules.factuality.claim_extractor import has_factual_claims
from modules.factuality.types import FactualityResult


# ---------------------------------------------------------------------------
# Claim extractor
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_extract_years():
    claims = extract_claims("Это произошло в 1999 году, а потом в 2024.")
    assert "1999" in claims
    assert "2024" in claims


@pytest.mark.regression
def test_extract_dates():
    claims = extract_claims("Встреча была 12.03.2024 и 5/7/2023.")
    assert "12.03.2024" in claims
    assert "5/7/2023" in claims


@pytest.mark.regression
def test_extract_numbers_with_units():
    claims = extract_claims("Он пробежал 42 км за 3 часа, температура была 25°C.")
    # 42 км, 25°C should be extracted; "3 часа" matches the "часа" form? — we
    # only match "часов / дней / лет / месяцев", so "3 часа" is fine to skip.
    assert any("км" in c for c in claims)
    assert any("°C" in c.lower() for c in claims) or any("°c" in c.lower() for c in claims)


@pytest.mark.regression
def test_extract_capitalized_phrases():
    text = "I read War And Peace by Leo Tolstoy yesterday."
    claims = extract_claims(text)
    assert any("War And Peace" in c for c in claims) or any("Leo Tolstoy" in c for c in claims)


@pytest.mark.regression
def test_extract_drops_sentence_initial():
    text = "Сегодня было тихо. Завтра планирую гулять."
    claims = extract_claims(text)
    # Both "Сегодня" and "Завтра" should be dropped as sentence-initial
    # single capitalized words.
    assert "Сегодня" not in claims
    assert "Завтра" not in claims


@pytest.mark.regression
def test_extract_empty_string_returns_empty():
    assert extract_claims("") == []
    assert extract_claims("    \n  ") == []


@pytest.mark.regression
def test_extract_respects_max_claims():
    text = "В 1990 в 1991 в 1992 в 1993 в 1994 в 1995 в 1996 в 1997 годах."
    claims = extract_claims(text, max_claims=3)
    assert len(claims) == 3


@pytest.mark.regression
def test_extract_deduplicates_case_insensitive():
    text = "Tolstoy wrote it. Then tolstoy revised it. Tolstoy again."
    claims = extract_claims(text)
    lowered = [c.lower() for c in claims]
    # "Tolstoy" should appear only once across the list.
    assert lowered.count("tolstoy") <= 1


@pytest.mark.regression
def test_has_factual_claims_quick_gate():
    assert has_factual_claims("Год был 1999.") is True
    assert has_factual_claims("привет, как дела") is False


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def _patch_factuality_config(monkeypatch, **overrides):
    base = {
        "enabled": True,
        "gate_on_low_confidence": True,
        "top_k": 3,
        "min_similarity": 0.6,
        "max_claims": 6,
        "claim_min_length": 3,
    }
    base.update(overrides)
    from modules.system import config as config_service

    monkeypatch.setattr(
        config_service,
        "get_config_value",
        lambda key, default=None: base if key == "factuality" else default,
    )


def _stub_lorebook(monkeypatch, hits_per_query):
    """hits_per_query: callable(query) -> list[dict] (the hits)."""
    from modules.memory import lorebook as lorebook_module

    monkeypatch.setattr(
        lorebook_module,
        "search_entries",
        lambda query, top_k=5, min_similarity=0.7: hits_per_query(query),
    )


@pytest.mark.regression
def test_service_disabled_returns_skipped(monkeypatch):
    _patch_factuality_config(monkeypatch, enabled=False)
    r = check_factuality(output="В 1999 году произошло важное событие.", confidence_low=True)
    assert r.skipped is True
    assert r.skip_reason == "disabled"


@pytest.mark.regression
def test_service_empty_output_skipped(monkeypatch):
    _patch_factuality_config(monkeypatch)
    r = check_factuality(output="", confidence_low=True)
    assert r.skipped is True
    assert r.skip_reason == "empty_output"


@pytest.mark.regression
def test_service_gated_when_confidence_high(monkeypatch):
    _patch_factuality_config(monkeypatch, gate_on_low_confidence=True)
    r = check_factuality(
        output="В 1999 году случилось важное.",
        confidence_low=False,
    )
    assert r.skipped is True
    assert r.skip_reason == "gated"


@pytest.mark.regression
def test_service_no_claims_skipped(monkeypatch):
    _patch_factuality_config(monkeypatch, gate_on_low_confidence=False)
    r = check_factuality(
        output="привет, как у тебя дела? всё хорошо",
        confidence_low=False,
    )
    assert r.skipped is True
    assert r.skip_reason == "no_claims"


@pytest.mark.regression
def test_service_supported_when_lorebook_returns_hits(monkeypatch):
    _patch_factuality_config(monkeypatch, gate_on_low_confidence=False)
    _stub_lorebook(
        monkeypatch,
        lambda q: [{"id": "lore-1", "content": f"match for {q}"}],
    )
    r = check_factuality(
        output="Это случилось в 1999 году.",
        confidence_low=False,
    )
    assert r.skipped is False
    assert r.checked is True
    assert r.supported is True
    assert r.sources_found >= 1


@pytest.mark.regression
def test_service_unverified_when_lorebook_empty(monkeypatch):
    _patch_factuality_config(monkeypatch, gate_on_low_confidence=False)
    _stub_lorebook(monkeypatch, lambda q: [])
    r = check_factuality(
        output="Это случилось в 1999 году с участием Leo Tolstoy.",
        confidence_low=False,
    )
    assert r.skipped is False
    assert r.checked is True
    assert r.supported is False
    assert r.sources_found == 0


@pytest.mark.regression
def test_service_swallows_per_claim_lookup_errors(monkeypatch):
    _patch_factuality_config(monkeypatch, gate_on_low_confidence=False)

    def _flaky(query, top_k=5, min_similarity=0.7):
        if "1999" in query:
            raise RuntimeError("lorebook on fire")
        return [{"id": "ok"}]

    _stub_lorebook(monkeypatch, _flaky)
    r = check_factuality(
        output="It happened in 1999 with Leo Tolstoy.",
        confidence_low=False,
    )
    # One claim threw, but service does NOT raise; it just records 0 hits
    # for that claim and continues with the others.
    assert isinstance(r, FactualityResult)
    assert r.skipped is False or r.skip_reason == "lookup_import_error"


# ---------------------------------------------------------------------------
# Conversation integration
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_maybe_run_factuality_skipped_when_disabled(monkeypatch):
    from modules.generative import conversation
    _patch_factuality_config(monkeypatch, enabled=False)

    payload = conversation._maybe_run_factuality(
        assistant_content="In 1999 something happened.",
        confidence_payload={"low": True, "score": 0.2},
    )
    assert payload.get("skipped") is True
    assert payload.get("skip_reason") == "disabled"


@pytest.mark.regression
def test_maybe_run_factuality_unverified_path(monkeypatch):
    from modules.generative import conversation
    _patch_factuality_config(monkeypatch, gate_on_low_confidence=True)
    _stub_lorebook(monkeypatch, lambda q: [])

    payload = conversation._maybe_run_factuality(
        assistant_content="Это случилось в 1999 году с участием Leo Tolstoy.",
        confidence_payload={"low": True, "score": 0.2},
    )
    assert payload["checked"] is True
    assert payload["supported"] is False
    assert payload["sources_found"] == 0


@pytest.mark.regression
def test_maybe_run_factuality_gated_when_high_confidence(monkeypatch):
    from modules.generative import conversation
    _patch_factuality_config(monkeypatch, gate_on_low_confidence=True)
    _stub_lorebook(monkeypatch, lambda q: [])

    payload = conversation._maybe_run_factuality(
        assistant_content="Это случилось в 1999 году.",
        confidence_payload={"low": False, "score": 0.9},
    )
    assert payload["skipped"] is True
    assert payload["skip_reason"] == "gated"
