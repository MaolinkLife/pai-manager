import pytest

from modules.generative import conversation


pytestmark = pytest.mark.regression


def test_stream_chunk_reasoning_parser_separates_think_block_from_visible_text():
    visible, reasoning, in_reasoning = conversation.strip_reasoning_from_chunk(
        "<think>думаю</think>\n\nОтвет",
        False,
    )

    assert visible == "\n\nОтвет"
    assert reasoning == "думаю"
    assert in_reasoning is False
    assert conversation._has_answer_signal(visible)


def test_stream_chunk_reasoning_parser_tracks_split_think_block():
    visible, reasoning, in_reasoning = conversation.strip_reasoning_from_chunk(
        "<think>первая часть",
        False,
    )
    assert visible == ""
    assert reasoning == "первая часть"
    assert in_reasoning is True
    assert not conversation._has_answer_signal(visible)

    visible, reasoning, in_reasoning = conversation.strip_reasoning_from_chunk(
        " и вторая</think> Финал",
        in_reasoning,
    )
    assert visible == " Финал"
    assert reasoning == " и вторая"
    assert in_reasoning is False
    assert conversation._has_answer_signal(visible)

