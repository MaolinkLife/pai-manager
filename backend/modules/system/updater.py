"""Self-update: compare the local version with GitHub and fast-forward.

Version source of truth is the first line of the root ``changelog``
(``version: X.Y.Z``) — locally and on the remote branch (raw fetch), so the
check works even when the repo has no GitHub Releases. The update itself is
git fast-forward only: a dirty tree or diverged history refuses safely and
nothing is ever overwritten. Zip installs (no .git) get check-only with a
manual-download hint.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_VERSION_RE = re.compile(r"version:\s*([0-9][0-9a-zA-Z.\-]*)")
_HTTP_TIMEOUT = 15
_GIT_TIMEOUT = 120
# Files that require reinstalling dependencies after an update.
_INSTALL_MARKERS = (
    "backend/requirements.txt",
    "backend/requirements.torch-cu121.txt",
    "frontend/package.json",
    "package.json",
)


def _update_settings() -> Dict[str, str]:
    cfg = config_service.get_config_value("system.update", {}) or {}
    return {
        "repo": str(cfg.get("repo") or "MaolinkLife/pai-manager").strip(),
        "branch": str(cfg.get("branch") or "master").strip(),
    }


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

def read_local_version() -> str:
    try:
        head = (PROJECT_ROOT / "changelog").read_text(encoding="utf-8", errors="replace")
        match = _VERSION_RE.search(head[:200])
        return match.group(1) if match else ""
    except Exception:
        return ""


def _parse_version(value: str) -> Tuple[int, ...]:
    parts: List[int] = []
    for piece in re.split(r"[.\-]", str(value or "").lstrip("vV")):
        if piece.isdigit():
            parts.append(int(piece))
        else:
            break
    return tuple(parts) or (0,)


def _is_newer(remote: str, local: str) -> bool:
    if not remote:
        return False
    if not local:
        return True
    return _parse_version(remote) > _parse_version(local)


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git(*args: str) -> Tuple[int, str, str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT,
        )
        return completed.returncode, (completed.stdout or "").strip(), (completed.stderr or "").strip()
    except FileNotFoundError:
        return 127, "", "git executable not found"
    except subprocess.TimeoutExpired:
        return 124, "", "git command timed out"


def _git_available() -> bool:
    if not (PROJECT_ROOT / ".git").exists():
        return False
    code, _, _ = _git("rev-parse", "--git-dir")
    return code == 0


def _git_state() -> Dict[str, Any]:
    code, branch, _ = _git("rev-parse", "--abbrev-ref", "HEAD")
    _, sha, _ = _git("rev-parse", "--short", "HEAD")
    _, porcelain, _ = _git("status", "--porcelain")
    return {
        "branch": branch if code == 0 else "",
        "sha": sha,
        "dirty": bool(porcelain.strip()),
    }


# ---------------------------------------------------------------------------
# Remote info
# ---------------------------------------------------------------------------

def _fetch_latest_release(repo: str) -> Optional[Dict[str, Any]]:
    try:
        response = requests.get(
            f"https://api.github.com/repos/{repo}/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
            timeout=_HTTP_TIMEOUT,
        )
        if response.status_code != 200:
            return None
        data = response.json()
        return {
            "tag": str(data.get("tag_name") or ""),
            "name": str(data.get("name") or ""),
            "published_at": str(data.get("published_at") or ""),
            "notes": str(data.get("body") or "")[:4000],
            "url": str(data.get("html_url") or ""),
            "zip_url": str(data.get("zipball_url") or ""),
        }
    except Exception:
        return None


def _fetch_branch_version(repo: str, branch: str) -> str:
    try:
        response = requests.get(
            f"https://raw.githubusercontent.com/{repo}/{branch}/changelog",
            timeout=_HTTP_TIMEOUT,
        )
        if response.status_code != 200:
            return ""
        match = _VERSION_RE.search(response.text[:200])
        return match.group(1) if match else ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_update() -> Dict[str, Any]:
    settings = _update_settings()
    repo, branch = settings["repo"], settings["branch"]
    local_version = read_local_version()
    git_ok = _git_available()

    result: Dict[str, Any] = {
        "status": "ok",
        "repo": repo,
        "branch": branch,
        "local_version": local_version,
        "git_available": git_ok,
        "git": _git_state() if git_ok else None,
        "release": None,
        "branch_remote": None,
        "has_release_update": False,
        "has_branch_update": False,
    }

    release = _fetch_latest_release(repo)
    if release:
        result["release"] = release
        result["has_release_update"] = _is_newer(release["tag"], local_version)

    branch_version = _fetch_branch_version(repo, branch)
    branch_remote: Dict[str, Any] = {"version": branch_version, "behind": None, "ahead": None}
    if git_ok:
        fetch_code, _, fetch_err = _git("fetch", "origin", branch)
        if fetch_code == 0:
            _, behind, _ = _git("rev-list", "--count", f"HEAD..origin/{branch}")
            _, ahead, _ = _git("rev-list", "--count", f"origin/{branch}..HEAD")
            branch_remote["behind"] = int(behind or 0)
            branch_remote["ahead"] = int(ahead or 0)
            result["has_branch_update"] = branch_remote["behind"] > 0
        else:
            branch_remote["fetch_error"] = fetch_err[:300]
    if not git_ok and branch_version:
        # Zip install: version comparison is all we can offer.
        result["has_branch_update"] = _is_newer(branch_version, local_version)
    result["branch_remote"] = branch_remote

    log_audit_entry(
        "system_update_check",
        "[Updater] Update check finished.",
        AuditStatus.INFO,
        details={
            "local": local_version,
            "release": (release or {}).get("tag"),
            "branch_version": branch_version,
            "behind": branch_remote.get("behind"),
        },
    )
    return result


def run_update(target: str = "branch") -> Dict[str, Any]:
    """Fast-forward the working tree to origin/<branch> or the latest release
    tag. Never force-updates: dirty tree or diverged history → clear refusal."""
    settings = _update_settings()
    repo, branch = settings["repo"], settings["branch"]

    if not _git_available():
        release = _fetch_latest_release(repo)
        return {
            "status": "error",
            "code": "no_git",
            "message": (
                "Установка без git-репозитория: автообновление недоступно. "
                "Скачайте свежий архив вручную."
            ),
            "download_url": (release or {}).get("zip_url")
            or f"https://github.com/{repo}/archive/refs/heads/{branch}.zip",
        }

    state = _git_state()
    if state["dirty"]:
        return {
            "status": "error",
            "code": "dirty_tree",
            "message": "В рабочем дереве есть несохранённые изменения — обновление остановлено, чтобы ничего не потерять.",
        }

    if target == "release":
        release = _fetch_latest_release(repo)
        if not release or not release["tag"]:
            return {"status": "error", "code": "no_release", "message": "На GitHub нет опубликованных релизов."}
        fetch_code, _, fetch_err = _git("fetch", "--tags", "origin")
        if fetch_code != 0:
            return {"status": "error", "code": "fetch_failed", "message": f"git fetch не удался: {fetch_err[:300]}"}
        merge_ref = release["tag"]
    else:
        fetch_code, _, fetch_err = _git("fetch", "origin", branch)
        if fetch_code != 0:
            return {"status": "error", "code": "fetch_failed", "message": f"git fetch не удался: {fetch_err[:300]}"}
        merge_ref = f"origin/{branch}"

    _, old_sha, _ = _git("rev-parse", "HEAD")
    merge_code, _, merge_err = _git("merge", "--ff-only", merge_ref)
    if merge_code != 0:
        return {
            "status": "error",
            "code": "not_fast_forward",
            "message": (
                "Истории разошлись (есть локальные коммиты?) — простое обновление невозможно. "
                f"Детали: {merge_err[:300]}"
            ),
        }
    _, new_sha, _ = _git("rev-parse", "HEAD")

    updated = old_sha != new_sha
    needs_install = False
    if updated:
        _, changed, _ = _git("diff", "--name-only", old_sha, new_sha)
        changed_files = [line.strip() for line in changed.splitlines() if line.strip()]
        needs_install = any(marker in changed_files for marker in _INSTALL_MARKERS)

    log_audit_entry(
        "system_update_applied" if updated else "system_update_noop",
        "[Updater] Update finished.",
        AuditStatus.SUCCESS if updated else AuditStatus.INFO,
        details={
            "target": target,
            "ref": merge_ref,
            "old": old_sha[:10],
            "new": new_sha[:10],
            "needs_install": needs_install,
        },
    )
    return {
        "status": "ok",
        "updated": updated,
        "target": target,
        "ref": merge_ref,
        "old_sha": old_sha[:10],
        "new_sha": new_sha[:10],
        "new_version": read_local_version(),
        "needs_install": needs_install,
        "needs_restart": updated,
    }
