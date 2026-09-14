"""PAI starts on an empty storage tree, the way a fresh install does.

When something is removed, the system still has to come up from zero. Each run is a separate process on its own empty PAI_STORAGE_DIR (paths are
read once at import), so the live database is never touched.

Two things of a real start are replaced: the vision service (were background
screen capture on, it would download a YOLO model and capture the screen) and the
generation presets file (it lives next to the code, outside the storage tree).
"""

import copy
import json
import os
import subprocess
import sys

import pytest

from constants.default_config import DEFAULT_CONFIG

pytestmark = pytest.mark.regression

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Technical prompts a fresh owner config must already carry. A prompt moved into
# the config goes on this list.
TECHNICAL_PROMPTS = (
    "decision_layer.instructor.build_schema",
    "analyzer.system_prompt",
    "moral.system_prompt",
    "synthesis.image_check.describe_prompt",
    "synthesis.image_check.system_prompt",
    "synthesis.image_check.user_template",
    "synthesis.image_scene.format_prompt",
    "synthesis.prompting.image_prompt_builder_system_prompt",
    "synthesis.prompting.image_prompt_builder_user_template",
    "validator.system_prompt",
    "confidence.system_prompt",
    "self_watcher.reflection_prompt",
    "memory.consolidation.judge.system_prompt",
    "memory.short_term.summary_system_prompt",
    "memory.short_term.summary_task_prompt",
    "memory.diary.system_prompt",
    "memory.diary.user_template",
    "moral.inner_voice.system_prompt",
    "decision_layer.orchestrator_prompt",
    "vision.attachment_prompt",
    "vision.generated_image_prompt",
    "vision.screen_prompt",
)

_RESULT_MARK = "@@RESULT@@"

_PRELUDE = r'''
import json
import os
import sys

sys.path.insert(0, os.getcwd())
storage = os.environ["PAI_STORAGE_DIR"]

import modules.vision.service as vision_module


class _NoVision:
    starts = 0

    def start(self):
        _NoVision.starts += 1

    def stop(self):
        pass


vision_module.VisionService = _NoVision

from modules.system import preset

preset.PRESET_PATH = os.path.join(storage, "generation_presets.json")


def report(data):
    print("@@RESULT@@" + json.dumps(data, ensure_ascii=False, default=str))
'''

_FIRST_START = _PRELUDE + r'''
from sqlalchemy import inspect

from core.initialize import run_startup_checks


def snapshot():
    from models.models import Base, Character, User, UserConfig
    from modules.database.core import DB_PATH, SessionLocal, engine

    session = SessionLocal()
    try:
        return {
            "db_path": DB_PATH,
            "tables": sorted(inspect(engine).get_table_names()),
            "model_tables": sorted(Base.metadata.tables),
            "characters": sorted(row.name for row in session.query(Character).all()),
            "users": sorted([row.email, row.role] for row in session.query(User).all()),
            "configs": sorted(row.user_uuid for row in session.query(UserConfig).all()),
        }
    finally:
        session.close()


run_startup_checks()
first = snapshot()

from modules.system import auth
from modules.system import config as config_service
from modules.system.service import get_active_character_name

active_character = get_active_character_name()
before = auth.get_auth_bootstrap_state()
first_user = auth.register_user(
    email="first@zero.test", password="zero-pass-123", login="first", role="user"
)
second_user = auth.register_user(
    email="second@zero.test", password="zero-pass-123", login="second", role="owner"
)
after = auth.get_auth_bootstrap_state()
owner_config = config_service.ensure_user_config_exists(first_user.user.uuid)

run_startup_checks()
restarted = snapshot()

report({
    "storage": storage,
    "presets_file": os.path.exists(preset.PRESET_PATH),
    "vision_starts": _NoVision.starts,
    "first": first,
    "active_character": active_character,
    "before": before,
    "first_user": {"uuid": first_user.user.uuid, "role": first_user.user.role},
    "second_user": {"uuid": second_user.user.uuid, "role": second_user.user.role},
    "after": after,
    "owner_config": owner_config,
    "restarted": restarted,
    "owner_config_after_restart": config_service.ensure_user_config_exists(first_user.user.uuid),
})
'''

_BACKEND = _PRELUDE + r'''
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)
ping = client.get("/api/ping")
state = client.get("/api/auth/bootstrap-state")
report({
    "ping": [ping.status_code, ping.json()],
    "state": [state.status_code, state.json()],
})
'''


def _run(script, storage):
    env = {key: value for key, value in os.environ.items() if key != "PAI_STORAGE_DIR"}
    env["PAI_STORAGE_DIR"] = str(storage)
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    results = [line for line in completed.stdout.splitlines() if line.startswith(_RESULT_MARK)]
    assert completed.returncode == 0 and results, (
        f"exit {completed.returncode}\n{completed.stdout[-4000:]}\n{completed.stderr[-4000:]}"
    )
    return json.loads(results[-1][len(_RESULT_MARK):])


def _key_paths(tree, prefix=""):
    paths = set()
    for key, value in tree.items():
        path = f"{prefix}.{key}" if prefix else key
        paths.add(path)
        if isinstance(value, dict):
            paths |= _key_paths(value, path)
    return paths


def _value(tree, path):
    for part in path.split("."):
        tree = tree[part]
    return tree


@pytest.fixture(scope="module")
def fresh_start(tmp_path_factory):
    return _run(_FIRST_START, tmp_path_factory.mktemp("zero"))


def test_first_start_on_empty_storage_builds_the_whole_schema(fresh_start):
    first = fresh_start["first"]
    storage = os.path.abspath(fresh_start["storage"])

    assert os.path.abspath(first["db_path"]).startswith(storage)
    assert sorted(set(first["model_tables"]) - set(first["tables"])) == []
    assert first["users"] == []
    assert fresh_start["presets_file"] is True


def test_first_start_has_a_character_to_talk_to(fresh_start):
    characters = fresh_start["first"]["characters"]

    # config/characters/default.yaml ships with the code.
    assert "default" in characters
    assert fresh_start["active_character"] in characters


def test_before_registration_there_is_no_owner(fresh_start):
    before = fresh_start["before"]

    assert before["has_owner"] is False
    assert before["requires_setup"] is True
    assert before["first_registration_role"] == "owner"


def test_first_registration_is_the_owner_and_the_second_is_not(fresh_start):
    assert fresh_start["first_user"]["role"] == "owner"
    assert fresh_start["second_user"]["role"] == "user"
    assert fresh_start["after"]["has_owner"] is True
    assert fresh_start["after"]["requires_setup"] is False


def test_every_registered_account_gets_its_config(fresh_start):
    configs = fresh_start["restarted"]["configs"]

    assert fresh_start["first_user"]["uuid"] in configs
    assert fresh_start["second_user"]["uuid"] in configs


def test_owner_config_keeps_every_default_key(fresh_start):
    lost = _key_paths(DEFAULT_CONFIG) - _key_paths(fresh_start["owner_config"])

    assert sorted(lost) == []


@pytest.mark.parametrize("path", TECHNICAL_PROMPTS)
def test_owner_config_carries_the_technical_prompt(fresh_start, path):
    value = _value(fresh_start["owner_config"], path)

    assert isinstance(value, str) and value.strip()
    assert value == _value(copy.deepcopy(DEFAULT_CONFIG), path)


def test_restart_changes_nothing(fresh_start):
    first = fresh_start["first"]
    restarted = fresh_start["restarted"]

    assert restarted["tables"] == first["tables"]
    assert restarted["characters"] == first["characters"]
    assert [email for email, _role in restarted["users"]] == ["first@zero.test", "second@zero.test"]
    assert fresh_start["owner_config_after_restart"] == fresh_start["owner_config"]


def test_fresh_start_sees_pictures_but_does_not_capture_the_screen(fresh_start):
    vision = fresh_start["owner_config"]["vision"]

    assert fresh_start["vision_starts"] == 0
    assert vision["enabled"] is True
    assert vision["screen_capture_enabled"] is False


def test_fresh_start_does_not_write_first(fresh_start):
    assert fresh_start["owner_config"]["initiative"]["enabled"] is False


def test_backend_answers_on_empty_storage(tmp_path):
    result = _run(_BACKEND, tmp_path)

    assert result["ping"] == [200, {"message": "pong"}]
    status, state = result["state"]
    assert status == 200
    assert state["has_owner"] is False
    assert state["requires_setup"] is True
