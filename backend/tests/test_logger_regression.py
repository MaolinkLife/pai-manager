from pathlib import Path

import pytest

from modules.system import logger


pytestmark = pytest.mark.regression


def test_traceback_log_path_is_in_root_logs():
    trace_path = Path(logger.TRACEBACK_FILE).resolve()
    assert trace_path.name == "runtime_tracebacks.log"
    assert "temp" not in {part.lower() for part in trace_path.parts}
    assert "logs" in {part.lower() for part in trace_path.parts}
    assert "backend" not in {part.lower() for part in trace_path.parts}


def test_debug_log_path_stays_inside_backend_logs():
    debug_path = Path(logger.DEBUG_FILE_CURRENT).resolve()
    lowered_parts = {part.lower() for part in debug_path.parts}
    assert debug_path.name == "debug_log.jsonl"
    assert "backend" in lowered_parts


def test_log_error_writes_runtime_traceback_file(tmp_path, monkeypatch):
    log_file = tmp_path / "runtime_tracebacks.log"
    monkeypatch.setattr(logger, "TRACEBACK_FILE", str(log_file))

    logger.log_error("boom", context={"step": "startup"}, severity="critical")

    content = log_file.read_text(encoding="utf-8")
    assert "ERROR: boom" in content
    assert "Context: {'step': 'startup'}" in content
