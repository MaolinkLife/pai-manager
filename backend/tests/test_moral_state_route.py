"""The matrix page reads her inner voice from the latest trace, so it survives a page reload."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from routes import moral_routes


class _Repository:
    def __init__(self, traces):
        self._traces = traces

    def fetch_latest_snapshot(self, character_id):
        return {}

    def fetch_daily_summary(self, character_id, day):
        return {}

    def fetch_recent_traces(self, character_id, limit=10):
        return self._traces[:limit]


def _state(monkeypatch, traces) -> dict:
    monkeypatch.setattr(moral_routes, "get_active_character_name", lambda **kwargs: "Test")
    monkeypatch.setattr(
        moral_routes, "get_or_create_character", lambda name: SimpleNamespace(id="c1", name=name)
    )
    monkeypatch.setattr(moral_routes, "_repository", _Repository(traces))
    request = SimpleNamespace(headers={})
    return asyncio.run(moral_routes.get_moral_state(request, limit=12))["state"]


def test_the_state_carries_the_inner_voice_of_the_latest_trace(monkeypatch):
    trace = {
        "primary_emotion": "tenderness",
        "intensity": 0.85,
        "emotion_vector": {"tenderness": 0.9},
        "notes": {
            "affective_state": {"trigger": "The user's affectionate surprise."},
            "inner_voice": "Мне тепло, потому что ты спросил так ласково.",
        },
    }

    state = _state(monkeypatch, [trace])

    assert state["inner_voice"] == "Мне тепло, потому что ты спросил так ласково."
    assert state["trigger"] == "The user's affectionate surprise."


def test_without_an_inner_voice_the_state_has_an_empty_one(monkeypatch):
    trace = {"primary_emotion": "joy", "notes": {"affective_state": {"trigger": "thanks"}}}

    state = _state(monkeypatch, [trace])

    assert state["inner_voice"] == ""
    assert state["trigger"] == "thanks"
