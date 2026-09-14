"""The model index: what each model can do.

The metadata says what a model can do and no model
is run to check; the owner's marks win and the settings remind where they differ;
a model no longer installed leaves the index, decided only while Ollama answers.
"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from core.interaction import InteractionPolicy
from modules.database import core as database_core
from modules.database.core import Base
from modules.model_index import service as model_index
from routes import model_index_routes


class FakeOllama:
    def __init__(self):
        self.available = True
        self.installed = {}
        self.declared = {}
        self.metadata_reads = []

    def list_runtime_models(self):
        if not self.available:
            return {"status": "error", "message": "Ollama not installed, not running or not accessible", "models": []}
        return {"status": "ok", "models": [{"name": name, "digest": digest} for name, digest in self.installed.items()]}

    def model_capabilities(self, name):
        self.metadata_reads.append(name)
        declared = self.declared.get(name)
        if declared is None:
            return {"status": "ok", "model": name, "declared": False, "capabilities": []}
        return {"status": "ok", "model": name, "declared": True, "capabilities": declared}


@pytest.fixture
def ollama(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'core.db'}")
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(model_index, "SessionLocal", sessionmaker(bind=engine))
    fake = FakeOllama()
    monkeypatch.setattr(model_index.ollama_client, "list_runtime_models", fake.list_runtime_models)
    monkeypatch.setattr(model_index.ollama_client, "model_capabilities", fake.model_capabilities)
    yield fake
    engine.dispose()


def _entry(name, capability=None):
    [entry] = [item for item in model_index.list_entries(capability=capability) if item["name"] == name]
    return entry


def test_an_installed_model_is_indexed_with_what_ollama_declares(ollama):
    ollama.installed = {"qwen3-vl:8b": "d1", "legacy:7b": "d2"}
    ollama.declared = {"qwen3-vl:8b": ["completion", "vision", "thinking"]}

    assert model_index.sync_ollama() == {"status": "ok", "added": 2, "refreshed": 0, "removed": 0}

    assert _entry("qwen3-vl:8b") == {
        "provider": "ollama",
        "name": "qwen3-vl:8b",
        "capabilities": ["completion", "thinking", "vision"],
        "declared": ["completion", "thinking", "vision"],
        "declared_known": True,
        "owner_marked": False,
        "differs": False,
    }
    assert _entry("legacy:7b")["declared_known"] is False
    assert _entry("legacy:7b")["capabilities"] == []


def test_the_metadata_is_read_again_only_after_a_new_pull(ollama):
    ollama.installed = {"qwen3:8b": "d1"}
    ollama.declared = {"qwen3:8b": ["completion"]}

    model_index.sync_ollama()
    model_index.sync_ollama()
    assert ollama.metadata_reads == ["qwen3:8b"]

    ollama.installed = {"qwen3:8b": "d2"}
    ollama.declared = {"qwen3:8b": ["completion", "tools"]}
    assert model_index.sync_ollama()["refreshed"] == 1
    assert ollama.metadata_reads == ["qwen3:8b", "qwen3:8b"]
    assert _entry("qwen3:8b")["capabilities"] == ["completion", "tools"]


def test_the_owners_marks_win_and_the_difference_is_shown(ollama):
    ollama.installed = {"llava:latest": "d1"}
    ollama.declared = {"llava:latest": ["completion"]}
    model_index.sync_ollama()

    marked = model_index.set_owner_capabilities("ollama", "llava:latest", ["completion", "vision"])

    assert marked["capabilities"] == ["completion", "vision"]
    assert marked["owner_marked"] is True
    assert marked["differs"] is True

    ollama.installed = {"llava:latest": "d2"}
    ollama.declared = {"llava:latest": ["completion", "tools"]}
    model_index.sync_ollama()
    entry = _entry("llava:latest")
    assert entry["capabilities"] == ["completion", "vision"]
    assert entry["declared"] == ["completion", "tools"]
    assert entry["differs"] is True


def test_marks_equal_to_the_metadata_follow_the_metadata_again(ollama):
    ollama.installed = {"qwen3:8b": "d1"}
    ollama.declared = {"qwen3:8b": ["completion", "tools"]}
    model_index.sync_ollama()
    model_index.set_owner_capabilities("ollama", "qwen3:8b", ["completion"])

    entry = model_index.set_owner_capabilities("ollama", "qwen3:8b", ["tools", "completion"])

    assert entry["owner_marked"] is False
    assert entry["differs"] is False


def test_unknown_capabilities_and_models_are_refused(ollama):
    ollama.installed = {"qwen3:8b": "d1"}
    ollama.declared = {"qwen3:8b": ["completion"]}
    model_index.sync_ollama()

    with pytest.raises(ValueError):
        model_index.set_owner_capabilities("ollama", "qwen3:8b", ["telepathy"])
    with pytest.raises(LookupError):
        model_index.set_owner_capabilities("ollama", "missing:1b", ["completion"])


def test_a_model_removed_from_ollama_leaves_the_index(ollama):
    ollama.installed = {"qwen3:8b": "d1", "old:7b": "d2"}
    ollama.declared = {"qwen3:8b": ["completion"], "old:7b": ["completion"]}
    model_index.sync_ollama()

    ollama.installed = {"qwen3:8b": "d1"}
    assert model_index.sync_ollama()["removed"] == 1

    assert [entry["name"] for entry in model_index.list_entries()] == ["qwen3:8b"]


def test_with_ollama_off_nothing_is_removed(ollama):
    ollama.installed = {"qwen3:8b": "d1"}
    ollama.declared = {"qwen3:8b": ["completion"]}
    model_index.sync_ollama()

    ollama.available = False
    assert model_index.sync_ollama()["status"] == "unavailable"

    assert [entry["name"] for entry in model_index.list_entries()] == ["qwen3:8b"]


def test_the_index_filters_by_capability(ollama):
    ollama.installed = {"qwen3-vl:8b": "d1", "qwen3:8b": "d2", "nomic-embed-text": "d3"}
    ollama.declared = {
        "qwen3-vl:8b": ["completion", "vision"],
        "qwen3:8b": ["completion", "tools"],
        "nomic-embed-text": ["embedding"],
    }
    model_index.sync_ollama()

    assert [entry["name"] for entry in model_index.list_entries(capability="vision")] == ["qwen3-vl:8b"]
    assert [entry["name"] for entry in model_index.list_entries(capability="completion")] == ["qwen3-vl:8b", "qwen3:8b"]


def test_an_existing_database_gets_the_table(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    monkeypatch.setattr(database_core, "engine", engine)

    database_core._ensure_model_index_table()
    database_core._ensure_model_index_table()

    assert "model_index" in inspect(engine).get_table_names()
    with engine.connect() as conn:
        indexes = [row[1] for row in conn.execute(text("PRAGMA index_list(model_index)"))]
    assert "uq_model_index_provider_name" in indexes
    engine.dispose()


@pytest.mark.parametrize("role", ["user", "anonymous"])
def test_only_the_owner_reads_or_marks_the_index(monkeypatch, role):
    monkeypatch.setattr(model_index_routes, "resolve_actor_uuid_from_auth_header", lambda header: "someone")
    monkeypatch.setattr(
        model_index_routes,
        "resolve_interaction_policy",
        lambda uuid: InteractionPolicy(actor_role=role, can_affect_moral=False, can_affect_global_memory=False),
    )
    touched = []
    monkeypatch.setattr(model_index_routes.model_index, "sync_ollama", lambda: touched.append("sync"))
    monkeypatch.setattr(model_index_routes.model_index, "set_owner_capabilities", lambda *args: touched.append(args))
    request = SimpleNamespace(headers={})

    for call in (
        lambda: model_index_routes.get_model_index(request, provider="ollama", capability=None),
        lambda: model_index_routes.set_model_capabilities(
            model_index_routes.OwnerCapabilitiesRequest(name="qwen3:8b", capabilities=["vision"]), request
        ),
    ):
        with pytest.raises(HTTPException) as refused:
            asyncio.run(call())
        assert refused.value.status_code == 403

    assert touched == []
