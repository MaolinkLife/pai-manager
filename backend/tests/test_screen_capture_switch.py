"""Background screen capture has its own switch.

Vision as a whole describes pictures sent to the chat; background screen capture
is PAI looking at the screen on her own. One can send pictures without sharing the
screen, a fresh install does not capture the screen, and a guest never gets the
owner's screen, only their own pictures described.
"""

import asyncio

import pytest

from constants.default_config import DEFAULT_CONFIG
from core import decision_layer as decision_layer_module
from core.decision_layer import DecisionLayer
from modules.system import config as config_service
from modules.vision import service as vision_service_module
from modules.vision import visual_module as visual_module_module
from modules.vision import worker as worker_module
from modules.vision.visual_module import VisualModule
from modules.vision.worker import ScreenCapturer, screen_capture_enabled

pytestmark = pytest.mark.regression


@pytest.fixture
def settings(monkeypatch):
    values = {}
    monkeypatch.setattr(
        config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: values.get(path, default),
    )
    for module in (decision_layer_module, vision_service_module, visual_module_module, worker_module):
        monkeypatch.setattr(module, "log_audit_entry", lambda *args, **kwargs: None)
    return values


# --- the switch -------------------------------------------------------------


def test_a_fresh_config_describes_pictures_but_does_not_capture_the_screen():
    assert DEFAULT_CONFIG["vision"]["enabled"] is True
    assert DEFAULT_CONFIG["vision"]["screen_capture_enabled"] is False


@pytest.mark.parametrize(
    "vision, capture, expected",
    [(True, True, True), (True, False, False), (False, True, False), (False, False, False)],
)
def test_screen_capture_is_part_of_vision(settings, vision, capture, expected):
    settings.update({"vision.enabled": vision, "vision.screen_capture_enabled": capture})

    assert screen_capture_enabled() is expected


@pytest.mark.parametrize("vision", [True, False])
def test_stored_settings_from_before_the_switch_keep_capturing_as_they_did(monkeypatch, vision):
    monkeypatch.setattr(config_service, "_load_user_tts_settings_from_db", lambda user_uuid: None)
    monkeypatch.setattr(config_service, "_load_user_vision_settings_from_db", lambda user_uuid: {"enabled": vision})
    config = {}

    config_service._apply_split_settings_overrides(config, "owner")

    assert config["vision"]["screen_capture_enabled"] is vision


def test_a_stored_switch_is_kept(monkeypatch):
    monkeypatch.setattr(config_service, "_load_user_tts_settings_from_db", lambda user_uuid: None)
    monkeypatch.setattr(
        config_service,
        "_load_user_vision_settings_from_db",
        lambda user_uuid: {"enabled": True, "screen_capture_enabled": False},
    )
    config = {}

    config_service._apply_split_settings_overrides(config, "owner")

    assert config["vision"]["screen_capture_enabled"] is False


# --- capture itself ---------------------------------------------------------


def test_capture_does_not_start_while_the_switch_is_off(settings):
    settings.update({"vision.enabled": True, "vision.screen_capture_enabled": False})
    capturer = ScreenCapturer(None)

    capturer.start()

    assert capturer.running is False
    assert capturer.capture_thread is None


def test_the_screen_snapshot_refuses_while_the_switch_is_off(settings, monkeypatch):
    settings.update({"vision.enabled": True, "vision.screen_capture_enabled": False})

    def no_service():
        raise AssertionError("the screen must not be looked at")

    monkeypatch.setattr(vision_service_module, "VisionService", no_service)
    module = VisualModule.__new__(VisualModule)

    assert module.describe_screen_snapshot() is None


@pytest.fixture
def vision_service(settings, monkeypatch):
    class Buffer:
        cleared = False

        def clear(self):
            self.cleared = True

    class FakeVisionService:
        _instance = None
        starts = 0
        stops = 0
        start_error = None

        def __init__(self):
            self.capturer = type("Capturer", (), {"running": True})()
            self.buffer = Buffer()
            FakeVisionService._instance = self

        def start(self):
            if FakeVisionService.start_error:
                raise FakeVisionService.start_error
            FakeVisionService.starts += 1

        def stop(self):
            FakeVisionService.stops += 1
            self.capturer.running = False

    monkeypatch.setattr(vision_service_module, "VisionService", FakeVisionService)
    return FakeVisionService


def test_switching_capture_on_starts_it_without_a_restart(settings, vision_service):
    settings.update({"vision.enabled": True, "vision.screen_capture_enabled": True})

    vision_service_module.sync_screen_capture_with_config()

    assert vision_service.starts == 1


def test_switching_capture_off_stops_it_and_forgets_the_frames(settings, vision_service):
    running = vision_service()
    settings.update({"vision.enabled": True, "vision.screen_capture_enabled": False})

    vision_service_module.sync_screen_capture_with_config()

    assert vision_service.stops == 1
    assert running.buffer.cleared is True


def test_capture_that_never_ran_is_not_built_to_be_stopped(settings, vision_service):
    settings.update({"vision.enabled": True, "vision.screen_capture_enabled": False})

    vision_service_module.sync_screen_capture_with_config()

    assert vision_service._instance is None
    assert (vision_service.starts, vision_service.stops) == (0, 0)


def test_capture_that_fails_to_start_does_not_break_saving_settings(settings, vision_service):
    settings.update({"vision.enabled": True, "vision.screen_capture_enabled": True})
    vision_service.start_error = RuntimeError("no model")

    vision_service_module.sync_screen_capture_with_config()


def test_saving_settings_applies_the_capture_switch(monkeypatch):
    from routes import config_routes

    calls = []
    monkeypatch.setattr("modules.telegram.runtime.sync_telegram_bridge_with_config", lambda: calls.append("telegram"))
    monkeypatch.setattr(vision_service_module, "sync_screen_capture_with_config", lambda: calls.append("screen"))

    asyncio.run(config_routes._apply_module_switches())

    assert "screen" in calls


# --- the turn: who may have the screen looked at ------------------------------


class SeeingVision:
    def __init__(self):
        self.screens = 0

    def is_ready(self):
        return True

    def describe_media_attachments(self, media):
        return {
            "items": [{"index": 0, "description": "a red square"}],
            "updates": [{"index": 0, "description": "a red square"}],
        }

    def describe_screen_snapshot(self):
        self.screens += 1
        return {"description": "the owner's desktop"}


@pytest.fixture
def layer(settings):
    settings.update({"vision.enabled": True, "vision.screen_capture_enabled": True})
    instance = DecisionLayer.__new__(DecisionLayer)
    instance._visual_module = SeeingVision()
    instance._visual_module_failed = False
    return instance


def _picture():
    return [{"category": "image", "name": "photo.png", "data": "aGVsbG8="}]


def _look(layer, media, *, owner):
    return asyncio.run(layer._collect_visual_context(media, {"needs_vision": True}, screen_allowed=owner))


def test_the_owner_gets_the_screen_while_capture_is_on(layer):
    context = _look(layer, [], owner=True)

    assert context["screen"]["description"] == "the owner's desktop"
    assert layer._visual_module.screens == 1


def test_the_owner_is_told_capture_is_off(layer, settings):
    settings["vision.screen_capture_enabled"] = False

    context = _look(layer, [], owner=True)

    assert context == {"screen": {"unavailable": True, "reason": decision_layer_module.SCREEN_CAPTURE_OFF_REASON}}
    assert layer._visual_module.screens == 0


def test_a_guest_never_gets_the_screen(layer):
    context = _look(layer, [], owner=False)

    assert context == {"screen": {"unavailable": True, "reason": decision_layer_module.SCREEN_NOT_SHARED_REASON}}
    assert layer._visual_module.screens == 0


def test_a_guest_gets_their_own_picture_described(layer):
    context = _look(layer, _picture(), owner=False)

    assert context["attachments"]["items"][0]["description"] == "a red square"
    assert "screen" not in context
    assert layer._visual_module.screens == 0


def test_a_picture_is_described_with_capture_off(layer, settings):
    settings["vision.screen_capture_enabled"] = False

    context = _look(layer, _picture(), owner=True)

    assert context["attachments"]["items"][0]["description"] == "a red square"
    assert "screen" not in context
    assert layer._visual_module.screens == 0


def test_vision_off_describes_nothing(layer, settings):
    settings["vision.enabled"] = False

    assert _look(layer, _picture(), owner=True) == {}
