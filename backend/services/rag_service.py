# ===========================================================
# Module: rag_service.py
# Purpose: Извлечение подходящего лора из БД для генерации ответа
# ===========================================================

import re
from services.logger_service import log_audit_entry, AuditStatus
from services import lorebook_service


# Простая вычленялка ключевых слов
def extract_keywords(text: str) -> list:
    words = re.findall(r"\b\w{4,}\b", text.lower())
    return list(set(words))


# Поиск фрагментов по ключевым словам
def retrieve_lore_fragments(text):
    try:
        for word in text.split():
            found = lorebook_service.get_lore_by_keyword(word, limit=1)
            # process `found`
    except Exception as e:
        print(f"Error retrieving lore for word '{word}': {e}")
        raise  # re-raise if you want it to propagate


# Форматирование для промпта
def format_lore_block(lore_entries: list) -> str:
    if not lore_entries:
        return ""

    header = "[LOREBOOK CONTEXT]\n"
    block = "\n".join(
        [f"• {entry['title']}: {entry['content']}" for entry in lore_entries]
    )

    log_audit_entry(
        event_type="rag_format",
        msg="Сформирован блок лора",
        status=AuditStatus.INFO,
        details={"entries_count": len(lore_entries)},
    )

    return f"{header}{block}\n"
