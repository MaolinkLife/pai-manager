import json
import os

from modules.system import config as config_service
from utils.open_file_w_utf8 import open_utf8

PRESET_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "generation_presets.json"
)

DEFAULT_PRESET = [
    {
        "name": "Default",
        "description": "Base parameters for generation",
        "temperature": 1.0,
        "min_p": 0.05,
        "top_p": 0.9,
        "top_k": 40,
        "repeat_penalty": 1.0,
        "stop": None,
        "num_predict": 1024,
        "normalize_messages": False,
    }
]


def _pick(source: dict, snake_key: str, camel_key: str = None, default=None):
    if snake_key in source:
        return source.get(snake_key)
    if camel_key and camel_key in source:
        return source.get(camel_key)
    return default


def normalize_preset(preset: dict) -> dict:
    return {
        "name": preset.get("name") or "Default",
        "description": preset.get("description", ""),
        "temperature": _pick(preset, "temperature", default=1.0),
        "min_p": _pick(preset, "min_p", "minP", 0.05),
        "top_p": _pick(preset, "top_p", "topP", 0.9),
        "top_k": _pick(preset, "top_k", "topK", 40),
        "repeat_penalty": _pick(preset, "repeat_penalty", "repeatPenalty", 1.0),
        "stop": preset.get("stop"),
        "num_predict": _pick(preset, "num_predict", "numPredict", 1024),
        "normalize_messages": _pick(preset, "normalize_messages", "normalizeMessages", False),
    }


def ensure_presets_exist():
    if not os.path.exists(PRESET_PATH):
        save_presets(DEFAULT_PRESET)


def get_all_presets() -> list:
    ensure_presets_exist()
    with open_utf8(PRESET_PATH, "r") as file:
        return [normalize_preset(preset) for preset in json.load(file)]


def save_presets(presets: list):
    with open_utf8(PRESET_PATH, "w") as file:
        json.dump(presets, file, indent=4, ensure_ascii=False)


def update_or_add_preset(preset: dict):
    preset = normalize_preset(preset)
    name = preset.get("name")
    if not name:
        raise ValueError("Preset must have a 'name' field")

    presets = get_all_presets()
    existing_index = next((i for i, p in enumerate(presets) if p["name"] == name), None)
    if existing_index is not None:
        presets[existing_index] = preset
    else:
        presets.append(preset)

    save_presets(presets)
    apply_preset_to_config(preset)


def apply_preset_to_config(preset: dict):
    gen_settings = {
        key: preset.get(key)
        for key in [
            "temperature",
            "min_p",
            "top_p",
            "top_k",
            "repeat_penalty",
            "stop",
            "num_predict",
            "normalize_messages",
        ]
        if key in preset
    }

    gen_settings["name"] = preset.get("name")
    gen_settings["description"] = preset.get("description", "")
    config_service.set_config_value("generate_settings", gen_settings)


def get_preset_by_name(name: str) -> dict | None:
    presets = get_all_presets()
    for preset in presets:
        if preset["name"] == name:
            return preset
    return None
