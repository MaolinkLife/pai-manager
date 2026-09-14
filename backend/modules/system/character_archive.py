"""Deleting a character: its data goes into a checked zip archive, then out of the database.

"Cannot delete" is not an answer. A character with
data is archived into storage — one JSON file per table, the message files, the
character row with its prompt and visual profile, a manifest with counts and
checksums. The archive is checked, and only then every linked row leaves the
database in one transaction. The archive lands in the library to be downloaded;
importing it back is for later.

Telegram is postponed: a character with Telegram messages is not deleted until it
is decided how Telegram messages map to characters. The
library is shared: its files hang on a service history row of whoever was active
at upload, so those rows move to another character instead of leaving.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import inspect, text

from constants.paths import STORAGE_DIR
from modules.database import core as database_core
from modules.system.logger import AuditStatus, log_audit_entry

ARCHIVE_FORMAT = "pai-character-archive"
ARCHIVE_FORMAT_VERSION = 1
STORAGE_ROOT = Path(STORAGE_DIR)
ARCHIVES_DIR = STORAGE_ROOT / "archives" / "characters"

TELEGRAM_TABLES = ("telegram_messages", "telegram_sync_jobs")
TELEGRAM_BLOCK_MESSAGE = (
    "The character has Telegram messages. Deleting such a character waits for the "
    "decision on how Telegram messages map to characters."
)
CHANGED_MESSAGE = (
    "The character's data changed while the archive was being written. Nothing was "
    "deleted; try again."
)
# A library upload is a service history row. The library is shared: it stays.
_LIBRARY_ROW = "(role = 'tool' AND COALESCE(tags, '') LIKE '%library_upload%')"


class CharacterDeletionBlocked(Exception):
    """The character is not deleted; `code` says why."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class CharacterArchiveError(Exception):
    """The archive could not be written or failed its check; nothing was deleted."""


# ---------------------------------------------------------------------------
# What belongs to a character
# ---------------------------------------------------------------------------


def _rows(conn, sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [dict(row._mapping) for row in conn.execute(text(sql), params)]


def _selectors(conn, character_id: str) -> List[Tuple[str, str, Dict[str, Any]]]:
    """(table, WHERE clause, params) for every row that belongs to the character.

    Rows linked through the character's messages come before the messages
    themselves, so deleting in this order never loses a link a later clause needs.
    """
    inspector = inspect(conn)
    names = set(inspector.get_table_names())
    params = {"cid": character_id}
    own_messages = f"SELECT id FROM history WHERE character_id = :cid AND NOT {_LIBRARY_ROW}"
    selectors: List[Tuple[str, str, Dict[str, Any]]] = []
    for table in ("reasoning", "storage"):
        if table in names and "history" in names:
            selectors.append((table, f"message_id IN ({own_messages})", params))
    if {"imported_artifacts", "imported_archives"} <= names:
        selectors.append(
            (
                "imported_artifacts",
                "archive_id IN (SELECT id FROM imported_archives WHERE character_id = :cid)",
                params,
            )
        )
    character_tables = sorted(
        table
        for table in names
        if table not in ("characters", "history")
        and any(column["name"] == "character_id" for column in inspector.get_columns(table))
    )
    for table in character_tables:
        selectors.append((table, "character_id = :cid", params))
    if "history" in names:
        selectors.append(("history", f"character_id = :cid AND NOT {_LIBRARY_ROW}", params))
    return selectors


def _collect(conn, character_id: str) -> Dict[str, List[Dict[str, Any]]]:
    return {
        table: _rows(conn, f"SELECT * FROM {table} WHERE {where}", params)
        for table, where, params in _selectors(conn, character_id)
    }


def _count(conn, character_id: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for table, where, params in _selectors(conn, character_id):
        count = int(conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {where}"), params).scalar() or 0)
        if count:
            counts[table] = count
    return counts


def _character_row(conn, character_id: str) -> Optional[Dict[str, Any]]:
    rows = _rows(conn, "SELECT * FROM characters WHERE id = :cid", {"cid": character_id})
    return rows[0] if rows else None


def _library_rows(conn, character_id: str) -> int:
    return int(
        conn.execute(
            text(f"SELECT COUNT(*) FROM history WHERE character_id = :cid AND {_LIBRARY_ROW}"),
            {"cid": character_id},
        ).scalar()
        or 0
    )


def _telegram_rows(counts: Dict[str, int]) -> int:
    return sum(counts.get(table, 0) for table in TELEGRAM_TABLES)


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def deletion_preview(character_id: str) -> Dict[str, Any]:
    """What deleting the character would archive and remove."""
    with database_core.engine.connect() as conn:
        character = _character_row(conn, character_id)
        if not character:
            raise FileNotFoundError("Character not found")
        counts = _count(conn, character_id)
        files_bytes = 0
        if counts.get("storage"):
            files_bytes = int(
                conn.execute(
                    text(
                        "SELECT COALESCE(SUM(size), 0) FROM storage WHERE message_id IN "
                        f"(SELECT id FROM history WHERE character_id = :cid AND NOT {_LIBRARY_ROW})"
                    ),
                    {"cid": character_id},
                ).scalar()
                or 0
            )
        library_files = _library_rows(conn, character_id)
    blocked = None
    if _telegram_rows(counts):
        blocked = {"code": "telegram_messages", "message": TELEGRAM_BLOCK_MESSAGE}
    return {
        "character": {"id": character.get("id"), "name": character.get("name")},
        "counts": counts,
        "has_data": bool(counts),
        "files": counts.get("storage", 0),
        "files_bytes": files_bytes,
        "library_files": library_files,
        "blocked": blocked,
    }


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def delete_character(character_id: str, *, user_uuid: Optional[str] = None) -> Dict[str, Any]:
    """Archive the character's data, check the archive, then delete it all.

    Raises FileNotFoundError, CharacterDeletionBlocked (Telegram messages, or the
    data changed while archiving) or CharacterArchiveError. In every raising case
    the database is left as it was.
    """
    with database_core.engine.connect() as conn:
        character = _character_row(conn, character_id)
        if not character:
            raise FileNotFoundError("Character not found")
        tables = _collect(conn, character_id)
    name = str(character.get("name") or character_id)
    counts = {table: len(rows) for table, rows in tables.items() if rows}

    telegram_rows = _telegram_rows(counts)
    if telegram_rows:
        log_audit_entry(
            "character_delete_blocked",
            "[Characters] Deletion postponed: the character has Telegram messages.",
            AuditStatus.WARNING,
            details={"character": name, "character_id": character_id, "telegram_rows": telegram_rows},
        )
        raise CharacterDeletionBlocked("telegram_messages", TELEGRAM_BLOCK_MESSAGE)

    archive_path: Optional[Path] = None
    if counts:
        archive_path = _archive_path(name)
        try:
            manifest = _write_archive(archive_path, character, tables)
            _verify_archive(archive_path, manifest)
        except Exception as exc:
            log_audit_entry(
                "character_archive_failed",
                "[Characters] Character archive failed; nothing was deleted.",
                AuditStatus.ERROR,
                details={"character": name, "archive": str(archive_path), "error": str(exc)},
            )
            raise CharacterArchiveError(str(exc)) from exc

    try:
        _delete_rows(character_id, counts, user_uuid=user_uuid)
    except CharacterDeletionBlocked as exc:
        log_audit_entry(
            "character_delete_blocked",
            "[Characters] Deletion aborted: the data changed while archiving.",
            AuditStatus.WARNING,
            details={
                "character": name,
                "code": exc.code,
                "archive": str(archive_path) if archive_path else None,
            },
        )
        raise

    removed_files = _remove_media_files(tables.get("storage", []))
    archive_info = None
    if archive_path is not None:
        archive_info = {
            "file_name": archive_path.name,
            "path": str(archive_path),
            "size": archive_path.stat().st_size,
            "library_item": _register_in_library(archive_path, name),
        }
    log_audit_entry(
        "character_deleted",
        "[Characters] Character deleted" + (" into an archive." if archive_info else "."),
        AuditStatus.SUCCESS,
        details={
            "character": name,
            "character_id": character_id,
            "counts": counts,
            "archive": archive_info["path"] if archive_info else None,
            "removed_files": removed_files,
        },
    )
    return {"id": character_id, "name": name, "counts": counts, "archive": archive_info}


def _delete_rows(character_id: str, expected: Dict[str, int], *, user_uuid: Optional[str]) -> None:
    with database_core.engine.begin() as conn:
        if _count(conn, character_id) != expected:
            raise CharacterDeletionBlocked("changed_during_archiving", CHANGED_MESSAGE)
        target = _library_owner(conn, character_id, user_uuid)
        if target:
            conn.execute(
                text(f"UPDATE history SET character_id = :target WHERE character_id = :cid AND {_LIBRARY_ROW}"),
                {"target": target, "cid": character_id},
            )
        for table, where, params in _selectors(conn, character_id):
            conn.execute(text(f"DELETE FROM {table} WHERE {where}"), params)
        if "user_settings" in set(inspect(conn).get_table_names()):
            conn.execute(
                text("UPDATE user_settings SET active_character_id = NULL WHERE active_character_id = :cid"),
                {"cid": character_id},
            )
        conn.execute(text("DELETE FROM characters WHERE id = :cid"), {"cid": character_id})


def _library_owner(conn, character_id: str, user_uuid: Optional[str]) -> Optional[str]:
    """Another character to carry the library files the deleted one was holding."""
    if not _library_rows(conn, character_id):
        return None
    if user_uuid:
        row = conn.execute(
            text("SELECT active_character_id FROM user_settings WHERE user_uuid = :uuid"),
            {"uuid": user_uuid},
        ).fetchone()
        if row and row[0] and row[0] != character_id:
            return str(row[0])
    row = conn.execute(
        text("SELECT id FROM characters WHERE id != :cid ORDER BY name LIMIT 1"),
        {"cid": character_id},
    ).fetchone()
    if row:
        return str(row[0])
    new_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    conn.execute(
        text(
            "INSERT INTO characters (id, name, configs, created_at, updated_at) "
            "VALUES (:id, 'default', '{}', :now, :now)"
        ),
        {"id": new_id, "now": now},
    )
    return new_id


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return {"base64": base64.b64encode(bytes(value)).decode("ascii")}
    return str(value)


def _dumps(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=1, default=_json_default).encode("utf-8")


def _json_object(raw: Any) -> Dict[str, Any]:
    try:
        value = json.loads(raw or "{}") if isinstance(raw, str) else raw
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _inside_storage(relative_path: Any) -> Optional[Path]:
    candidate = (STORAGE_ROOT / str(relative_path or "")).resolve()
    root = STORAGE_ROOT.resolve()
    return candidate if candidate != root and candidate.is_relative_to(root) else None


def _archive_path(name: str) -> Path:
    safe = re.sub(r"[^\w.-]+", "_", name).strip("_") or "character"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = ARCHIVES_DIR / f"{safe}_{stamp}.zip"
    if path.exists():
        path = ARCHIVES_DIR / f"{safe}_{stamp}_{uuid.uuid4().hex[:6]}.zip"
    return path


def _visual_profile(character_name: str) -> Optional[Dict[str, Any]]:
    try:
        from modules.system import config as config_service

        prompting = config_service.get_config_value("synthesis.prompting", {}) or {}
        profiles = prompting.get("per_character_visual_profiles") if isinstance(prompting, dict) else None
        profile = profiles.get(character_name) if isinstance(profiles, dict) else None
        return profile if isinstance(profile, dict) else None
    except Exception:
        return None


def _app_version() -> str:
    try:
        from modules.system.updater import read_local_version

        return str(read_local_version() or "")
    except Exception:
        return ""


def _write_archive(
    path: Path,
    character: Dict[str, Any],
    tables: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    checksums: Dict[str, str] = {}
    missing_files: List[str] = []
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:

        def put(arcname: str, data: bytes) -> None:
            archive.writestr(arcname, data)
            checksums[arcname] = hashlib.sha256(data).hexdigest()

        configs = _json_object(character.get("configs"))
        put(
            "character.json",
            _dumps(
                {
                    "row": character,
                    "prompt": str(configs.get("prompt") or ""),
                    "visual_profile": _visual_profile(str(character.get("name") or "")),
                }
            ),
        )
        for table, rows in tables.items():
            if rows:
                put(f"tables/{table}.json", _dumps(rows))
        for row in tables.get("storage", []):
            source = _inside_storage(row.get("file_path"))
            file_name = Path(str(row.get("file_name") or "file")).name
            if source is not None and source.is_file():
                put(f"files/{row['id']}/{file_name}", source.read_bytes())
            else:
                missing_files.append(str(row.get("file_path") or ""))
        manifest = {
            "format": ARCHIVE_FORMAT,
            "format_version": ARCHIVE_FORMAT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "app_version": _app_version(),
            "character": {"id": character.get("id"), "name": character.get("name")},
            "counts": {table: len(rows) for table, rows in tables.items() if rows},
            "checksums": checksums,
            "missing_files": missing_files,
        }
        archive.writestr("manifest.json", _dumps(manifest))
    return manifest


def _verify_archive(path: Path, manifest: Dict[str, Any]) -> None:
    with zipfile.ZipFile(path) as archive:
        damaged = archive.testzip()
        if damaged is not None:
            raise CharacterArchiveError(f"archive entry is damaged: {damaged}")
        stored = json.loads(archive.read("manifest.json"))
        if stored.get("counts") != manifest["counts"] or stored.get("checksums") != manifest["checksums"]:
            raise CharacterArchiveError("the archive manifest does not match what was written")
        for arcname, digest in stored["checksums"].items():
            if hashlib.sha256(archive.read(arcname)).hexdigest() != digest:
                raise CharacterArchiveError(f"checksum mismatch: {arcname}")
        for table, count in stored["counts"].items():
            if len(json.loads(archive.read(f"tables/{table}.json"))) != count:
                raise CharacterArchiveError(f"row count mismatch: {table}")


def _remove_media_files(rows: List[Dict[str, Any]]) -> int:
    """The archived message files leave the disk once their rows are gone."""
    removed = 0
    for row in rows:
        source = _inside_storage(row.get("file_path"))
        if source is None or not source.is_file():
            continue
        try:
            source.unlink()
            removed += 1
        except OSError as exc:
            log_audit_entry(
                "character_media_file_left",
                "[Characters] An archived message file could not be removed from disk.",
                AuditStatus.WARNING,
                details={"file_path": str(row.get("file_path")), "error": str(exc)},
            )
    return removed


def _register_in_library(path: Path, character_name: str) -> Optional[Dict[str, Any]]:
    try:
        from modules.storage.service import register_library_path

        return register_library_path(
            file_path=path,
            file_name=path.name,
            mime_type="application/zip",
            description=f"Archive of character {character_name}",
        )
    except Exception as exc:
        log_audit_entry(
            "character_archive_library_failed",
            "[Characters] The archive is on disk but could not be added to the library.",
            AuditStatus.WARNING,
            details={"archive": str(path), "error": str(exc)},
        )
        return None
