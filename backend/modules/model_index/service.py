"""The model index: what each model can do.

Rules:
- A model is not run to find out what it can do. Its provider's metadata says it
  (Ollama: /api/show capabilities); a capability it does not declare is absent.
- The owner marks capabilities by hand in the models settings. The owner's marks
  win over the metadata; the settings remind where the two differ.
- A model that is no longer installed leaves the index. That is only decided
  while Ollama answers: with Ollama off nothing is touched.
- The metadata is read again only when a model's digest changes (a new pull), so
  opening a model list does not ask Ollama about every model.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional

from models.models import ModelIndexEntry
from modules.database.core import SessionLocal
from modules.ollama import client as ollama_client

OLLAMA = "ollama"
KNOWN_CAPABILITIES = ("completion", "vision", "tools", "thinking", "embedding", "insert")


def _loads(raw: Optional[str]) -> List[str]:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return sorted({str(item).strip().lower() for item in value if str(item).strip()}) if isinstance(value, list) else []


def _dumps(capabilities: Iterable[str]) -> str:
    return json.dumps(sorted({str(item).strip().lower() for item in capabilities or [] if str(item).strip()}))


def _serialize(row: ModelIndexEntry) -> Dict[str, Any]:
    declared = _loads(row.declared_capabilities)
    owner = None if row.owner_capabilities is None else _loads(row.owner_capabilities)
    return {
        "provider": row.provider,
        "name": row.name,
        "capabilities": owner if owner is not None else declared,
        "declared": declared,
        "declared_known": bool(row.declared_known),
        "owner_marked": owner is not None,
        "differs": owner is not None and set(owner) != set(declared),
    }


def sync_ollama() -> Dict[str, Any]:
    """Bring the Ollama part of the index in line with what is installed."""
    installed = ollama_client.list_runtime_models()
    if installed.get("status") != "ok":
        return {"status": "unavailable", "reason": installed.get("message") or "Ollama is unavailable"}
    present = {
        str(item.get("name")): item.get("digest")
        for item in installed.get("models") or []
        if item.get("name")
    }

    added = refreshed = removed = 0
    session = SessionLocal()
    try:
        rows = {
            row.name: row
            for row in session.query(ModelIndexEntry).filter(ModelIndexEntry.provider == OLLAMA)
        }
        for name, digest in present.items():
            row = rows.get(name)
            if row is not None and digest and row.digest == digest:
                continue
            declared = ollama_client.model_capabilities(name)
            if declared.get("status") != "ok":
                continue
            if row is None:
                row = ModelIndexEntry(provider=OLLAMA, name=name)
                session.add(row)
                added += 1
            else:
                refreshed += 1
            row.digest = digest
            row.declared_known = bool(declared.get("declared"))
            row.declared_capabilities = _dumps(declared.get("capabilities") or [])
        for name, row in rows.items():
            if name not in present:
                session.delete(row)
                removed += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return {"status": "ok", "added": added, "refreshed": refreshed, "removed": removed}


def list_entries(provider: str = OLLAMA, capability: Optional[str] = None) -> List[Dict[str, Any]]:
    session = SessionLocal()
    try:
        rows = (
            session.query(ModelIndexEntry)
            .filter(ModelIndexEntry.provider == provider)
            .order_by(ModelIndexEntry.name.asc())
            .all()
        )
        entries = [_serialize(row) for row in rows]
    finally:
        session.close()
    wanted = str(capability or "").strip().lower()
    if wanted:
        entries = [entry for entry in entries if wanted in entry["capabilities"]]
    return entries


def capabilities_of(provider: str, name: str) -> Optional[List[str]]:
    """What a model can do by the index; the index is synced first when it does not know the model.

    None: the model is not in the index even after the sync (not installed, or Ollama off).
    """
    entry = _find(provider, name)
    if entry is None and provider == OLLAMA:
        sync_ollama()
        entry = _find(provider, name)
    return entry["capabilities"] if entry else None


def _find(provider: str, name: str) -> Optional[Dict[str, Any]]:
    session = SessionLocal()
    try:
        row = (
            session.query(ModelIndexEntry)
            .filter(ModelIndexEntry.provider == provider, ModelIndexEntry.name == name)
            .first()
        )
        return _serialize(row) if row else None
    finally:
        session.close()


def set_owner_capabilities(provider: str, name: str, capabilities: Optional[List[str]]) -> Dict[str, Any]:
    """The owner's marks for a model; marks equal to the metadata follow the metadata again."""
    marks = None if capabilities is None else _loads(json.dumps(list(capabilities)))
    unknown = sorted(set(marks or []) - set(KNOWN_CAPABILITIES))
    if unknown:
        raise ValueError(f"Unknown capabilities: {', '.join(unknown)}")
    session = SessionLocal()
    try:
        row = (
            session.query(ModelIndexEntry)
            .filter(ModelIndexEntry.provider == provider, ModelIndexEntry.name == name)
            .first()
        )
        if row is None:
            raise LookupError(f"The model is not in the index: {name}")
        if marks is None or set(marks) == set(_loads(row.declared_capabilities)):
            row.owner_capabilities = None
        else:
            row.owner_capabilities = _dumps(marks)
        session.commit()
        return _serialize(row)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
