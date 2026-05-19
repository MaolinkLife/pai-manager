import pytest

from modules.generative.sanitizer import (
    sanitize_generation_messages,
    sanitize_generation_text,
)


pytestmark = pytest.mark.regression


def test_sanitize_generation_text_removes_closed_think_block():
    raw = "Before\n<think>\ninternal reasoning\n</think>\n\nAfter"

    assert sanitize_generation_text(raw) == "Before\n\nAfter"


def test_sanitize_generation_text_removes_dangling_think_block():
    raw = "Observed material:\n- visible\n- <think>\nThinking Process:\n1. internal"

    assert sanitize_generation_text(raw) == "Observed material:\n- visible\n-"


def test_sanitize_generation_messages_preserves_metadata_and_nested_content():
    messages = [
        {
            "role": "tool",
            "name": "memory.lookup",
            "content": "[OK]\n- <think>secret</think>\n\nVisible",
            "reasoning": "top-level secret",
            "tool_call_id": "tc1",
        },
        {
            "role": "user",
            "content": [{"type": "text", "text": "Hi <think>hidden</think>there"}],
        },
    ]

    sanitized = sanitize_generation_messages(messages)

    assert sanitized[0]["role"] == "tool"
    assert sanitized[0]["name"] == "memory.lookup"
    assert sanitized[0]["tool_call_id"] == "tc1"
    assert "reasoning" not in sanitized[0]
    assert "secret" not in sanitized[0]["content"]
    assert "Visible" in sanitized[0]["content"]
    assert sanitized[1]["content"][0]["text"] == "Hi there"
