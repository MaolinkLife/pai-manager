import pytest

from core.decision_layer import DecisionLayer
from core.task_layer import TASK_COMPLETE, TASK_SKIPPED, TaskPlan


pytestmark = pytest.mark.regression


def test_task_plan_marks_terminal_result():
    plan = TaskPlan()
    plan.add("memory", "memory", "collect_context", "needed")

    plan.mark("memory", TASK_COMPLETE, details={"matches": 2})

    payload = plan.to_list()
    assert payload[0]["status"] == TASK_COMPLETE
    assert payload[0]["result"]["status"] == TASK_COMPLETE
    assert payload[0]["result"]["details"]["matches"] == 2


def test_decision_layer_task_plan_keeps_memory_visible_when_skipped(monkeypatch):
    monkeypatch.setattr(
        "core.decision_layer.config_service.get_config_value",
        lambda key, default=None: True if key == "moral.enabled" else default,
    )
    layer = DecisionLayer.__new__(DecisionLayer)

    plan = layer._build_task_plan(
        analysis={},
        decisions={"needs_deep_memory": False, "needs_vision": False},
        image_generation_decision={"enabled": False},
        media_payload=[],
    )
    plan.mark("memory", TASK_SKIPPED, reason="disabled_by_config")

    tasks = plan.to_list()
    modules = [item["module"] for item in tasks]
    memory_task = next(item for item in tasks if item["module"] == "memory")

    assert modules[:2] == ["analysis", "decision"]
    assert "instructor" in modules
    assert "llm" in modules
    assert memory_task["status"] == TASK_SKIPPED
    assert memory_task["result"]["reason"] == "disabled_by_config"


def test_decision_layer_visual_hard_signal_detects_image_attachment():
    signal = DecisionLayer._detect_visual_hard_signal(
        {"media": []},
        [{"category": "image", "mimeType": "image/png"}],
    )

    assert signal["needs_vision"] is True
    assert signal["sources"] == ["image_attachment"]


def test_decision_layer_visual_hard_signal_ignores_non_visual_media():
    signal = DecisionLayer._detect_visual_hard_signal(
        {"feature_flags": {"image_generation": True}},
        [{"category": "audio", "mimeType": "audio/wav"}],
    )

    assert signal["needs_vision"] is False
    assert signal["sources"] == []


def test_decision_layer_visual_hard_signal_detects_screen_share_flag():
    signal = DecisionLayer._detect_visual_hard_signal(
        {"runtime_meta": {"screen_sharing": True}},
        [],
    )

    assert signal["needs_vision"] is True
    assert signal["sources"] == ["runtime_meta"]
