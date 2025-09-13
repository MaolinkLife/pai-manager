# ===========================================================
# Module: lorebook_service.py
# Purpose: Работа с таблицей lore_chunks (лоровые записи)
# ===========================================================
import traceback
import logging
from sqlalchemy import text
from services.db_core import SessionLocal
from services.logger_service import log_audit_entry, AuditStatus

sql_logger = logging.getLogger("sql_debug")
sql_handler = logging.FileHandler("logs/sql_debug.log", encoding="utf-8")
sql_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
sql_logger.addHandler(sql_handler)
sql_logger.setLevel(logging.DEBUG)


def get_lore_by_keyword(keyword: str, limit: int = 1):
    session = SessionLocal()
    try:
        sql = text(
            """
            SELECT title, content, tags FROM lore_chunks
            WHERE title LIKE :kw OR tags LIKE :kw
            LIMIT :limit
        """
        )
        rows = session.execute(sql, {"kw": f"%{keyword}%", "limit": limit}).fetchall()
        return [
            {"title": row.title, "content": row.content, "tags": row.tags}
            for row in rows
        ]
    except Exception as e:
        # 🔹 Лаконично в UI
        log_audit_entry(
            event_type="lore_error",
            msg="Ошибка при поиске по лору",
            status=AuditStatus.ERROR,
            details={
                "error": f"{e.__class__.__name__}: {str(e).splitlines()[0]}",
                "keyword": keyword,
            },
        )

        # 🔹 Полный SQL и traceback в отдельный файл
        sql_logger.debug(
            "Lore DB error | keyword=%s | error=%s\nTrace:\n%s",
            keyword,
            str(e),
            traceback.format_exc(),
        )
        return []
    finally:
        session.close()
