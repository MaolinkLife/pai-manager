import copy

import pytest

from constants.default_config import DEFAULT_CONFIG
from modules.system.config import normalize_config_structure


pytestmark = pytest.mark.regression


def test_normalize_forces_telegram_fallback_off_when_main_chat_primary():
    raw = copy.deepcopy(DEFAULT_CONFIG)
    raw["communication"]["priority"] = ["main_chat", "telegram"]
    raw["communication"]["channels"]["telegram"]["allow_fallback"] = True

    normalized = normalize_config_structure(raw)

    assert normalized["communication"]["channels"]["telegram"]["allow_fallback"] is False


def test_normalize_keeps_telegram_fallback_when_telegram_primary():
    raw = copy.deepcopy(DEFAULT_CONFIG)
    raw["communication"]["priority"] = ["telegram", "main_chat"]
    raw["communication"]["channels"]["telegram"]["allow_fallback"] = True

    normalized = normalize_config_structure(raw)

    assert normalized["communication"]["channels"]["telegram"]["allow_fallback"] is True


def test_normalize_adds_synthesis_defaults():
    raw = copy.deepcopy(DEFAULT_CONFIG)
    raw.pop("synthesis", None)

    normalized = normalize_config_structure(raw)

    assert "synthesis" in normalized
    assert "sd_webui" in normalized["synthesis"]
    assert normalized["synthesis"]["sd_webui"]["base_url"] == "http://127.0.0.1:7860"
