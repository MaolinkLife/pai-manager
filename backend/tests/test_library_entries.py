"""Library entries: an upload is copied in; a file already in storage is registered in place.

A character archive is written into storage and put into the library without a
second copy. Both paths share one way of creating the entry: a
service history row of the active character carries the file.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from models.models import Character
from modules.database.core import Base
from modules.storage import service as storage_service
from modules.system import character as character_module
from modules.system import service as system_service


@pytest.fixture
def library(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'core.db'}")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(Character(id="lim", name="Lim"))
        session.commit()
    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setattr(storage_service, "SessionLocal", factory)
    monkeypatch.setattr(storage_service, "STORAGE_DIR", str(storage))
    monkeypatch.setattr(storage_service, "FILES_ROOT", storage / "files")
    monkeypatch.setattr(storage_service, "signed_media_url", lambda media_id, now=None: f"/media/{media_id}")
    monkeypatch.setattr(system_service, "get_active_character_name", lambda default=None: "Lim")
    monkeypatch.setattr(character_module, "get_or_create_character", lambda name: SimpleNamespace(id="lim"))
    yield engine, storage
    engine.dispose()


def test_an_upload_is_copied_into_the_library(library):
    engine, storage = library

    uploaded = storage_service.save_library_file(file_name="notes.txt", mime_type="text/plain", file_bytes=b"hello")

    assert uploaded["size"] == 5 and uploaded["exists"] is True
    with engine.connect() as conn:
        row = conn.execute(text("SELECT file_path FROM storage WHERE id = :id"), {"id": uploaded["id"]}).fetchone()
        owner = conn.execute(
            text("SELECT h.character_id, h.role, h.tags FROM storage s JOIN history h ON h.id = s.message_id")
        ).fetchone()
    assert (storage / row[0]).read_bytes() == b"hello"
    assert tuple(owner) == ("lim", "tool", '["library_upload"]')


def test_a_file_in_storage_is_registered_without_a_copy(library):
    engine, storage = library
    archive = storage / "archives" / "characters" / "Kate_20260913-230000.zip"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"zip-bytes")

    registered = storage_service.register_library_path(
        file_path=archive,
        file_name=archive.name,
        mime_type="application/zip",
        description="Archive of character Kate",
    )

    assert registered["size"] == len(b"zip-bytes")
    assert registered["exists"] is True
    assert registered["description"] == "Archive of character Kate"
    with engine.connect() as conn:
        paths = [row[0] for row in conn.execute(text("SELECT file_path FROM storage"))]
    assert paths == ["archives/characters/Kate_20260913-230000.zip"]
    assert not (storage / "files").exists()


def test_a_file_outside_storage_is_refused(library, tmp_path):
    outside = tmp_path / "outside.zip"
    outside.write_bytes(b"zip-bytes")

    with pytest.raises(HTTPException) as refused:
        storage_service.register_library_path(file_path=outside, file_name=outside.name, mime_type="application/zip")

    assert refused.value.status_code == 400
