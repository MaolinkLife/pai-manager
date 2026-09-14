from pathlib import Path

import pytest

from constants.paths import LOGS_DIR, TRACEBACK_LOGS_DIR
from modules.system import logger


pytestmark = pytest.mark.regression

# The logger must write where constants.paths points. Which folders those are
# (root logs / backend logs for the live backend, the PAI_STORAGE_DIR tree for a
# test run) is checked in test_storage_override_paths.py.


def test_traceback_log_path_is_in_root_logs():
    trace_path = Path(logger.TRACEBACK_FILE).resolve()
    assert trace_path.name == "runtime_tracebacks.log"
    assert trace_path.parent == Path(TRACEBACK_LOGS_DIR).resolve()


def test_debug_log_path_stays_inside_backend_logs():
    debug_path = Path(logger.DEBUG_FILE_CURRENT).resolve()
    assert debug_path.name == "debug_log.jsonl"
    assert debug_path.parent == Path(LOGS_DIR).resolve()


def test_log_error_writes_runtime_traceback_file(tmp_path, monkeypatch):
    log_file = tmp_path / "runtime_tracebacks.log"
    monkeypatch.setattr(logger, "TRACEBACK_FILE", str(log_file))

    logger.log_error("boom", context={"step": "startup"}, severity="critical")

    content = log_file.read_text(encoding="utf-8")
    assert "ERROR: boom" in content
    assert "Context: {'step': 'startup'}" in content
