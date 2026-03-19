from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Sequence

from modules.tts.paths import project_root


class FFmpegError(RuntimeError):
    pass


def _binary_names(base_name: str) -> list[str]:
    if os.name == "nt":
        return [f"{base_name}.exe", base_name]
    return [base_name]


def _ffmpeg_roots() -> list[Path]:
    root = project_root() / "tools" / "ffmpeg"
    return [root, root / "bin"]


def find_binary(base_name: str) -> Path | None:
    for directory in _ffmpeg_roots():
        for candidate_name in _binary_names(base_name):
            candidate = directory / candidate_name
            if candidate.exists() and candidate.is_file():
                return candidate
    return None


def require_binary(base_name: str) -> Path:
    binary = find_binary(base_name)
    if binary is None:
        raise FFmpegError(
            f"Local {base_name} binary not found. Expected it in tools/ffmpeg or tools/ffmpeg/bin."
        )
    return binary


def run_binary(base_name: str, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    binary = require_binary(base_name)
    completed = subprocess.run(
        [str(binary), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        raise FFmpegError(stderr or f"{base_name} exited with code {completed.returncode}")
    return completed


def probe_audio(file_path: str | Path) -> dict[str, Any]:
    completed = run_binary(
        "ffprobe",
        [
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(file_path),
        ],
    )
    try:
        return json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise FFmpegError(f"Failed to parse ffprobe output for {file_path}") from exc

