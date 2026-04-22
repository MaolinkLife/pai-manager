from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
import importlib.util
from pathlib import Path
import sys


def _load_diary_module():
    backend_root = Path(__file__).resolve().parents[1]
    module_path = backend_root / "modules" / "memory" / "diary.py"
    spec = importlib.util.spec_from_file_location("memory_diary_module", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load diary module for tests.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_diary = _load_diary_module()
_build_activity_transcript = _diary._build_activity_transcript
_build_day_activity_stats = _diary._build_day_activity_stats
_signature_text = _diary._signature_text
_estimate_diary_confidence = _diary._estimate_diary_confidence
_fallback_summary = _diary._fallback_summary
_build_structured_payload = _diary._build_structured_payload
DiaryEntry = _diary.DiaryEntry


def _row(
    *,
    role: str,
    content: str,
    transport_name: str,
    chat_id: int | None,
    event: str,
    media_count: int = 0,
):
    runtime_meta = {
        "transport": {
            "name": transport_name,
            "chat_id": chat_id,
        },
        "event": event,
    }
    media = [object() for _ in range(media_count)]
    return SimpleNamespace(
        role=role,
        content=content,
        runtime_meta=json.dumps(runtime_meta, ensure_ascii=False),
        media=media,
        timestamp=datetime(2026, 4, 18, 10, 0, tzinfo=timezone.utc),
    )


def test_build_day_activity_stats_aggregates_across_all_chats_and_channels():
    rows = [
        _row(
            role="user",
            content="tg private message",
            transport_name="telegram",
            chat_id=101,
            event="incoming_message",
        ),
        _row(
            role="assistant",
            content="tg private reply",
            transport_name="telegram",
            chat_id=101,
            event="outgoing_message",
            media_count=1,
        ),
        _row(
            role="user",
            content="tg group message",
            transport_name="telegram",
            chat_id=202,
            event="incoming_message",
        ),
        _row(
            role="tool",
            content="[OK] image generated",
            transport_name="main_chat",
            chat_id=None,
            event="tool_event",
        ),
    ]

    stats = _build_day_activity_stats(rows)

    assert stats["total_messages"] == 4
    assert stats["by_transport"]["telegram"] == 3
    assert stats["by_transport"]["main_chat"] == 1
    assert stats["telegram_chats_touched"] == 2
    assert stats["by_event"]["incoming_message"] == 2
    assert stats["by_event"]["outgoing_message"] == 1
    assert stats["by_event"]["tool_event"] == 1
    assert stats["media_items"] == 1


def test_build_activity_transcript_contains_transport_and_event_context():
    rows = [
        _row(
            role="tool",
            content="[ERROR] fallback used",
            transport_name="telegram",
            chat_id=303,
            event="tool_event",
        ),
    ]
    transcript = _build_activity_transcript(rows)
    lowered = transcript.lower()

    assert "telegram" in lowered
    assert "chat=303" in lowered
    assert "tool_event" in lowered
    assert "fallback used" in lowered


def test_diary_signature_and_confidence_helpers_are_stable():
    signature = _signature_text("Hello!!!   Hello\nworld, world? 123")
    assert "hello" in signature
    assert "world" in signature

    entry = DiaryEntry(
        id="x",
        character_id="char",
        day="2026-04-18",
        mood="focused",
        summary="A compact but meaningful daily recap with enough detail.",
        tags=["daily", "telegram", "reflection"],
        stats={
            "total_messages": 12,
            "by_transport": {"telegram": 10},
            "media_items": 1,
        },
        payload={},
        created_at="2026-04-18T00:00:00+00:00",
        updated_at="2026-04-18T00:00:00+00:00",
    )
    confidence = _estimate_diary_confidence(entry)
    assert 0.05 <= confidence <= 0.99


def test_fallback_summary_contains_structured_sections():
    payload = _fallback_summary(
        day=datetime(2026, 4, 18, tzinfo=timezone.utc).date(),
        stats={
            "total_messages": 12,
            "by_transport": {"telegram": 10},
            "by_role": {"assistant": 8, "user": 4},
            "telegram_chats_touched": 2,
            "media_items": 1,
        },
    )

    assert payload["title"]
    assert isinstance(payload["outcomes"], list)
    assert isinstance(payload["entities"], list)
    assert payload["importance_score"] is not None


def test_build_structured_payload_maps_sections_from_summary_payload():
    structured = _build_structured_payload(
        day=datetime(2026, 4, 18, tzinfo=timezone.utc).date(),
        stats={"total_messages": 5, "media_items": 0, "telegram_chats_touched": 1},
        summary_payload={
            "title": "Test Diary",
            "source_event": "Read several posts.",
            "outcomes": ["Outcome A"],
            "entities": ["Entity A"],
            "key_messages": ["Message A"],
            "importance_score": 0.81,
            "importance_notes": "Important due to repetition.",
            "emotion_valence": "negative",
            "emotion_arousal": "high",
            "emotion_notes": "Overstimulated.",
            "relationships": "PAI as observer.",
            "retrieval_cues": ["cue-a"],
            "similarities": ["similar-a"],
            "photo_descriptions": ["photo-a"],
            "contradictions": ["contradiction-a"],
        },
    )

    assert structured["title"] == "Test Diary"
    assert structured["source_event"] == "Read several posts."
    assert structured["emotion"]["valence"] == "negative"
    assert structured["retrieval_cues"] == ["cue-a"]
