from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    backend_root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, "-m", "pytest", "-m", "regression"]
    print(f"[regression] running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(backend_root))
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
