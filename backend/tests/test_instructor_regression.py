import asyncio

import pytest

from core.instructor import Instructor


pytestmark = pytest.mark.regression


def test_format_for_api_injects_dynamic_tool_context_and_keeps_tool_history(monkeypatch):
    instructor = Instructor()

    monkeypatch.setattr(
        instructor,
        "_build_environment_tool_content",
        lambda: "Date: 01 January 2026\nTime: 12:00:00",
    )

    user_message = {
        "id": "u1",
        "content": "hello",
        "history": [
            {"role": "system", "content": "legacy system note"},
            {"role": "assistant", "content": "previous reply", "id": "a1"},
            {
                "role": "tool",
                "name": "image.generate",
                "tool_call_id": "tc1",
                "content": "[OK]: image generated",
                "id": "t1",
            },
        ],
        "runtime_meta": {
            "transport": {"name": "telegram", "chat_id": 123, "chat_kind": "private"},
            "time_awareness": {
                "local_time": "2026-01-01T12:00:00+03:00",
                "day_phase": "day",
                "is_quiet_hours": False,
            },
            "open_loop_context": {
                "unanswered_initiatives_in_row": 1,
                "hours_since_last_user_message": 2.0,
                "hours_since_last_outbound": 0.4,
                "has_open_conversational_loop": True,
                "last_user_message_excerpt": "hello",
                "last_unanswered_outbound_excerpt": "follow up",
            },
            "repeat_feedback": {
                "enabled": True,
                "reason": "semantic",
                "instruction": "Generate a materially different message.",
                "blocked_text": "old draft",
            },
            "memory_hint": "[OK]: memory lookup completed.",
        },
    }
    memory_context = {
        "memory_status": "ready",
        "key_facts": ["User asked about testing strategy."],
        "lore_matches": ["Character likes concise answers."],
        "stage_trace": [
            {
                "stage": "session_recent_32",
                "status": "ok",
                "candidates": 32,
                "matches": 1,
            },
            {
                "stage": "session_window",
                "status": "miss",
                "candidates": 64,
                "matches": 0,
                "chunk_size": 32,
                "chunks_checked": 2,
            },
        ],
        "conversation_state": {
            "last_message_at": "2026-01-01T10:00:00Z",
            "hours_since_last_message": 2,
            "inactivity_bucket": "short",
            "last_topic": "testing",
            "recent_tone_summary": "neutral",
        }
    }
    analysis = {
        "input_analysis": {
            "dominant_themes": ["testing"],
            "intent_analysis": {"primary_intent": "request_information"},
            "emotional_tone": {"primary": "neutral"},
        }
    }
    moral_state = {"current_emotion": "excited", "intensity": 0.7}
    tool_hints = {"instructions": "[TOOLS]\nUse tools carefully."}

    messages = asyncio.run(
        instructor.format_for_api(
            system_prompt="[CORE]\nbase",
            user_message=user_message,
            analysis=analysis,
            moral_state=moral_state,
            memory_context=memory_context,
            tool_hints=tool_hints,
        )
    )

    assert messages[0]["role"] == "system"
    names = [m.get("name") for m in messages if m.get("role") == "tool"]
    assert "context.analysis" in names
    assert "memory.lookup" in names
    assert "knowledge.lorebook" in names
    assert "state.emotion" in names
    assert "system.clock" in names
    assert "context.relationship" in names
    assert "orchestration.hints" in names
    assert "telegram.runtime" in names
    assert "repeat.guard" in names
    assert "memory.hint" in names
    assert "image.generate" in names
    memory_messages = [
        m for m in messages if m.get("role") == "tool" and m.get("name") == "memory.lookup"
    ]
    assert memory_messages
    assert "[STAGES]" in str(memory_messages[0].get("content") or "")

    # Ensure system entries from history are stripped.
    assert all(
        not (m.get("role") == "system" and m.get("content") == "legacy system note")
        for m in messages[1:]
    )

    # User message remains the final message.
    assert messages[-1]["role"] == "user"
    assert messages[-1]["id"] == "u1"
