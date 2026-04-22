import copy

import pytest

from constants.default_config import DEFAULT_CONFIG
from modules.system.config import validate_config


pytestmark = pytest.mark.regression


def _base_config():
    return copy.deepcopy(DEFAULT_CONFIG)


def test_validate_fails_when_all_channels_disabled():
    cfg = _base_config()
    cfg["communication"]["channels"]["main_chat"]["enabled"] = False
    cfg["communication"]["channels"]["telegram"]["enabled"] = False

    ok, errors = validate_config(cfg)
    assert ok is False
    assert any("at least one enabled channel" in err for err in errors)


def test_validate_fails_when_main_chat_primary_and_telegram_fallback_true():
    cfg = _base_config()
    cfg["communication"]["priority"] = ["main_chat", "telegram"]
    cfg["communication"]["channels"]["main_chat"]["enabled"] = True
    cfg["communication"]["channels"]["telegram"]["enabled"] = True
    cfg["communication"]["channels"]["telegram"]["allow_fallback"] = True

    ok, errors = validate_config(cfg)
    assert ok is False
    assert any("allow_fallback must be false when main_chat is primary" in err for err in errors)


def test_validate_passes_for_telegram_primary_with_fallback():
    cfg = _base_config()
    cfg["communication"]["priority"] = ["telegram", "main_chat"]
    cfg["communication"]["channels"]["main_chat"]["enabled"] = True
    cfg["communication"]["channels"]["telegram"]["enabled"] = True
    cfg["communication"]["channels"]["telegram"]["allow_fallback"] = True

    ok, errors = validate_config(cfg)
    assert ok is True
    assert errors == []
