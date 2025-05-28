import os
import json
from services import config_service  # Импортируем чтобы вносить изменения в конфиг

PRESET_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "generation_presets.json")

# 🔐 Стандартный пресет, если файл отсутствует
DEFAULT_PRESET = [{
    "name": "Default",
    "description": "Базовые параметры генерации",
    "temperature": 1.0,
    "min_p": 0.05,
    "top_p": 0.9,
    "top_k": 40,
    "repeat_penalty": 1.0,
    "stop": None,
    "num_predict": 1024
}]


def ensure_presets_exist():
    if not os.path.exists(PRESET_PATH):
        save_presets(DEFAULT_PRESET)


def get_all_presets() -> list:
    ensure_presets_exist()
    with open(PRESET_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_presets(presets: list):
    with open(PRESET_PATH, "w", encoding="utf-8") as f:
        json.dump(presets, f, indent=4, ensure_ascii=False)


def update_or_add_preset(preset: dict):
    name = preset.get("name")
    if not name:
        raise ValueError("Preset must have a 'name' field")

    presets = get_all_presets()

    existing_index = next((i for i, p in enumerate(presets) if p["name"] == name), None)

    if existing_index is not None:
        presets[existing_index] = preset  # обновляем существующий
    else:
        presets.append(preset)  # добавляем новый

    save_presets(presets)

    # 🎯 Обновляем config.json на основе нового/обновлённого пресета
    apply_preset_to_config(preset)


def apply_preset_to_config(preset: dict):
    gen_settings = {
        key: preset.get(key)
        for key in [
            "temperature", "min_p", "top_p", "top_k",
            "repeat_penalty", "stop", "num_predict"
        ]
        if key in preset
    }

    gen_settings["name"] = preset.get("name")
    gen_settings["description"] = preset.get("description", "")

    config_service.set_config_value("generate_settings", gen_settings)

def get_preset_by_name(name: str) -> dict | None:
    presets = get_all_presets()
    for p in presets:
        if p["name"] == name:
            return p
    return None