"""Deleting a character archives its data, checks the archive, then removes it.

"Cannot delete" is not an answer. Everything linked
to the character goes into a zip in storage and out of the database; the library
is shared and stays; a character with Telegram messages waits for the Telegram
decision. Runs on a throwaway SQLite file and storage folder.
"""

import json
import zipfile

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from models.models import Character, History, ShortTermMemory, Storage, TelegramMessage, UserSettings
from modules.database import core as database_core
from modules.database.core import Base
from modules.system import character_archive
from modules.system.character_archive import CharacterArchiveError, CharacterDeletionBlocked


@pytest.fixture
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'core.db'}")
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database_core, "engine", engine)
    database_core._ensure_daily_activity_diary_table()

    storage = tmp_path / "storage"
    (storage / "files" / "images").mkdir(parents=True)
    (storage / "files" / "documents").mkdir(parents=True)
    (storage / "files" / "images" / "pic.png").write_bytes(b"png-bytes")
    (storage / "files" / "documents" / "shared.txt").write_bytes(b"library file")
    monkeypatch.setattr(character_archive, "STORAGE_ROOT", storage)
    monkeypatch.setattr(character_archive, "ARCHIVES_DIR", storage / "archives" / "characters")
    monkeypatch.setattr(character_archive, "_visual_profile", lambda name: {"appearance_textarea": f"{name} look"})
    monkeypatch.setattr(character_archive, "_app_version", lambda: "0.9.3-test")
    monkeypatch.setattr(character_archive, "log_audit_entry", lambda *args, **kwargs: None)
    library = []
    monkeypatch.setattr(
        character_archive,
        "_register_in_library",
        lambda path, name: library.append(path) or {"id": "library-1", "name": path.name},
    )

    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add_all(
            [
                Character(id="kate", name="Kate", configs=json.dumps({"prompt": "Kate prompt"})),
                Character(id="lim", name="Lim", configs=json.dumps({"prompt": "Lim prompt"})),
                Character(id="empty", name="default", configs="{}"),
                History(id="k1", character_id="kate", role="user", content="привет"),
                History(id="k2", character_id="kate", role="assistant", content="привет!"),
                History(
                    id="k-library",
                    character_id="kate",
                    role="tool",
                    content="[Library upload] shared.txt",
                    tags='["library_upload"]',
                ),
                History(id="l1", character_id="lim", role="user", content="как дела?"),
                Storage(id="s-kate", message_id="k2", file_name="pic.png", file_path="files/images/pic.png", size=9),
                Storage(
                    id="s-library",
                    message_id="k-library",
                    file_name="shared.txt",
                    file_path="files/documents/shared.txt",
                    size=12,
                ),
                ShortTermMemory(
                    id="st-kate", character_id="kate", summary="Kate day", dialogue_ids=json.dumps(["k1", "k2"])
                ),
                ShortTermMemory(id="st-lim", character_id="lim", summary="Lim day", dialogue_ids=json.dumps(["l1"])),
                UserSettings(id="settings", user_uuid="owner", active_character_id="kate"),
            ]
        )
        session.commit()
    with engine.begin() as conn:
        for row_id, character_id in (("d-kate", "kate"), ("d-lim", "lim")):
            conn.execute(
                text(
                    "INSERT INTO daily_activity_diary (id, character_id, day, created_at, updated_at) "
                    "VALUES (:id, :cid, '2026-09-12', '2026-09-13', '2026-09-13')"
                ),
                {"id": row_id, "cid": character_id},
            )
    yield engine, storage, library, factory
    engine.dispose()


def _ids(engine, sql, **params):
    with engine.connect() as conn:
        return sorted(row[0] for row in conn.execute(text(sql), params))


def test_preview_says_what_goes_into_the_archive(world):
    preview = character_archive.deletion_preview("kate")

    assert preview["character"] == {"id": "kate", "name": "Kate"}
    assert preview["counts"] == {
        "daily_activity_diary": 1,
        "history": 2,
        "short_term_memory": 1,
        "storage": 1,
    }
    assert preview["has_data"] is True
    assert preview["files"] == 1 and preview["files_bytes"] == 9
    assert preview["library_files"] == 1
    assert preview["blocked"] is None


def test_a_character_with_data_is_archived_then_deleted(world):
    engine, storage, library, _factory = world

    result = character_archive.delete_character("kate", user_uuid="owner")

    archive_path = storage / "archives" / "characters" / result["archive"]["file_name"]
    assert archive_path.is_file()
    assert library == [archive_path]
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format"] == "pai-character-archive"
        assert manifest["counts"] == result["counts"]
        assert [row["id"] for row in json.loads(archive.read("tables/history.json"))] == ["k1", "k2"]
        character = json.loads(archive.read("character.json"))
        assert character["prompt"] == "Kate prompt"
        assert character["visual_profile"] == {"appearance_textarea": "Kate look"}
        assert archive.read("files/s-kate/pic.png") == b"png-bytes"

    assert _ids(engine, "SELECT id FROM characters") == ["empty", "lim"]
    assert _ids(engine, "SELECT id FROM history WHERE character_id = 'kate'") == []
    assert _ids(engine, "SELECT id FROM daily_activity_diary") == ["d-lim"]
    assert _ids(engine, "SELECT id FROM short_term_memory") == ["st-lim"]
    assert _ids(engine, "SELECT id FROM storage") == ["s-library"]
    # The library is shared: its file moves to another character and stays.
    assert _ids(engine, "SELECT character_id FROM history WHERE id = 'k-library'") == ["lim"]
    assert (storage / "files" / "documents" / "shared.txt").is_file()
    assert not (storage / "files" / "images" / "pic.png").exists()
    assert _ids(engine, "SELECT COUNT(*) FROM user_settings WHERE active_character_id IS NULL") == [1]
    assert _ids(engine, "SELECT id FROM history WHERE character_id = 'lim'") == ["k-library", "l1"]


def test_a_character_without_data_is_deleted_without_an_archive(world):
    engine, storage, library, _factory = world

    result = character_archive.delete_character("empty")

    assert result["archive"] is None
    assert library == []
    assert not (storage / "archives").exists()
    assert _ids(engine, "SELECT id FROM characters") == ["kate", "lim"]


def test_a_character_with_telegram_messages_waits(world):
    engine, storage, library, factory = world
    with factory() as session:
        session.add(
            TelegramMessage(
                id="tg-1",
                character_id="kate",
                chat_id="chat",
                telegram_chat_id=1,
                telegram_message_id=770,
            )
        )
        session.commit()

    with pytest.raises(CharacterDeletionBlocked) as blocked:
        character_archive.delete_character("kate", user_uuid="owner")

    assert blocked.value.code == "telegram_messages"
    assert character_archive.deletion_preview("kate")["blocked"]["code"] == "telegram_messages"
    assert _ids(engine, "SELECT id FROM characters") == ["empty", "kate", "lim"]
    assert not (storage / "archives").exists()


def test_data_changed_while_archiving_deletes_nothing(world, monkeypatch):
    engine, _storage, _library, factory = world
    verify = character_archive._verify_archive

    def verify_while_she_keeps_talking(path, manifest):
        with factory() as session:
            session.add(History(id="k3", character_id="kate", role="user", content="ещё одно"))
            session.commit()
        verify(path, manifest)

    monkeypatch.setattr(character_archive, "_verify_archive", verify_while_she_keeps_talking)

    with pytest.raises(CharacterDeletionBlocked) as blocked:
        character_archive.delete_character("kate", user_uuid="owner")

    assert blocked.value.code == "changed_during_archiving"
    assert _ids(engine, "SELECT id FROM history WHERE character_id = 'kate'") == ["k-library", "k1", "k2", "k3"]
    assert _ids(engine, "SELECT id FROM characters") == ["empty", "kate", "lim"]


def test_a_failed_archive_deletes_nothing(world, monkeypatch):
    engine, storage, _library, _factory = world

    def broken(path, manifest):
        raise CharacterArchiveError("checksum mismatch: tables/history.json")

    monkeypatch.setattr(character_archive, "_verify_archive", broken)

    with pytest.raises(CharacterArchiveError):
        character_archive.delete_character("kate", user_uuid="owner")

    assert _ids(engine, "SELECT id FROM history WHERE character_id = 'kate'") == ["k-library", "k1", "k2"]
    assert (storage / "files" / "images" / "pic.png").is_file()
