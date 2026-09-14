"""The character delete route: owner only, and it says plainly why it waits.

Deleting a character is a system action, the owner's alone. The
route used to answer 409 "Cannot delete character with chat history" to anyone
logged in and wrote nothing to the log; the work is in character_archive.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from core.interaction import InteractionPolicy
from modules.system.character_archive import CharacterDeletionBlocked
from routes import config_routes


def _as(monkeypatch, role):
    monkeypatch.setattr(config_routes, "_require_user_uuid", lambda request: "someone")
    monkeypatch.setattr(
        config_routes,
        "resolve_interaction_policy",
        lambda uuid: InteractionPolicy(
            actor_role=role,
            can_affect_moral=role == "owner",
            can_affect_global_memory=role == "owner",
        ),
    )


@pytest.mark.parametrize("role", ["user", "anonymous"])
def test_only_the_owner_deletes_or_previews(monkeypatch, role):
    _as(monkeypatch, role)
    touched = []
    monkeypatch.setattr(config_routes, "delete_character", lambda *args, **kwargs: touched.append(args))
    monkeypatch.setattr(config_routes, "deletion_preview", lambda *args, **kwargs: touched.append(args))

    for call in (
        lambda: config_routes.delete_system_character("kate", SimpleNamespace()),
        lambda: config_routes.get_character_deletion_preview("kate", SimpleNamespace()),
    ):
        with pytest.raises(HTTPException) as refused:
            call()
        assert refused.value.status_code == 403

    assert touched == []


def test_a_postponed_deletion_says_why(monkeypatch):
    _as(monkeypatch, "owner")
    monkeypatch.setattr(config_routes, "get_active_character_for_user", lambda uuid: None)

    def blocked(character_id, user_uuid=None):
        raise CharacterDeletionBlocked("telegram_messages", "The character has Telegram messages.")

    monkeypatch.setattr(config_routes, "delete_character", blocked)

    with pytest.raises(HTTPException) as refused:
        config_routes.delete_system_character("lim", SimpleNamespace())

    assert refused.value.status_code == 409
    assert refused.value.detail == "The character has Telegram messages."


def test_the_owner_gets_the_archive_back(monkeypatch):
    _as(monkeypatch, "owner")
    monkeypatch.setattr(config_routes, "get_active_character_for_user", lambda uuid: {"id": "lim", "name": "Lim"})
    monkeypatch.setattr(config_routes, "list_characters", lambda sync_from_yaml=True: [{"id": "lim", "name": "Lim"}])
    monkeypatch.setattr(
        config_routes,
        "delete_character",
        lambda character_id, user_uuid=None: {
            "id": "kate",
            "name": "Kate",
            "counts": {"history": 2},
            "archive": {"file_name": "Kate_20260913-230000.zip"},
        },
    )

    response = config_routes.delete_system_character("kate", SimpleNamespace())

    assert response["deleted"] == {"id": "kate", "name": "Kate"}
    assert response["archive"] == {"file_name": "Kate_20260913-230000.zip"}
    assert response["active_char_name"] == "Lim"
