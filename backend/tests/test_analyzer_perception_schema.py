import pytest

from core.decision_layer import DecisionLayer
from modules.analyzer.service import AnalyzerModule


pytestmark = pytest.mark.regression


def _perception_payload(**routing_overrides):
    routing = {
        "need_memory": True,
        "memory_reason": "The request refers to previous context.",
        "memory_scope": "recent_context",
        "need_clarification": False,
        "clarification_reason": "Memory retrieval should be attempted first.",
        "need_vision": False,
        "vision_reason": "none",
        "need_file_inspection": False,
        "file_reason": "none",
        "need_image_gen": False,
        "need_image_edit": False,
        "need_video_gen": False,
        "need_audio_gen": False,
        "need_web_search": False,
        "web_search_reason": "none",
    }
    routing.update(routing_overrides)
    return {
        "input": {
            "inputText": "Сделай как в прошлый раз, только мрачнее",
            "hasMedia": False,
        },
        "understanding": {
            "summary": "User asks to modify a previous result with a darker tone.",
            "primary_intent": "command",
            "secondary_intents": ["memory_recall"],
            "topics": ["previous_result", "darker_tone"],
            "emotional_tone": {
                "primary": "neutral",
                "intensity": 0.2,
            },
            "context_completeness": {
                "score": 0.3,
                "label": "partial",
                "missing_context": ["previous result"],
            },
        },
        "module_routing": routing,
        "safety": {
            "content_category": "sfw",
            "risk_level": 0.0,
            "flags": [],
        },
        "decision_hints": {
            "recommended_next_step": "retrieve_memory",
            "response_style": {
                "temperature": 0.7,
                "sarcasm_level": 0.1,
                "warmth_level": 0.5,
                "brevity": "medium",
            },
            "notes_for_generator": ["Retrieve the previous result first."],
        },
        "confidence": {
            "intent_confidence": 0.85,
            "routing_confidence": 0.95,
            "overall_confidence": 0.82,
        },
    }


def test_analyzer_normalizes_perception_schema_to_legacy_metadata():
    metadata = AnalyzerModule._normalize_metadata(
        _perception_payload(),
        "Сделай как в прошлый раз, только мрачнее",
        {"media_count": 0},
    )

    assert metadata["perception"]["module_routing"]["need_memory"] is True
    assert metadata["orchestration"]["need_memory"] is True
    assert metadata["orchestration"]["memory_scope"] == "recent_context"
    assert metadata["orchestration"]["recommended_next_step"] == "retrieve_memory"
    assert metadata["input_analysis"]["intent_analysis"]["primary_intent"] == "command"
    assert metadata["input_analysis"]["dominant_themes"] == [
        "previous_result",
        "darker_tone",
    ]
    assert metadata["response_guidance"]["generation_parameters"]["warmth_level"] == 0.5


def test_media_presence_does_not_force_vision_without_routing_request(monkeypatch):
    monkeypatch.setattr(
        "core.decision_layer.config_service.get_config_value",
        lambda key, default=None: True if key == "moral.enabled" else default,
    )
    layer = DecisionLayer.__new__(DecisionLayer)
    metadata = AnalyzerModule._normalize_metadata(
        _perception_payload(need_memory=False, need_vision=False),
        "Привет",
        {"media_count": 1},
    )

    plan = layer._build_task_plan(
        analysis=metadata,
        decisions={"needs_deep_memory": False, "needs_vision": False},
        image_generation_decision={"enabled": False},
        media_payload=[{"category": "image", "data": "base64"}],
    )

    assert "vision" not in [item["module"] for item in plan.to_list()]
