"""Character service: DB-first prompt storage with YAML import compatibility."""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any, Dict, Optional

import yaml
from sqlalchemy.orm import Session

from models.models import Character, History, UserSettings
from modules.database.core import SessionLocal

CHARACTERS_DIR = "config/characters"
_YAML_EXTS = (".yaml", ".yml")
_PROMPT_KEYS = ("prompt", "system_prompt", "systemPrompt")


def _normalize_character_name(name: str) -> str:
    raw = (name or "").strip()
    if not raw:
        return ""
    normalized = re.sub(r"[\\/:*?\"<>|]+", " ", raw)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _safe_load_configs(raw: str) -> Dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {}


def _safe_dump_configs(payload: Dict[str, Any]) -> str:
    return json.dumps(payload or {}, ensure_ascii=False)


def _find_character_yaml_path(char_name: str) -> Optional[str]:
    for ext in _YAML_EXTS:
        candidate = os.path.join(CHARACTERS_DIR, f"{char_name}{ext}")
        if os.path.exists(candidate):
            return candidate
    return None


def _extract_prompt(payload: Dict[str, Any]) -> str:
    for key in _PROMPT_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_name_from_payload(payload: Dict[str, Any], fallback_file_name: str) -> str:
    for key in ("name", "char_name", "character", "id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            normalized = _normalize_character_name(value)
            if normalized:
                return normalized
    fallback_name = os.path.splitext(os.path.basename(fallback_file_name or ""))[0]
    normalized_fallback = _normalize_character_name(fallback_name)
    return normalized_fallback or "Character Name"


def _read_yaml_prompt(char_name: str) -> str:
    yaml_path = _find_character_yaml_path(char_name)
    if not yaml_path:
        return ""
    try:
        with open(yaml_path, "r", encoding="utf-8") as fh:
            payload = yaml.safe_load(fh) or {}
            if isinstance(payload, dict):
                return _extract_prompt(payload)
    except Exception:
        return ""
    return ""


def get_or_create_character(name: str, prompt: str | None = None) -> Character:
    normalized_name = _normalize_character_name(name)
    if not normalized_name:
        raise ValueError("Character name cannot be empty")

    session: Session = SessionLocal()
    try:
        char = session.query(Character).filter_by(name=normalized_name).first()
        if char:
            if isinstance(prompt, str) and prompt.strip():
                configs = _safe_load_configs(char.configs)
                configs["prompt"] = prompt.strip()
                configs.setdefault("source", "db")
                char.configs = _safe_dump_configs(configs)
                session.commit()
                session.refresh(char)
            return char

        configs: Dict[str, Any] = {}
        if isinstance(prompt, str) and prompt.strip():
            configs["prompt"] = prompt.strip()
            configs["source"] = "db"

        new_char = Character(
            id=str(uuid.uuid4()),
            name=normalized_name,
            configs=_safe_dump_configs(configs),
        )
        session.add(new_char)
        session.commit()
        session.refresh(new_char)
        return new_char
    finally:
        session.close()


def get_character(name: str) -> Optional[Character]:
    normalized_name = _normalize_character_name(name)
    if not normalized_name:
        return None
    session: Session = SessionLocal()
    try:
        return session.query(Character).filter_by(name=normalized_name).first()
    finally:
        session.close()


def get_character_by_id(character_id: str) -> Optional[Character]:
    if not character_id:
        return None
    session: Session = SessionLocal()
    try:
        return session.query(Character).filter_by(id=character_id).first()
    finally:
        session.close()


def list_characters(sync_from_yaml: bool = True) -> list[dict]:
    if sync_from_yaml:
        import_characters_from_yaml_dir(update_existing=False)

    session: Session = SessionLocal()
    try:
        records = session.query(Character).order_by(Character.name.asc()).all()
        payload: list[dict] = []
        for char in records:
            configs = _safe_load_configs(char.configs)
            prompt = str(configs.get("prompt") or "").strip()
            if not prompt:
                prompt = _read_yaml_prompt(char.name)
            payload.append(
                {
                    "id": char.id,
                    "name": char.name,
                    "prompt": prompt,
                    "has_prompt": bool(prompt),
                    "source": str(configs.get("source") or "db"),
                    "updated_at": char.updated_at.isoformat() if char.updated_at else None,
                }
            )
        return payload
    finally:
        session.close()


def get_active_character_for_user(user_uuid: str) -> Optional[dict]:
    if not user_uuid:
        return None
    session: Session = SessionLocal()
    try:
        settings = session.query(UserSettings).filter_by(user_uuid=user_uuid).first()
        if not settings or not settings.active_character_id:
            return None
        character = session.query(Character).filter_by(id=settings.active_character_id).first()
        if not character:
            return None
        configs = _safe_load_configs(character.configs)
        prompt = str(configs.get("prompt") or "").strip() or _read_yaml_prompt(character.name)
        return {"id": character.id, "name": character.name, "prompt": prompt}
    finally:
        session.close()


def get_last_history_character() -> Optional[dict]:
    session: Session = SessionLocal()
    try:
        row = (
            session.query(Character)
            .join(History, History.character_id == Character.id)
            .order_by(History.timestamp.desc())
            .first()
        )
        if not row:
            return None
        configs = _safe_load_configs(row.configs)
        prompt = str(configs.get("prompt") or "").strip() or _read_yaml_prompt(row.name)
        return {"id": row.id, "name": row.name, "prompt": prompt}
    finally:
        session.close()


def set_active_character_for_user(
    user_uuid: str,
    *,
    character_id: str | None = None,
    char_name: str | None = None,
) -> Optional[dict]:
    if not user_uuid:
        return None

    session: Session = SessionLocal()
    try:
        settings = session.query(UserSettings).filter_by(user_uuid=user_uuid).first()
        if not settings:
            settings = UserSettings(user_uuid=user_uuid)
            session.add(settings)
            session.flush()

        character: Optional[Character] = None
        if character_id:
            character = session.query(Character).filter_by(id=character_id).first()
        elif char_name:
            normalized_name = _normalize_character_name(char_name)
            if normalized_name:
                character = session.query(Character).filter_by(name=normalized_name).first()
                if not character:
                    prompt = _read_yaml_prompt(normalized_name)
                    character = Character(
                        id=str(uuid.uuid4()),
                        name=normalized_name,
                        configs=_safe_dump_configs(
                            {
                                "prompt": prompt,
                                "source": "yaml_sync" if prompt else "db",
                            }
                        ),
                    )
                    session.add(character)
                    session.flush()

        if not character:
            return None

        settings.active_character_id = character.id
        session.commit()

        configs = _safe_load_configs(character.configs)
        prompt = str(configs.get("prompt") or "").strip() or _read_yaml_prompt(character.name)
        return {"id": character.id, "name": character.name, "prompt": prompt}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def resolve_active_character_name_for_user(
    user_uuid: str | None,
    fallback_char_name: str = "default_waifu",
) -> str:
    fallback_name = _normalize_character_name(fallback_char_name) or "default_waifu"
    if not user_uuid:
        recent = get_last_history_character()
        if recent and recent.get("name"):
            return str(recent["name"])
        return fallback_name
    active = get_active_character_for_user(user_uuid)
    if active and active.get("name"):
        return str(active["name"])
    recent = get_last_history_character()
    if recent and recent.get("name"):
        saved = set_active_character_for_user(
            user_uuid,
            character_id=str(recent.get("id") or ""),
        )
        if saved and saved.get("name"):
            return str(saved["name"])
        return str(recent["name"])
    return fallback_name


def get_character_prompt(char_name: str) -> str:
    normalized_name = _normalize_character_name(char_name)
    if not normalized_name:
        return ""

    session: Session = SessionLocal()
    try:
        char = session.query(Character).filter_by(name=normalized_name).first()
        if char:
            configs = _safe_load_configs(char.configs)
            prompt = str(configs.get("prompt") or "").strip()
            if prompt:
                return prompt
    finally:
        session.close()

    yaml_prompt = _read_yaml_prompt(normalized_name)
    if yaml_prompt:
        save_character_prompt(normalized_name, yaml_prompt, source="yaml_sync")
        return yaml_prompt

    if normalized_name != "default":
        return get_character_prompt("default")
    return ""


def save_character_prompt(char_name: str, prompt: str, source: str = "manual") -> None:
    normalized_name = _normalize_character_name(char_name)
    normalized_prompt = (prompt or "").strip()
    if not normalized_name:
        raise ValueError("Character name cannot be empty")
    if not normalized_prompt:
        raise ValueError("Prompt cannot be empty")

    session: Session = SessionLocal()
    try:
        char = session.query(Character).filter_by(name=normalized_name).first()
        if not char:
            char = Character(
                id=str(uuid.uuid4()),
                name=normalized_name,
                configs=_safe_dump_configs({}),
            )
            session.add(char)
            session.flush()

        configs = _safe_load_configs(char.configs)
        configs["prompt"] = normalized_prompt
        configs["source"] = source or "manual"
        char.configs = _safe_dump_configs(configs)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_character_prompt(char_name: str, prompt: str):
    if get_character(_normalize_character_name(char_name)):
        raise ValueError(f"Character {char_name} already exists")
    save_character_prompt(char_name, prompt, source="manual")


def update_character_prompt(char_name: str, prompt: str):
    if not get_character(_normalize_character_name(char_name)):
        raise FileNotFoundError(f"Character '{char_name}' not found")
    save_character_prompt(char_name, prompt, source="manual")


def delete_character_prompt(char_name: str):
    normalized_name = _normalize_character_name(char_name)
    if not normalized_name:
        return
    session: Session = SessionLocal()
    try:
        char = session.query(Character).filter_by(name=normalized_name).first()
        if char:
            session.delete(char)
            session.commit()
    finally:
        session.close()


def import_character_yaml_text(file_name: str, content: str) -> dict:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("YAML content is empty")

    payload = yaml.safe_load(content) or {}
    if not isinstance(payload, dict):
        raise ValueError("YAML root must be an object")

    char_name = _extract_name_from_payload(payload, file_name)
    prompt = _extract_prompt(payload)
    if not prompt:
        raise ValueError("YAML must contain 'prompt' field")

    save_character_prompt(char_name, prompt, source="yaml_import")
    return {"name": char_name, "prompt_length": len(prompt)}


def import_characters_from_yaml_dir(update_existing: bool = False) -> dict:
    if not os.path.isdir(CHARACTERS_DIR):
        return {"imported": 0, "updated": 0, "skipped": 0}

    imported = 0
    updated = 0
    skipped = 0

    for file_name in os.listdir(CHARACTERS_DIR):
        lower = file_name.lower()
        if not lower.endswith(_YAML_EXTS):
            continue
        file_path = os.path.join(CHARACTERS_DIR, file_name)
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                payload = yaml.safe_load(fh) or {}
            if not isinstance(payload, dict):
                skipped += 1
                continue
            char_name = _extract_name_from_payload(payload, file_name)
            prompt = _extract_prompt(payload)
            if not prompt:
                skipped += 1
                continue

            existing = get_character(char_name)
            if existing:
                existing_prompt = _safe_load_configs(existing.configs).get("prompt", "")
                if existing_prompt and not update_existing:
                    skipped += 1
                    continue
                save_character_prompt(char_name, prompt, source="yaml_sync")
                updated += 1
                continue

            save_character_prompt(char_name, prompt, source="yaml_sync")
            imported += 1
        except Exception:
            skipped += 1

    return {"imported": imported, "updated": updated, "skipped": skipped}
