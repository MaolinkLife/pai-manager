"""Path and URL helpers for the llama.cpp transport layer.

Intentionally smaller than the AI_WAIFU_Y original — the GGUF metadata parser
and bundle scanner have been left out for now. They are only needed by an
embedded "pick your model from a folder" UI, which is not part of this phase.
Re-introduce them when the embedded launcher gains a model picker.
"""

from __future__ import annotations

import os

from constants.paths import PROJECT_DIR


def project_path(path: str) -> str:
    """Resolve a project-relative path to an absolute one, leaving absolute paths intact."""
    text = str(path or "").strip()
    if not text:
        return ""
    if os.path.isabs(text):
        return os.path.abspath(text)
    return os.path.abspath(os.path.join(PROJECT_DIR, text))


def server_base_url(*, host: str, port: int) -> str:
    return f"http://{host}:{port}"
