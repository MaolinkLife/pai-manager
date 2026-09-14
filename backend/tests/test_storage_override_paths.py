"""PAI_STORAGE_DIR moves everything a test run writes, logs included.

Paths are read once at import, so each case imports them in a fresh process.
"""

import json
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.regression

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.dirname(BACKEND_DIR)

_PROBE = (
    "import json; from constants import paths; "
    "print(json.dumps({'storage': paths.STORAGE_DIR, 'logs': paths.LOGS_DIR, "
    "'tracebacks': paths.TRACEBACK_LOGS_DIR}))"
)


def _paths(override):
    env = {key: value for key, value in os.environ.items() if key != "PAI_STORAGE_DIR"}
    if override:
        env["PAI_STORAGE_DIR"] = override
    output = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return {key: os.path.abspath(value) for key, value in json.loads(output).items()}


def test_override_moves_storage_and_both_log_folders(tmp_path):
    override = os.path.abspath(str(tmp_path))
    paths = _paths(override)
    assert paths["storage"] == override
    assert paths["logs"].startswith(override)
    assert paths["tracebacks"].startswith(override)


def test_without_override_logs_stay_where_the_live_backend_writes_them():
    paths = _paths(None)
    assert paths["storage"] == os.path.join(BACKEND_DIR, "storage")
    assert paths["logs"] == os.path.join(BACKEND_DIR, "logs")
    assert paths["tracebacks"] == os.path.join(PROJECT_DIR, "logs")
