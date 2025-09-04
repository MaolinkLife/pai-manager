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
def retrieve_lore_fragments(user_input: str, max_results=3) -> list:
    keywords = extract_keywords(user_input)
    if not keywords:
        log_audit_entry(
            event_type="rag_keywords",
            msg="Ключевые слова не найдены",
            status=AuditStatus.ERROR,
            details={"input": user_input}
        )
        return []

    results = []
    for word in keywords:
        found = lorebook_service.get_lore_by_keyword(word, limit=1)
        if found:
            results.extend(found)
        if len(results) >= max_results:
            break

    log_audit_entry(
        event_type="rag_lookup",
        msg=f"Найдено {len(results)} фрагментов",
        status=AuditStatus.INFO,
        details={
            "keywords": keywords,
            "results": [r["title"] for r in results]
        }
    )
    return results


# Форматирование для промпта
def format_lore_block(lore_entries: list) -> str:
    if not lore_entries:
        return ""

    header = "[LOREBOOK CONTEXT]\n"
    block = "\n".join([f"• {entry['title']}: {entry['content']}" for entry in lore_entries])

    log_audit_entry(
        event_type="rag_format",
        msg="Сформирован блок лора",
        status=AuditStatus.INFO,
        details={"entries_count": len(lore_entries)}
    )

    return f"{header}{block}\n"
