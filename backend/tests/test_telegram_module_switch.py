import copy

import pytest

from constants.default_config import DEFAULT_CONFIG
from modules.system import config as config_service
from modules.system.config import validate_config
from modules.telegram import runtime as telegram_runtime
from modules.telegram.service import TelegramBridgeService


pytestmark = pytest.mark.regression


class _FakeBridge:
    def __init__(self, running: bool):
        self.running = running
        self.stop_calls = 0

    def is_running(self) -> bool:
        return self.running

    def stop(self) -> None:
        self.stop_calls += 1
        self.running = False


def _serve_config(monkeypatch, values: dict) -> None:
    monkeypatch.setattr(
        config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: values.get(path, default),
    )


def _bridge_without_init() -> TelegramBridgeService:
    # Skip __init__: it builds guards and status that the switch check does not need.
    return TelegramBridgeService.__new__(TelegramBridgeService)


def test_bridge_is_switched_by_telegram_enabled_alone(monkeypatch):
    _serve_config(monkeypatch, {"telegram.enabled": True, "modules.telegram": False})

    assert _bridge_without_init()._is_enabled() is True


def test_bridge_is_off_when_telegram_enabled_is_off(monkeypatch):
    _serve_config(monkeypatch, {"telegram.enabled": False, "modules.telegram": True})

    assert _bridge_without_init()._is_enabled() is False


def test_bridge_is_off_when_switch_is_missing(monkeypatch):
    _serve_config(monkeypatch, {})

    assert _bridge_without_init()._is_enabled() is False


def test_sync_stops_running_bridge_when_switched_off(monkeypatch):
    bridge = _FakeBridge(running=True)
    monkeypatch.setattr(telegram_runtime, "telegram_bridge_runtime", bridge)
    monkeypatch.setattr(telegram_runtime, "log_audit_entry", lambda *args, **kwargs: None)
    _serve_config(monkeypatch, {"telegram.enabled": False})

    assert telegram_runtime.sync_telegram_bridge_with_config() is True
    assert bridge.stop_calls == 1


def test_sync_keeps_bridge_running_when_switched_on(monkeypatch):
    bridge = _FakeBridge(running=True)
    monkeypatch.setattr(telegram_runtime, "telegram_bridge_runtime", bridge)
    _serve_config(monkeypatch, {"telegram.enabled": True})

    assert telegram_runtime.sync_telegram_bridge_with_config() is False
    assert bridge.stop_calls == 0


def test_sync_does_not_create_bridge_that_was_never_started(monkeypatch):
    monkeypatch.setattr(telegram_runtime, "telegram_bridge_runtime", None)
    _serve_config(monkeypatch, {"telegram.enabled": False})

    assert telegram_runtime.sync_telegram_bridge_with_config() is False
    assert telegram_runtime.telegram_bridge_runtime is None


def test_validate_requires_credentials_when_bridge_is_on():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["telegram"]["enabled"] = True

    ok, errors = validate_config(cfg)

    assert ok is False
    assert any("telegram.api_id" in err for err in errors)
    assert any("telegram.api_hash" in err for err in errors)


def test_validate_skips_credentials_when_bridge_is_off():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["telegram"]["enabled"] = False

    ok, errors = validate_config(cfg)

    assert ok is True
    assert errors == []


def test_bulk_update_ignores_retired_module_switch(monkeypatch):
    stored = copy.deepcopy(DEFAULT_CONFIG)
    stored["telegram"]["enabled"] = True
    saved = {}
    monkeypatch.setattr(config_service, "get_config", lambda user_uuid=None: copy.deepcopy(stored))
    monkeypatch.setattr(
        config_service,
        "save_config",
        lambda data, user_uuid=None: saved.update(config_service.normalize_config_structure(data)),
    )
    monkeypatch.setattr(config_service, "log_audit_entry", lambda *args, **kwargs: None)

    config_service.update_config_bulk({"modules": {"telegram": False, "discord": True}})

    assert saved["telegram"]["enabled"] is True
    assert saved["modules"]["discord"] is True
    assert "telegram" not in saved["modules"]
