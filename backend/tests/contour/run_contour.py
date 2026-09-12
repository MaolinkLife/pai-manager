"""Run the contour smoke tests on a throwaway storage tree.

    venv\\Scripts\\python.exe tests\\contour\\run_contour.py [extra pytest args]

PAI_STORAGE_DIR is pointed at a fresh temporary directory before pytest starts,
so the database, the vector store and everything else under storage/ are
created there. The temporary directory is removed when the run ends; the live
storage is never opened.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="pai-contour-", ignore_cleanup_errors=True) as storage:
        env = dict(os.environ, PAI_STORAGE_DIR=storage)
        command = [
            sys.executable,
            "-m",
            "pytest",
            "tests/contour",
            "-p",
            "no:cacheprovider",
            *sys.argv[1:],
        ]
        return subprocess.call(command, cwd=BACKEND_DIR, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
