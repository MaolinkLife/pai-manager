# =========================================================
# Модуль: prompt_builder.py
# Назначение: Сборка истории сообщений для отправки в модель
# Используется в: api_service, ollama_service
# Особенности:
# - Добавляет system prompt, память и эмоции в начало истории
# - Удаляет ненужные поля из сообщений (например, timestamp)
# - Поддерживает настройку включения system prompt
# =======================================================

def compose_prompt(system_prompt, memory=None, emotion=None, history=[], user_input=""):
    messages = [{"role": "system", "content": system_prompt}]
    if memory:
        messages.append({"role": "system", "content": f"[Память] {memory}"})
    if emotion:
        messages.append({"role": "system", "content": f"[Эмоции] {emotion}"})
    messages.extend(history)
    messages.append({"role": "user", "content": user_input})
    return messages