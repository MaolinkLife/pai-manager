import pytest

from modules.telegram.service import TelegramBridgeService


pytestmark = pytest.mark.regression


def test_invalid_visible_reply_rejects_reasoning_fragments():
    assert TelegramBridgeService._is_invalid_visible_reply("excited, emotions overflowing")
    assert TelegramBridgeService._is_invalid_visible_reply(
        "Due to long dialogues with your person, you fell in love with him."
    )

