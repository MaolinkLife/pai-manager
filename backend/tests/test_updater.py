"""Self-update — unit tests for version logic and safety refusals."""

from modules.system import updater


def test_parse_version_variants():
    assert updater._parse_version("0.9.2") == (0, 9, 2)
    assert updater._parse_version("v1.2.10") == (1, 2, 10)
    assert updater._parse_version("") == (0,)
    assert updater._parse_version("garbage") == (0,)


def test_is_newer_semver_not_lexicographic():
    assert updater._is_newer("0.10.0", "0.9.2")
    assert not updater._is_newer("0.9.2", "0.9.2")
    assert not updater._is_newer("0.9.1", "0.9.2")
    assert updater._is_newer("1.0.0", "0.9.9")
    # Unknown local version → any remote counts as newer.
    assert updater._is_newer("0.1.0", "")
    assert not updater._is_newer("", "0.9.2")


def test_read_local_version_matches_changelog_head():
    version = updater.read_local_version()
    assert version, "changelog head must carry a version: line"
    assert updater._parse_version(version) >= (0, 9)


def test_run_update_refuses_dirty_tree(monkeypatch):
    monkeypatch.setattr(updater, "_git_available", lambda: True)
    monkeypatch.setattr(
        updater, "_git_state", lambda: {"branch": "master", "sha": "abc", "dirty": True}
    )
    result = updater.run_update("branch")
    assert result["status"] == "error"
    assert result["code"] == "dirty_tree"


def test_run_update_without_git_gives_download_link(monkeypatch):
    monkeypatch.setattr(updater, "_git_available", lambda: False)
    monkeypatch.setattr(updater, "_fetch_latest_release", lambda repo: None)
    result = updater.run_update("branch")
    assert result["status"] == "error"
    assert result["code"] == "no_git"
    assert result["download_url"].startswith("https://github.com/")
