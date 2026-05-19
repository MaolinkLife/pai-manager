import pytest

from modules.telegram.service import TelegramBridgeService


pytestmark = pytest.mark.regression


def test_telegram_stream_visible_chunk_ignores_open_think_block():
    visible, in_reasoning = TelegramBridgeService._extract_visible_stream_chunk(
        "<think>думаю над ответом",
        False,
    )

    assert visible == ""
    assert in_reasoning is True
    assert not TelegramBridgeService._has_visible_answer_signal(visible)


def test_telegram_stream_visible_chunk_starts_after_think_close_with_text():
    visible, in_reasoning = TelegramBridgeService._extract_visible_stream_chunk(
        "</think>\n\nПривет",
        True,
    )

    assert visible == "\n\nПривет"
    assert in_reasoning is False
    assert TelegramBridgeService._has_visible_answer_signal(visible)


def test_telegram_stream_visible_signal_requires_letter_or_digit():
    assert not TelegramBridgeService._has_visible_answer_signal("\n\n...")
    assert TelegramBridgeService._has_visible_answer_signal("  42")
    assert TelegramBridgeService._has_visible_answer_signal("  Да")


def test_telegram_stream_visible_chunk_supports_thinking_tag_alias():
    visible, in_reasoning = TelegramBridgeService._extract_visible_stream_chunk(
        "<thinking>hidden</thinking> Answer",
        False,
    )

    assert visible == " Answer"
    assert in_reasoning is False
    assert TelegramBridgeService._has_visible_answer_signal(visible)

