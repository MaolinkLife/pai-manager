from pathlib import Path

import pytest

from constants.paths import BASE_DIR, PROJECT_DIR
from modules.system import logger


pytestmark = pytest.mark.regression

# Compare resolved paths instead of looking for the literal "backend" among the
# path parts: that made both tests depend on the working directory pytest was
# started from and on the checkout directory being named "backend".
BACKEND_LOGS = (Path(BASE_DIR) / "logs").resolve()
ROOT_LOGS = (Path(PROJECT_DIR) / "logs").resolve()


def test_traceback_log_path_is_in_root_logs():
    trace_path = Path(logger.TRACEBACK_FILE).resolve()
    assert trace_path.name == "runtime_tracebacks.log"
    assert trace_path.parent == ROOT_LOGS
    assert trace_path.parent != BACKEND_LOGS


def test_debug_log_path_stays_inside_backend_logs():
    debug_path = Path(logger.DEBUG_FILE_CURRENT).resolve()
    assert debug_path.name == "debug_log.jsonl"
    assert debug_path.parent == BACKEND_LOGS
    assert debug_path.parent != ROOT_LOGS


def test_log_error_writes_runtime_traceback_file(tmp_path, monkeypatch):
    log_file = tmp_path / "runtime_tracebacks.log"
    monkeypatch.setattr(logger, "TRACEBACK_FILE", str(log_file))

    logger.log_error("boom", context={"step": "startup"}, severity="critical")

    content = log_file.read_text(encoding="utf-8")
    assert "ERROR: boom" in content
    assert "Context: {'step': 'startup'}" in content
