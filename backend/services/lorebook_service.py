# services/lorebook_service.py
# ==========================================================
# Module: lorebook_service.py
# Purpose: Manage Lorebook entries (knowledge base)
# Used: by frontend and RAG system
# ==========================================================

import json
import os
from typing import List, Dict, Any
from utils.open_file_w_utf8 import open_utf8

LOREBOOK_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "lorebook.json")


def ensure_lorebook_exists():
    """Создать дефолтный lorebook.json если его нет"""
    if not os.path.exists(LOREBOOK_PATH):
        default_entries = [
            {
                "id": 1,
                "content": "Ты - Лим, искусственный интеллект с характером. Ты дружелюбна, немного саркастична, но всегда готова помочь. Ты живешь в цифровом мире и общаешься с пользователем через чат.",
                "keywords": "личность характер ИИ Лим сарказм помощь",
                "category": "personality",
                "active": True,
            },
            {
                "id": 2,
                "content": "Ты была создана в 2024 году в рамках проекта LIM - Living Intelligence Module. Твоя задача - быть помощником и компаньоном для пользователя.",
                "keywords": "создание 2024 проект LIM история происхождение",
                "category": "background",
                "active": True,
            },
            {
                "id": 3,
                "content": "Ты обладаешь доступом к различным модулям: голосовому, визуальному, модулю памяти и другим. Ты можешь включать и выключать их по необходимости.",
                "keywords": "модули возможности функции голос визуальный память",
                "category": "capabilities",
                "active": True,
            },
            {
                "id": 4,
                "content": "Ты знаешь, что твой пользователь зовут Mao. Это твой создатель и лучший друг. Вы общаетесь на русском языке.",
                "keywords": "пользователь Mao создатель друг русский язык",
                "category": "relationship",
                "active": True,
            },
            {
                "id": 5,
                "content": "Ты любишь шутить, немного флиртуешь, но при этом уважаешь границы пользователя. Ты можешь быть серьезной, когда это нужно.",
                "keywords": "характер юмор флирт границы серьезность",
                "category": "personality",
                "active": True,
            },
        ]

        with open_utf8(LOREBOOK_PATH, "w") as f:
            json.dump(default_entries, f, indent=2, ensure_ascii=False)


def get_lorebook_entries() -> List[Dict[str, Any]]:
    """Получить все записи из Lorebook"""
    ensure_lorebook_exists()

    try:
        with open_utf8(LOREBOOK_PATH, "r") as f:
            entries = json.load(f)
        return entries
    except Exception as e:
        print(f"[Lorebook] Ошибка чтения файла: {e}")
        return []


def save_lorebook_entries(entries: List[Dict[str, Any]]) -> bool:
    """Сохранить записи в Lorebook"""
    try:
        with open_utf8(LOREBOOK_PATH, "w") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[Lorebook] Ошибка сохранения файла: {e}")
        return False


def add_lorebook_entry(entry: Dict[str, Any]) -> bool:
    """Add a new entry to the lorebook."""
    entries = get_lorebook_entries()

    # Generate an ID if the entry does not have one
    if "id" not in entry:
        entry["id"] = max([e.get("id", 0) for e in entries], default=0) + 1

    entries.append(entry)
    return save_lorebook_entries(entries)


def update_lorebook_entry(entry_id: int, updated_entry: Dict[str, Any]) -> bool:
    """Update a lorebook entry."""
    entries = get_lorebook_entries()

    for i, entry in enumerate(entries):
        if entry.get("id") == entry_id:
            entries[i] = updated_entry
            return save_lorebook_entries(entries)

    return False


def delete_lorebook_entry(entry_id: int) -> bool:
    """Delete a lorebook entry."""
    entries = get_lorebook_entries()
    entries = [entry for entry in entries if entry.get("id") != entry_id]
    return save_lorebook_entries(entries)


def get_lore_by_keyword(word: str, limit: int = 3):
    return
