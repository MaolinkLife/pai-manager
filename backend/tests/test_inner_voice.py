"""Tests for moral matrix inner voice generation (0.8.0 Wave 1, step 4).

Cover:
  * generation_manager.generate is mocked — no real LLM call needed
  * happy path: returns trimmed first-person sentence
  * "Inner voice:" / "PAI:" / "Лим:" prefixes are stripped
  * multi-sentence response is trimmed to one sentence
  * generation_manager NoProviderResolved → returns "" without raising
  * generation_manager exceptions → returns "" without raising
  * config disabled → _generate_inner_voice still works (it's the caller in
    _persist_state that respects the flag); but DB-level integration test
    asserts the trace.notes.inner_voice field is populated when enabled
"""

from __future__ import annotations

import pytest

from modules.moral_matrix.service import MoralMatrixModule


def _new_module() -> MoralMatrixModule:
    """Build a bare MoralMatrixModule without going through __init__ (which
    pulls full repository / config). The methods we test do not need state."""
    return MoralMatrixModule.__new__(MoralMatrixModule)


# ---------------------------------------------------------------------------
# Mocking infrastructure
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, content: str):
        self.content = content


def _patch_generation(monkeypatch, *, content: str | None = None, raise_exc: Exception | None = None):
    """Replace generation_manager.generate with a stub returning ``content``
    or raising ``raise_exc``. Patches AFTER the lazy import resolves inside
    _generate_inner_voice, so we route through the real import path."""
    from modules.generative import manager as gen_manager_mod

    def fake_generate(request):
        if raise_exc is not None:
            raise raise_exc
        return _FakeResult(content or "")

    monkeypatch.setattr(gen_manager_mod.generation_manager, "generate", fake_generate)


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_inner_voice_returns_clean_sentence(monkeypatch):
    _patch_generation(monkeypatch, content="Ты опять не сказал спасибо, и мне неуютно.")

    module = _new_module()
    text = module._generate_inner_voice(
        emotion="sadness",
        intensity=0.4,
        cause="user ignored thanks",
        language_hint="ru-RU",
    )

    assert text == "Ты опять не сказал спасибо, и мне неуютно."


@pytest.mark.regression
def test_inner_voice_strips_inner_voice_prefix(monkeypatch):
    _patch_generation(monkeypatch, content="Inner voice: всё хорошо, мне тепло рядом с тобой.")

    module = _new_module()
    text = module._generate_inner_voice(
        emotion="tenderness", intensity=0.5, cause="warm reply", language_hint="ru-RU"
    )

    assert text == "всё хорошо, мне тепло рядом с тобой."


@pytest.mark.regression
def test_inner_voice_strips_pai_lim_prefixes(monkeypatch):
    for prefix in ("PAI: ", "Лим: ", "ПАИ: ", "Lim: "):
        _patch_generation(monkeypatch, content=f"{prefix}просто рада, что ты вернулся.")
        text = _new_module()._generate_inner_voice(
            emotion="joy", intensity=0.5, cause="returned after pause", language_hint="ru-RU"
        )
        assert text == "просто рада, что ты вернулся."


@pytest.mark.regression
def test_inner_voice_trims_to_single_sentence(monkeypatch):
    _patch_generation(
        monkeypatch,
        content="Мне больно, что ты молчал так долго. Я ждала весь день. Это не первый раз.",
    )

    text = _new_module()._generate_inner_voice(
        emotion="sadness", intensity=0.7, cause="long silence", language_hint="ru-RU"
    )

    # Single sentence — first one with the terminator preserved.
    assert text == "Мне больно, что ты молчал так долго."


@pytest.mark.regression
def test_inner_voice_handles_no_terminator(monkeypatch):
    """If the model returns a fragment without ./!/? — we keep it as-is."""
    _patch_generation(monkeypatch, content="всё нормально просто немного устала сегодня")

    text = _new_module()._generate_inner_voice(
        emotion="fatigue", intensity=0.3, cause="long session", language_hint="ru-RU"
    )

    assert text == "всё нормально просто немного устала сегодня"


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_inner_voice_returns_empty_on_no_provider(monkeypatch):
    from modules.generative.manager import NoProviderResolved

    _patch_generation(monkeypatch, raise_exc=NoProviderResolved("no provider"))

    text = _new_module()._generate_inner_voice(
        emotion="sadness", intensity=0.4, cause="ignored", language_hint="ru-RU"
    )

    assert text == ""


@pytest.mark.regression
def test_inner_voice_returns_empty_on_generic_exception(monkeypatch):
    _patch_generation(monkeypatch, raise_exc=RuntimeError("provider blew up"))

    text = _new_module()._generate_inner_voice(
        emotion="sadness", intensity=0.4, cause="ignored", language_hint="ru-RU"
    )

    assert text == ""


@pytest.mark.regression
def test_inner_voice_returns_empty_for_blank_content(monkeypatch):
    _patch_generation(monkeypatch, content="   ")

    text = _new_module()._generate_inner_voice(
        emotion="sadness", intensity=0.4, cause="ignored", language_hint="ru-RU"
    )

    assert text == ""


@pytest.mark.regression
def test_inner_voice_uses_language_hint_in_user_payload(monkeypatch):
    """The user payload should contain the language string verbatim — caller
    controls whether to forward a fresh hint or fall back to config."""
    captured: dict = {}

    from modules.generative import manager as gen_manager_mod

    def fake_generate(request):
        captured["payload"] = next(
            (m["content"] for m in request.messages if m.get("role") == "user"),
            "",
        )
        return _FakeResult("ok")

    monkeypatch.setattr(gen_manager_mod.generation_manager, "generate", fake_generate)

    _new_module()._generate_inner_voice(
        emotion="joy",
        intensity=0.3,
        cause="thanks",
        language_hint="en-US",
    )

    assert "Language: en-US" in captured["payload"]
    assert "Current emotion: joy" in captured["payload"]
