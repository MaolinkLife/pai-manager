"""PAI runs on the backend venv only.

Found 2026-09-12: activate.bat still pointed at the folder the venv was created
in before the project was renamed, so launch.bat silently ran the live backend
on miniconda packages while the tests ran on the venv.
"""

import importlib.util
import os
import sys

import pytest

pytestmark = pytest.mark.regression

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.dirname(BACKEND_DIR)
BACKEND_VENV_DIR = os.path.join(BACKEND_DIR, "venv")


@pytest.fixture
def launcher():
    dont_write_bytecode = sys.dont_write_bytecode
    spec = importlib.util.spec_from_file_location("pai_launcher", os.path.join(PROJECT_DIR, "run.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    sys.dont_write_bytecode = dont_write_bytecode


def _read(name):
    with open(os.path.join(PROJECT_DIR, name), encoding="utf-8") as handle:
        return handle.read()


def _code_lines(text):
    lines = (line.strip() for line in text.splitlines())
    return [line for line in lines if line and not line.startswith("::")]


def test_launcher_accepts_the_backend_venv(launcher):
    assert launcher.backend_venv_mismatch(BACKEND_VENV_DIR) is None


def test_launcher_refuses_any_other_python(launcher):
    mismatch = launcher.backend_venv_mismatch(r"C:\Users\someone\miniconda3")
    assert mismatch is not None
    assert mismatch["expected"] == os.path.normcase(os.path.abspath(BACKEND_VENV_DIR))


def test_tests_run_on_the_same_python_as_the_live_backend(launcher):
    assert launcher.backend_venv_mismatch() is None, sys.prefix


def test_launch_bat_starts_run_py_with_the_venv_python():
    lines = _code_lines(_read("launch.bat"))
    assert not any("activate" in line.lower() for line in lines)
    assert not any(line.lower().startswith("python ") for line in lines)
    assert '"%PAI_PYTHON%" run.py' in lines
    assert any("backend\\venv\\Scripts\\python.exe" in line for line in lines)


def test_install_bat_installs_packages_into_the_venv():
    lines = _code_lines(_read("install.bat"))
    assert not any("activate" in line.lower() for line in lines)
    pip_lines = [line for line in lines if "-m pip" in line]
    assert pip_lines
    assert all(line.startswith('"%VENV_PYTHON%" -m pip') for line in pip_lines)
