# ===========================================================
# Module: lorebook_service.py
# Purpose: Работа с таблицей lore_chunks (лоровые записи)
# ===========================================================

from sqlalchemy import text
from services.db_core import SessionLocal
from services.logger_service import log_audit_entry, AuditStatus


def get_lore_by_keyword(keyword: str, limit: int = 1):
    session = SessionLocal()
    try:
        sql = text("""
            SELECT title, content, tags FROM lore_chunks
            WHERE title LIKE :kw OR tags LIKE :kw
            LIMIT :limit
        """)
        rows = session.execute(sql, {"kw": f"%{keyword}%", "limit": limit}).fetchall()
        return [
            {"title": row.title, "content": row.content, "tags": row.tags}
            for row in rows
        ]
    except Exception as e:
        log_audit_entry(
            event_type="lore_error",
            msg="Ошибка при поиске по лору",
            status=AuditStatus.ERROR,
            details={"error": str(e), "keyword": keyword}
        )
        return []
    finally:
        session.close()
