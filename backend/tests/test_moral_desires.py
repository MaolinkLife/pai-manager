"""What the matrix wants: the desire vector of its answer is kept, not thrown away.

The matrix prompt asks for a desire vector next to the wanted response. It is
kept in the transition and so reaches the saved snapshot; nothing hands it to
the model yet.
"""

from __future__ import annotations

import asyncio

from modules.moral_matrix.service import MoralMatrixModule, ProviderRunResult


def _answer(desires=None) -> dict:
    behavior = {"desired_behavior": "answer_warmly"}
    if desires is not None:
        behavior["desire_vector"] = desires
    return {
        "emotional_reaction": {
            "dominant_shift": "tenderness",
            "shift_strength": 0.8,
            "shift_reason": "kind words",
        },
        "state_update": {"recommended_new_state": {"tenderness": 0.8, "joy": 0.5}},
        "behavior_formation": behavior,
    }


def test_the_matrix_desires_are_kept():
    transition = MoralMatrixModule()._normalize_structured_answer(
        _answer({"seek_closeness": 0.8, "express_playfulness": 0.4})
    )

    assert transition["desire_vector"] == {"seek_closeness": 0.8, "express_playfulness": 0.4}


def test_desire_values_are_clamped_and_junk_is_dropped():
    transition = MoralMatrixModule()._normalize_structured_answer(
        _answer(
            {
                "seek_closeness": 1.7,
                "protect_self": -0.2,
                "express_hurt": "a lot",
                "avoid_conflict": None,
                "refuse_access": True,
                "": 0.5,
            }
        )
    )

    assert transition["desire_vector"] == {"seek_closeness": 1.0, "protect_self": 0.0}


def test_an_answer_without_desires_gives_none():
    assert MoralMatrixModule()._normalize_structured_answer(_answer())["desire_vector"] == {}
    assert MoralMatrixModule()._normalize_structured_answer(_answer(["seek_closeness"]))["desire_vector"] == {}


class _Repository:
    def __init__(self):
        self.snapshots = []

    def fetch_recent_traces(self, _character_id, limit=10):
        return []

    def fetch_traces_for_messages(self, _character_id, _message_ids):
        return []

    def fetch_similar_traces(self, _character_id, query_text, *, limit=5, scan_limit=160):
        return []

    def fetch_latest_snapshot(self, _character_id):
        return {}

    def fetch_daily_summary(self, _character_id, _date):
        return {}

    def store_snapshot(self, character_id, message_id, payload):
        self.snapshots.append(payload)
        return "stored-snapshot"

    def store_emotional_trace(self, character_id, *, message_id, payload):
        return "stored-trace"

    def annotate_previous_trace_outcome(self, character_id, *, current_message_id, payload):
        return None


class _Provider:
    async def run(self, payload):
        return ProviderRunResult(
            provider="test",
            payload=_answer({"seek_closeness": 0.8, "protect_self": 0.1}),
        )


def test_the_desires_reach_the_saved_snapshot(monkeypatch):
    module = MoralMatrixModule()
    repository = _Repository()
    module._repository = repository
    module._provider_manager = _Provider()
    monkeypatch.setattr(module, "_resolve_character_id", lambda: "char-1")
    settings = {"moral.enabled": True, "moral.inner_voice.enabled": False, "moral.scars.enabled": False}
    monkeypatch.setattr(
        "modules.moral_matrix.service.config_service.get_config_value",
        lambda path, default=None: settings.get(path, default),
    )
    monkeypatch.setattr(
        "modules.moral_matrix.service.config_service.set_config_value", lambda path, value: True
    )

    payload = asyncio.run(
        module.evaluate(
            analysis_result={"input_analysis": {"emotional_tone": {"primary": "warmth", "intensity": 0.6}}},
            memory_context={"matches": [], "conversation_state": {}},
            memory_meta={"matches_found": 0},
            message_meta={"message_id": "u1"},
            user_message={"id": "u1", "role": "user", "content": "ты очень красивая"},
            persist_state=True,
        )
    )

    wanted = {"seek_closeness": 0.8, "protect_self": 0.1}
    assert payload["meta"]["transition"]["desire_vector"] == wanted
    assert repository.snapshots[0]["meta"]["transition"]["desire_vector"] == wanted
