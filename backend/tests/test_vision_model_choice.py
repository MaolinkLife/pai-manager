"""The vision module describes images, with the model picked in the vision settings.

Rules:
- No vision model is assumed. With none picked the module says so, and the
  final model tells the user the vision module is not connected.
- An image is described by the vision module only: there is no path that hands
  it to the main model, whatever an old config still says.
"""

import asyncio

import pytest

import modules.vision.providers.apple_vision as apple_vision
import modules.vision.providers.ollama_vision as ollama_vision
from constants.default_config import DEFAULT_CONFIG
from constants.visual import VISION_MODEL_NOT_SELECTED
from core import decision_layer as decision_layer_module
from core.decision_layer import DecisionLayer
from models.config_model import VisionConfig, VisionModulesAppleVisionConfig, VisionModulesLlavaConfig
from modules.ollama import client as ollama_client
from modules.vision import visual_module as visual_module_mod
from modules.vision.providers.ollama_vision import OllamaVisionProvider


def _no_call(*args, **kwargs):
    raise AssertionError("nothing is asked about a model nobody picked")


def _picked_models(vision_modules):
    return {
        name: str(cfg.get("model") or cfg.get("model_id") or "")
        for name, cfg in vision_modules.items()
        if isinstance(cfg, dict) and ("model" in cfg or "model_id" in cfg)
    }


def test_no_vision_provider_comes_with_a_model():
    defaults = _picked_models(DEFAULT_CONFIG["vision"]["vision_modules"])
    model_defaults = _picked_models(VisionConfig().vision_modules)

    assert defaults and all(model == "" for model in defaults.values()), defaults
    assert model_defaults and all(model == "" for model in model_defaults.values()), model_defaults
    assert VisionModulesAppleVisionConfig().model_id == ""
    assert VisionModulesLlavaConfig().model_id == ""


def test_an_ollama_vision_without_a_model_says_it_is_not_selected(monkeypatch):
    monkeypatch.setattr(ollama_vision.ollama_client, "is_available", lambda: True)
    monkeypatch.setattr(ollama_vision.ollama_client, "model_supports_vision", _no_call)
    provider = OllamaVisionProvider({"model": ""})

    assert provider.is_ready() is False
    assert provider._last_probe_error == VISION_MODEL_NOT_SELECTED


def test_an_apple_vision_without_a_model_loads_nothing(monkeypatch):
    monkeypatch.setattr(apple_vision, "log_audit_entry", lambda *args, **kwargs: None)
    provider = apple_vision.AppleVisionProvider(None)

    assert provider.is_ready() is False
    assert provider._load_error == VISION_MODEL_NOT_SELECTED
    assert provider.model is None


def test_the_vision_module_takes_the_model_from_the_vision_settings(monkeypatch):
    settings = {"vision.vision_modules.apple_vision": {"model_id": "apple/FastVLM-1.5B"}}
    monkeypatch.setattr(visual_module_mod.config_service, "get_config_value", lambda path, default=None: settings.get(path, default))

    module = visual_module_mod.VisualModule("apple_vision")

    assert module.provider.model_id == "apple/FastVLM-1.5B"


def test_the_vision_module_names_why_it_cannot_look(monkeypatch):
    settings = {"vision.vision_modules.ollama_vision": {"model": ""}}
    monkeypatch.setattr(visual_module_mod.config_service, "get_config_value", lambda path, default=None: settings.get(path, default))
    monkeypatch.setattr(ollama_vision.ollama_client, "is_available", lambda: True)

    module = visual_module_mod.VisualModule("ollama_vision")

    assert module.is_ready() is False
    assert module.unavailable_reason() == VISION_MODEL_NOT_SELECTED


def test_the_ollama_client_does_not_pick_a_vision_model_of_its_own():
    assert ollama_client._resolve_visual_model(None) == ""
    assert ollama_client._resolve_visual_model(" qwen3.5:9b ") == "qwen3.5:9b"


class _NotReadyVision:
    def is_ready(self):
        return False

    def unavailable_reason(self):
        return VISION_MODEL_NOT_SELECTED


def test_an_image_goes_to_the_vision_module_even_with_the_old_bypass_switched_on(monkeypatch):
    settings = {
        "vision.enabled": True,
        "vision.active_provider": "ollama_vision",
        "vision.vision_modules.ollama_vision.use_main_model_context": True,
        "api.active_provider": "ollama",
    }
    monkeypatch.setattr(
        decision_layer_module.config_service,
        "get_config_value",
        lambda path, default=None: settings.get(path, default),
    )
    layer = DecisionLayer.__new__(DecisionLayer)
    layer._visual_module = _NotReadyVision()
    layer._visual_module_failed = False
    media = [{"category": "image", "name": "photo.png", "data": "aGVsbG8="}]

    context = asyncio.run(layer._collect_visual_context(media, {"needs_vision": True}))

    assert "direct_context" not in context.get("attachments", {})
    assert context["attachments"]["unavailable"] is True
    assert context["attachments"]["reason"] == VISION_MODEL_NOT_SELECTED
