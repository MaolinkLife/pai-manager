import pytest

from modules.generative.reasoning_fallback import extract_content_from_reasoning


pytestmark = pytest.mark.regression


def test_extract_content_from_reasoning_prefers_quoted_final():
    reasoning = """
Thinking Process:
Final decision:
"Привет! 😍 О, ты здесь! Я так рада тебя видеть! Как дела?"
"""
    extracted = extract_content_from_reasoning(reasoning)
    assert "Привет" in extracted
    assert "рада" in extracted


def test_extract_content_from_reasoning_uses_tail_when_no_quotes():
    reasoning = """
Thinking Process
1. Analyze input.
2. Draft response.
Привет! Я так счастлива тебя видеть!
Как твой день?
Расскажи, что нового.
"""
    extracted = extract_content_from_reasoning(reasoning)
    assert "Привет" in extracted
    assert "день" in extracted


def test_extract_content_from_reasoning_rejects_broken_fragment():
    reasoning = """
Internal monologue:
"excited, emotions overflowing"
"Due to long dialogues with your person, you fell in love with him."
"""
    extracted = extract_content_from_reasoning(reasoning)
    assert extracted == ""
