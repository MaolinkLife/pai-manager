# ===========================================================
# Module: rag_service.py
# Purpose: Extracting suitable lore from the DB to generate a response
# ==========================================================

import re
from sqlalchemy import text
from services.sqlite_service import SessionLocal
from services.logger_service import log_audit_entry, AuditStatus

# Helper function - simple text splitting into keywords
def extract_keywords(text: str) -> list:
    words = re.findall(r"\b\w{4,}\b", text.lower())
    return list(set(words))


# Search lore from the lore_chunks table
def retrieve_lore_fragments(user_input: str, max_results=3) -> list:
    keywords = extract_keywords(user_input)
    if not keywords:
        log_audit_entry(
            event_type="rag_keywords",
            msg="Keywords not found",
            status=AuditStatus.ERROR,
            details={"input": user_input}
        )
        return []

    session = SessionLocal()
    try:
        results = []
        for word in keywords:
            sql = text("""
                SELECT title, content, tags FROM lore_chunks
                WHERE title LIKE :kw OR tags LIKE :kw
                LIMIT 1
            """)
            row = session.execute(sql, {"kw": f"%{word}%"}).fetchone()
            if row:
                results.append({
                    "title": row.title,
                    "content": row.content,
                    "tags": row.tags
                })
            if len(results) >= max_results:
                break

        log_audit_entry(
            event_type="rag_lookup",
            msg=f"Found {len(results)} fragments for the requestу",
            status=AuditStatus.INFO,
            details={
                "keywords": keywords,
                "results": [r["title"] for r in results]
            }
        )
        return results

    except Exception as e:
        log_audit_entry(
            event_type="rag_error",
            msg="Error while extracting lore fragments",
            status=AuditStatus.ERROR,
            details={"error": str(e)}
        )
        return []

    finally:
        session.close()


# Preparing text for insertion into prompt
def format_lore_block(lore_entries: list) -> str:
    if not lore_entries:
        return ""

    header = "[LOREBOOK CONTEXT]\n"
    block = "\n".join([f"• {entry['title']}: {entry['content']}" for entry in lore_entries])
    
    log_audit_entry(
        event_type="rag_format",
        msg=f"Lore block formed",
        status=AuditStatus.INFO,
        details={"entries_count": len(lore_entries)}
    )

    return f"{header}{block}\n"
