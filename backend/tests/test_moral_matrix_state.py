import asyncio

import pytest

from core.instructor import Instructor
from modules.moral_matrix.providers.ollama import OllamaMoralProvider
from modules.moral_matrix.service import MoralMatrixModule, ProviderRunResult


pytestmark = pytest.mark.regression


class _FakeMoralRepository:
    def __init__(self):
        self.snapshots = []
        self.traces = []
        self.outcomes = []

    def fetch_recent_traces(self, _character_id, limit=10):
        return [
            {
                "id": "recent-1",
                "primary_emotion": "tenderness",
                "intensity": 0.4,
                "cause": "user was warm before",
                "emotion_vector": {"tenderness": 0.4},
            }
        ][:limit]

    def fetch_traces_for_messages(self, _character_id, _message_ids):
        return []

    def fetch_similar_traces(self, _character_id, query_text, *, limit=5, scan_limit=160):
        if "спасибо" not in query_text.lower():
            return []
        return [
            {
                "id": "similar-1",
                "primary_emotion": "joy",
                "intensity": 0.5,
                "cause": "similar praise",
                "emotion_vector": {"joy": 0.5},
                "similarity_score": 0.5,
            }
        ][:limit]

    def fetch_latest_snapshot(self, _character_id):
        return {
            "id": "snap-1",
            "trust": 0.7,
            "stability": 0.6,
            "sociability": 0.55,
            "resentment": 0.04,
            "mood": "peace",
            "meta": {
                "affective_state": {
                    "state": "peace",
                    "intensity": 0.34,
                    "emotion_vector": {"peace": 0.34, "joy": 0.2, "tenderness": 0.2},
                    "trigger": "previous calm state",
                }
            },
        }

    def fetch_daily_summary(self, _character_id, _date):
        return {}

    def store_snapshot(self, character_id, message_id, payload):
        self.snapshots.append((character_id, message_id, payload))
        return "stored-snapshot"

    def store_emotional_trace(self, character_id, *, message_id, payload):
        self.traces.append((character_id, message_id, payload))
        return "stored-trace"

    def annotate_previous_trace_outcome(self, character_id, *, current_message_id, payload):
        self.outcomes.append((character_id, current_message_id, payload))
        return "recent-1"


class _FakeProviderManager:
    async def run(self, payload):
        assert payload["previous_state"]["state"] == "peace"
        assert payload["current_state"]["state"] in payload["allowed_emotions"]
        assert payload["memory_traces"]
        return ProviderRunResult(
            provider="test",
            payload={
                "summary": "Мне радостно и тепло, потому что пользователь меня поддержал.",
                "current_state": {
                    "state": "joy",
                    "intensity": 0.82,
                    "trigger": "пользователь поблагодарил и похвалил",
                    "associated_events": ["message:u1", "similar_trace:similar-1"],
                    "influence": {
                        "initiative": 0.2,
                        "tone": "живой",
                        "reaction_delay": "-0.2s",
                    },
                },
                "emotion_vector_delta": {"joy": 0.2, "tenderness": 0.1},
                "metrics_delta": {"trust": 0.05, "sociability": 0.04},
                "hard_directives": ["stay_warm"],
                "soft_recommendations": ["respond with visible joy"],
            },
        )


def test_moral_matrix_applies_provider_transition_and_persists_current_state(monkeypatch):
    module = MoralMatrixModule()
    fake_repo = _FakeMoralRepository()
    module._repository = fake_repo
    module._provider_manager = _FakeProviderManager()
    monkeypatch.setattr(module, "_resolve_character_id", lambda: "char-1")

    config_updates = {}

    def fake_get_config(path, default=None):
        if path == "moral.enabled":
            return True
        return default

    monkeypatch.setattr("modules.moral_matrix.service.config_service.get_config_value", fake_get_config)
    monkeypatch.setattr(
        "modules.moral_matrix.service.config_service.set_config_value",
        lambda path, value: config_updates.setdefault(path, value) or True,
    )

    payload = asyncio.run(
        module.evaluate(
            analysis_result={
                "input_analysis": {
                    "emotional_tone": {
                        "primary": "joy",
                        "intensity": 0.55,
                        "secondary": ["warmth"],
                    }
                }
            },
            memory_context={"matches": [], "conversation_state": {}},
            memory_meta={"matches_found": 1},
            message_meta={"message_id": "u1"},
            user_message={"id": "u1", "role": "user", "content": "Лим, спасибо, ты умница"},
            persist_state=True,
        )
    )

    assert payload["current_emotion"] == "joy"
    assert payload["emotion_intensity"] == 0.82
    assert payload["trigger"] == "пользователь поблагодарил и похвалил"
    assert payload["affective_state"]["influence"]["tone"] == "живой"
    assert payload["emotion_vector"]["joy"] >= 0.82
    assert payload["metrics"]["trust"] > 0.7
    assert payload["meta"]["transition_provider"] == "test"
    assert fake_repo.snapshots
    assert fake_repo.traces[0][2]["notes"]["affective_state"]["state"] == "joy"
    assert fake_repo.outcomes
    assert config_updates["moral.current_state"]["current_emotion"] == "joy"


def test_instructor_emotion_tool_contains_trigger_and_influence(monkeypatch):
    instructor = Instructor()
    monkeypatch.setattr(
        instructor,
        "_build_environment_tool_content",
        lambda: "Date: 09 May 2026\nTime: 12:00:00",
    )

    messages = asyncio.run(
        instructor.format_for_api(
            system_prompt="base",
            user_message={"id": "u1", "content": "hello", "history": []},
            moral_state={
                "current_emotion": "joy",
                "emotion_intensity": 0.82,
                "relationship_status": "very close",
                "trigger": "пользователь похвалил",
                "influence": {
                    "initiative": 0.2,
                    "tone": "живой",
                    "reaction_delay": "-0.2s",
                    "behavior": "Повышенная активность",
                },
                "associated_events": ["message:u1"],
                "affective_state": {"label": "Радость"},
            },
        )
    )

    emotion_tool = next(
        item for item in messages if item.get("role") == "tool" and item.get("name") == "state.emotion"
    )
    content = str(emotion_tool.get("content") or "")
    assert "Радость (joy)" in content
    assert "Why this state changed: пользователь похвалил" in content
    assert "tone=живой" in content
    assert "message:u1" in content


def test_ollama_moral_provider_disables_thinking_by_default(monkeypatch):
    captured = {}

    def fake_get_config(path, default=None):
        if path == "moral.providers.ollama":
            return {"model": "gpt-oss:20b", "temperature": 0.3, "max_tokens": 128}
        if path == "moral.system_prompt":
            return "Return strict JSON."
        return default

    def fake_chat(messages, options, model=None):
        captured["messages"] = messages
        captured["options"] = options
        captured["model"] = model
        return {"message": {"content": '{"summary":"ok"}'}}

    monkeypatch.setattr(
        "modules.moral_matrix.providers.ollama.config_service.get_config_value",
        fake_get_config,
    )
    monkeypatch.setattr(
        "modules.moral_matrix.providers.ollama.ollama_client.chat",
        fake_chat,
    )

    result = OllamaMoralProvider._call_ollama({"message": "test"}, OllamaMoralProvider()._get_settings())

    assert result == {"summary": "ok"}
    assert captured["model"] == "gpt-oss:20b"
    assert captured["options"]["__think"] is False


def test_ollama_moral_provider_returns_none_on_empty_content(monkeypatch):
    def fake_get_config(path, default=None):
        if path == "moral.providers.ollama":
            return {"model": "gpt-oss:20b", "temperature": 0.3, "max_tokens": 128}
        if path == "moral.system_prompt":
            return "Return strict JSON."
        return default

    monkeypatch.setattr(
        "modules.moral_matrix.providers.ollama.config_service.get_config_value",
        fake_get_config,
    )
    monkeypatch.setattr(
        "modules.moral_matrix.providers.ollama.ollama_client.chat",
        lambda *_args, **_kwargs: {"message": {"content": ""}},
    )

    result = OllamaMoralProvider._call_ollama(
        {"message": "test"},
        OllamaMoralProvider()._get_settings(),
    )

    assert result is None
