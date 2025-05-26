import yaml
import os
from config import config_loader

def load_system_prompt() -> str:
    base_path = os.path.join(os.path.dirname(__file__), "..", "config", "characters")
    
    char_name = config_loader.get_config_value("char_name", default="default")
    filename = f"{char_name}.yaml"
    full_path = os.path.join(base_path, filename)
    
    fallback_path = os.path.join(base_path, "default.yaml")

    try:
        if os.path.exists(full_path):
            with open(full_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data.get("prompt", "")
        elif os.path.exists(fallback_path):
            with open(fallback_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data.get("prompt", "")
        else:
            print("[❌] Ни кастом, ни fallback не найдены")
            return "[System Error] Character prompt not found."
    except Exception as e:
        print(f"[Ошибка чтения character-файла]: {e}")
        return "[System Error] Prompt loading failed."

def build_chat_request(history, include_system=True):
    full_history = history[:]
    if include_system:
        system_prompt = load_system_prompt()
        if system_prompt:
            full_history.insert(0, {
                "role": "system",
                "content": system_prompt
            })
    return full_history

