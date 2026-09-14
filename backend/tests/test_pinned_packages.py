"""Packages pinned in requirements.txt are the ones installed in the backend venv.

requirements.txt asked for "the latest diffusers from git", so
two environments ended up with different builds and an image model crashed
on the older one.
"""

import importlib.metadata
import json
import os
import re

import pytest

pytestmark = pytest.mark.regression

REQUIREMENTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "requirements.txt")


def _requirement(name):
    with open(REQUIREMENTS, encoding="utf-8") as handle:
        for line in handle:
            text = line.split("#", 1)[0].strip()
            if re.match(rf"{re.escape(name)}\b", text, re.IGNORECASE):
                return text
    raise AssertionError(f"{name} is not in requirements.txt")


def test_diffusers_is_the_pinned_git_commit():
    line = _requirement("diffusers")
    pinned = re.search(r"@\s*git\+\S+@([0-9a-f]{40})$", line)
    assert pinned, f"diffusers must be pinned to a git commit: {line}"

    direct_url = importlib.metadata.distribution("diffusers").read_text("direct_url.json") or "{}"
    installed = json.loads(direct_url).get("vcs_info", {}).get("commit_id")
    assert installed == pinned.group(1)


def test_safetensors_is_the_pinned_version():
    line = _requirement("safetensors")
    pinned = re.fullmatch(r"safetensors==(\S+)", line)
    assert pinned, f"safetensors must be pinned exactly: {line}"
    assert importlib.metadata.version("safetensors") == pinned.group(1)
