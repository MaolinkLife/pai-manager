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


def test_normalize_folds_legacy_module_switch_off_into_bridge_switch():
    raw = copy.deepcopy(DEFAULT_CONFIG)
    raw["modules"]["telegram"] = False
    raw["telegram"]["enabled"] = True

    normalized = normalize_config_structure(raw)

    assert normalized["telegram"]["enabled"] is False
    assert "telegram" not in normalized["modules"]


def test_normalize_legacy_module_switch_never_turns_bridge_on():
    raw = copy.deepcopy(DEFAULT_CONFIG)
    raw["modules"]["telegram"] = True
    raw["telegram"]["enabled"] = False

    normalized = normalize_config_structure(raw)

    assert normalized["telegram"]["enabled"] is False
    assert "telegram" not in normalized["modules"]


def test_normalize_keeps_bridge_switch_on_across_repeated_passes():
    raw = copy.deepcopy(DEFAULT_CONFIG)
    raw["modules"].pop("telegram", None)
    raw["telegram"]["enabled"] = True

    once = normalize_config_structure(raw)
    twice = normalize_config_structure(copy.deepcopy(once))

    assert twice["telegram"]["enabled"] is True
    assert "telegram" not in twice["modules"]


def test_normalize_restores_missing_bridge_switch_as_off():
    raw = copy.deepcopy(DEFAULT_CONFIG)
    raw["telegram"].pop("enabled", None)

    normalized = normalize_config_structure(raw)

    assert normalized["telegram"]["enabled"] is False


LEGACY_IMAGE_ASSESSMENT_KEYS = {"assess_enabled", "quality_threshold", "max_attempts", "retry_enabled"}


def test_normalize_replaces_the_old_image_assessment_with_the_image_check():
    raw = copy.deepcopy(DEFAULT_CONFIG)
    raw["synthesis"]["prompting"].update(
        {"assess_enabled": True, "quality_threshold": 0.72, "max_attempts": 3, "retry_enabled": True}
    )
    raw["synthesis"].pop("image_check")

    normalized = normalize_config_structure(raw)

    prompting = normalized["synthesis"]["prompting"]
    assert not LEGACY_IMAGE_ASSESSMENT_KEYS & set(prompting)
    # Hidden in the UI, kept in the config until it is understood what it was for.
    assert prompting["enabled"] is True
    # The old values never took effect; the new defaults apply.
    assert normalized["synthesis"]["image_check"] == DEFAULT_CONFIG["synthesis"]["image_check"]


def test_normalize_keeps_image_check_settings_the_owner_changed():
    raw = copy.deepcopy(DEFAULT_CONFIG)
    raw["synthesis"]["image_check"]["quality"] = {"enabled": True, "threshold": 0.9, "reroll": True}
    raw["synthesis"]["image_check"]["system_prompt"] = "Judge strictly."

    normalized = normalize_config_structure(raw)

    assert normalized["synthesis"]["image_check"]["quality"] == {"enabled": True, "threshold": 0.9, "reroll": True}
    assert normalized["synthesis"]["image_check"]["system_prompt"] == "Judge strictly."


def test_a_fresh_config_presets_the_image_check_and_its_prompts():
    normalized = normalize_config_structure({})

    check = normalized["synthesis"]["image_check"]
    assert check["relevance"] == {"enabled": True, "threshold": 0.6, "reroll": False}
    assert check["quality"] == {"enabled": False, "threshold": 0.82, "reroll": False}
    assert check["max_generations"] == 2
    for key in ("describe_prompt", "system_prompt", "user_template"):
        assert check[key].strip(), key
    assert not LEGACY_IMAGE_ASSESSMENT_KEYS & set(normalized["synthesis"]["prompting"])


def test_the_config_model_and_the_defaults_agree_on_the_image_check():
    from models.config_model import SynthesisImageCheckConfig

    assert SynthesisImageCheckConfig().model_dump() == DEFAULT_CONFIG["synthesis"]["image_check"]


def test_a_fresh_config_presets_the_image_scene_answer_format():
    from models.config_model import SynthesisImageSceneConfig

    normalized = normalize_config_structure({})

    assert normalized["synthesis"]["image_scene"]["format_prompt"].strip()
    assert SynthesisImageSceneConfig().model_dump() == DEFAULT_CONFIG["synthesis"]["image_scene"]
