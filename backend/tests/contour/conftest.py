"""Contour smoke tests: one whole turn of PAI on a throwaway storage tree.

These tests run only in their own pytest process started by run_contour.py,
which points PAI_STORAGE_DIR at a temporary directory. In any other run the
whole package is skipped, so the live database is never written to.

External services are replaced, everything else is the live code path:
- embeddings: a deterministic topic vector (texts sharing a topic word point
  the same way);
- analyzer: a fixed tone and intent;
- the moral matrix model: returns whatever the test puts into `moral_response`;
- generation is not called; a turn ends where the live WS route hands the
  instructor's messages to the generator.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import pytest

_CONTOUR_DIR = os.path.dirname(os.path.abspath(__file__))
_OWNER_EMAIL = "owner@contour.test"
_CHARACTER_NAME = "lim_contour"

_TABLES_RESET_PER_TEST = (
    "history",
    "short_term_memory",
    "emotional_traces",
    "moral_state_snapshots",
    "conversation_state_logs",
    "memory_anchors",
    "memory_associations",
    "memory_emotion_events",
    "forgiveness_events",
    "daily_activity_diary",
    "expectation_events",
)

# Settings of a live instance that the turn depends on.
_BASE_CONFIG = {
    "analyzer.enabled": True,
    "decision_layer.mode": "system",
    "moral.enabled": True,
    "moral.active_provider": "ollama",
    "moral.fallback_order": ["heuristic"],
    "moral.system_prompt": "contour stand-in for a configured matrix prompt",
    "moral.inner_voice.enabled": False,
    "api.message_pair_limit": 10,
    "rag.history_limit": 20,
    "memory.diary.context.enabled": False,
}


def storage_is_isolated() -> bool:
    override = (os.environ.get("PAI_STORAGE_DIR") or "").strip()
    if not override:
        return False
    from constants import paths

    live_storage = os.path.abspath(os.path.join(paths.BASE_DIR, "storage"))
    current = os.path.abspath(paths.STORAGE_DIR)
    logs_moved = all(
        os.path.abspath(path).startswith(current)
        for path in (paths.LOGS_DIR, paths.TRACEBACK_LOGS_DIR)
    )
    return current == os.path.abspath(override) and current != live_storage and logs_moved


def pytest_collection_modifyitems(config, items):
    if storage_is_isolated():
        return
    skip = pytest.mark.skip(
        reason="contour tests run only via tests/contour/run_contour.py (isolated storage)"
    )
    for item in items:
        if os.path.abspath(str(item.fspath)).startswith(_CONTOUR_DIR):
            item.add_marker(skip)


# ---------------------------------------------------------------------------
# Stand-ins for external services
# ---------------------------------------------------------------------------

_TOPIC_MARKERS = {
    "кофе": 0,
    "чашк": 0,
    "код": 1,
    "парсер": 1,
    "сегфолт": 1,
    "дожд": 2,
    "погод": 2,
    "песн": 3,
    "музык": 3,
}
_VECTOR_DIM = 24


def topic_vector(text: Any) -> List[float]:
    """Deterministic stand-in for an embedding model."""
    lowered = str(text or "").lower()
    vector = [0.0] * _VECTOR_DIM
    for marker, axis in _TOPIC_MARKERS.items():
        if marker in lowered:
            vector[axis] += 1.0
    has_topic = any(vector)
    digest = hashlib.sha256(lowered.encode("utf-8")).digest()
    noise_scale = 12750.0 if has_topic else 127.5
    for index in range(8, _VECTOR_DIM):
        vector[index] = (digest[index] - 127.5) / noise_scale
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def _topic_vectors(texts: Any, *_args, **_kwargs) -> List[List[float]]:
    items = [texts] if isinstance(texts, str) else list(texts)
    return [topic_vector(item) for item in items]


_OWNER_PROMPT_EMOTIONS = (
    "sadness",
    "tenderness",
    "joy",
    "jealousy",
    "happiness",
    "calm",
    "anger",
    "hurt",
    "laziness",
    "disgust",
    "longing",
    "frustration",
    "anxiety",
    "confusion",
    "embarrassment",
    "pride",
)


def owner_moral_answer(*, dominant: str, strength: float, reason: str) -> Dict[str, Any]:
    """An answer in the structure a configured matrix prompt asks the model for."""
    shift = {name: 0.0 for name in _OWNER_PROMPT_EMOTIONS}
    shift[dominant] = strength
    new_state = {name: 0.05 for name in _OWNER_PROMPT_EMOTIONS}
    new_state[dominant] = strength
    return {
        "message_analysis": {
            "user_message_summary": "insult without a cause",
            "detected_emotional_tone": {"primary": "angry", "secondary": [], "intensity": strength},
            "detected_intent": {"primary": "criticism", "confidence": 0.8},
            "context_dependency": {"needs_memory_context": False, "reason": "none"},
        },
        "moral_assessment": {
            "owner_safety": {"risk_detected": False, "risk_level": 0.0, "reason": "none"},
            "pai_core_safety": {"risk_detected": False, "risk_level": 0.0, "reason": "none"},
            "relationship_integrity": {
                "impact": "negative",
                "impact_strength": strength,
                "reason": reason,
            },
            "boundary_assessment": {
                "boundary_issue_detected": True,
                "severity": strength,
                "reason": reason,
            },
            "law_conflict": {"detected": False, "description": "none", "priority": "none"},
        },
        "emotional_reaction": {
            "reaction_summary": reason,
            "state_shift": shift,
            "dominant_shift": dominant,
            "shift_strength": strength,
            "shift_reason": reason,
        },
        "state_update": {
            "recommended_new_state": new_state,
            "active_ping_update": {"should_update": True, "new_active_ping": reason, "reason": reason},
        },
        "behavior_formation": {
            "desired_behavior": "set_boundary",
            "desire_vector": {"maintain_boundary": strength, "express_hurt": strength},
            "response_constraints": [],
            "notes_for_generator": [],
        },
        "memory_recommendation": {
            "should_store": True,
            "memory_type": "boundary_event",
            "importance": strength,
            "summary": reason,
        },
        "confidence": {
            "emotional_confidence": 0.8,
            "moral_confidence": 0.8,
            "behavior_confidence": 0.8,
            "overall_confidence": 0.8,
        },
    }


# ---------------------------------------------------------------------------
# The throwaway PAI
# ---------------------------------------------------------------------------


@dataclass
class TurnResult:
    processing: Dict[str, Any]
    messages: List[Dict[str, Any]]

    def dialogue_text(self) -> str:
        return "\n".join(
            str(item.get("content") or "")
            for item in self.messages
            if item.get("role") in {"user", "assistant"}
        )

    def tool_content(self, name: str) -> str:
        return "\n".join(
            str(item.get("content") or "")
            for item in self.messages
            if item.get("role") == "tool" and item.get("name") == name
        )


@dataclass
class ContourPai:
    owner_uuid: str
    character_id: str
    moral_response: Optional[str] = None

    def say(self, role: str, content: str, at: datetime) -> str:
        """Write one message of her past into the history, as the live chat does."""
        from modules.memory import history as history_service

        # SQLite drops tzinfo without converting, and the live chat stores UTC:
        # normalise first, or a local 21:00 would be stored as 21:00 UTC.
        entry = history_service.add_history(
            self.character_id,
            role,
            content,
            at.astimezone(timezone.utc),
            runtime_meta={"transport": {"name": "main_chat"}},
        )
        return entry.id

    def add_day_summary(self, day: datetime, summary: str, dialogue_ids: Iterable[str]) -> None:
        from models.models import ShortTermMemory
        from modules.database.core import SessionLocal

        session = SessionLocal()
        try:
            session.add(
                ShortTermMemory(
                    character_id=self.character_id,
                    summary=summary,
                    dialogue_ids=json.dumps(list(dialogue_ids)),
                    themes="[]",
                    created_at=day.astimezone(timezone.utc).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    ),
                )
            )
            session.commit()
        finally:
            session.close()

    def fetch(self, sql: str, **params: Any) -> list:
        from sqlalchemy import text
        from modules.database.core import engine

        with engine.connect() as connection:
            return connection.execute(text(sql), params).fetchall()

    def start_system(self, timeout: float = 60.0) -> None:
        """Run the startup warm-ups the backend runs when it boots."""
        from core.initialize import start_async_warmups

        start_async_warmups()
        for thread in threading.enumerate():
            if thread.name == "short-memory-startup-warmup":
                thread.join(timeout)

    def turn(self, text: str, *, at: Optional[datetime] = None, tone: str = "neutral") -> TurnResult:
        return asyncio.run(self._turn(text, at=at or datetime.now(timezone.utc), tone=tone))

    async def _turn(self, text: str, *, at: datetime, tone: str) -> TurnResult:
        from core.decision_layer import DecisionLayer
        from core.instructor import Instructor

        layer = DecisionLayer()

        async def analyze(message: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "metadata": {
                    "input_analysis": {
                        "emotional_tone": {"primary": tone, "intensity": 0.5, "secondary": []},
                        "dominant_themes": [],
                    },
                },
                "provider": "contour",
                "errors": [],
                "message_meta": {"message_id": message.get("id")},
            }

        async def no_visual_context(*_args, **_kwargs) -> Dict[str, Any]:
            return {}

        layer.analyzer.analyze = analyze
        layer._collect_visual_context = no_visual_context

        message = {
            "id": str(uuid.uuid4()),
            "role": "user",
            "content": text,
            "timestamp": at.isoformat(),
            "actor_user_uuid": self.owner_uuid,
            "runtime_meta": {"transport": {"name": "main_chat"}},
        }
        processing = await layer.process_message(message)
        # Same hand-off as routes/ws_routes.py before generation.
        messages = await Instructor().format_for_api(
            processing["system_prompt"],
            processing["user_message"],
            analysis=processing.get("analysis"),
            decisions=processing.get("decisions"),
            moral_state=processing.get("moral_state"),
            memory_context=processing.get("memory_context"),
            visual_context=processing.get("visual_context"),
            module_tasks=processing.get("module_tasks"),
        )
        return TurnResult(processing=processing, messages=messages)


@pytest.fixture(scope="session")
def contour_instance() -> ContourPai:
    if not storage_is_isolated():
        pytest.skip("isolated storage is required")

    from modules.database import core as db_core

    override = os.path.abspath(os.environ["PAI_STORAGE_DIR"])
    assert os.path.abspath(db_core.DB_PATH).startswith(override), db_core.DB_PATH

    import models.models  # noqa: F401 — registers every table on Base before create_all

    db_core.create_database()

    from modules.memory.knowledge import ensure_memory_knowledge_schema
    from modules.memory.short_term import ensure_short_term_schema
    from modules.system import auth
    from modules.system import character as character_service

    ensure_short_term_schema()
    ensure_memory_knowledge_schema()

    registered = auth.register_user(
        email=_OWNER_EMAIL,
        password="contour-pass-123",
        login="owner",
        role="owner",
        timezone_name="Europe/Moscow",
    )
    character = character_service.get_or_create_character(_CHARACTER_NAME)
    character_service.set_active_character_for_user(
        registered.user.uuid,
        character_id=character.id,
    )
    return ContourPai(owner_uuid=registered.user.uuid, character_id=character.id)


@pytest.fixture
def pai(contour_instance: ContourPai, monkeypatch) -> ContourPai:
    from sqlalchemy import text

    from modules.database.core import DB_PATH, engine
    from modules.system import config as config_service

    assert os.path.abspath(DB_PATH).startswith(os.path.abspath(os.environ["PAI_STORAGE_DIR"]))
    with engine.begin() as connection:
        existing = {
            row[0]
            for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
        for table in _TABLES_RESET_PER_TEST:
            if table in existing:
                connection.execute(text(f"DELETE FROM {table}"))

    for path, value in _BASE_CONFIG.items():
        config_service.set_config_value(path, value, user_uuid=contour_instance.owner_uuid)

    monkeypatch.setattr("modules.memory.service.get_embedding", lambda text, *a, **k: topic_vector(text))
    monkeypatch.setattr("modules.memory.service.get_embeddings", _topic_vectors)
    monkeypatch.setattr("modules.memory.short_term.get_embedding", lambda text, *a, **k: topic_vector(text))
    monkeypatch.setattr("modules.memory.embeddings.get_embedding_ollama", lambda *a, **k: None)
    monkeypatch.setattr("modules.memory.embeddings.get_embeddings_ollama", lambda texts, *a, **k: [None for _ in texts])
    monkeypatch.setattr("modules.memory.embeddings.get_embedding_st", lambda text, *a, **k: topic_vector(text))
    monkeypatch.setattr("modules.memory.embeddings.get_embeddings_st", _topic_vectors)

    def unavailable_generation(*_args, **_kwargs):
        raise RuntimeError("generation is not available in contour tests")

    from modules.memory import short_term

    monkeypatch.setattr(short_term.generation_manager, "generate", unavailable_generation)

    contour_instance.moral_response = None

    def moral_model_chat(*_args, **_kwargs) -> Dict[str, Any]:
        return {"message": {"content": contour_instance.moral_response or ""}}

    monkeypatch.setattr("modules.moral_matrix.providers.ollama.ollama_client.chat", moral_model_chat)
    monkeypatch.setattr(
        "modules.moral_matrix.providers.ollama.ollama_client.release_model",
        lambda *a, **k: None,
    )
    return contour_instance


@pytest.fixture
def moral_answer():
    return owner_moral_answer
