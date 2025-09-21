import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session, joinedload
from models.models import History, Reasoning
from services.db_core import SessionLocal
from services.logger_service import log_audit_entry, AuditStatus
from utils.time_utils import format_user_datetime
import asyncio
from typing import Optional


def add_history(
    character_id: str,
    role: str,
    content: str,
    timestamp: Optional[datetime] = None,
    session: Optional[Session] = None,
):
    """Добавление сообщения в историю"""
    own_session = False
    if session is None:
        session = SessionLocal()
        own_session = True

    try:
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        entry = History(
            id=str(uuid.uuid4()),
            character_id=character_id,
            role=role,
            content=content,
            timestamp=timestamp,
        )
        session.add(entry)
        session.commit()
        session.refresh(entry)
        return entry
    finally:
        if own_session:
            session.close()


def add_reasoning_entry(
    message_id: str,
    content: str,
    session: Optional[Session] = None,
):
    if not content:
        return None

    own_session = False
    if session is None:
        session = SessionLocal()
        own_session = True

    try:
        existing = session.query(Reasoning).filter_by(message_id=message_id).first()
        if existing:
            existing.content = content
            session.commit()
            session.refresh(existing)
            return existing

        entry = Reasoning(message_id=message_id, content=content)
        session.add(entry)
        session.commit()
        session.refresh(entry)
        return entry
    finally:
        if own_session:
            session.close()


def get_reasoning_by_message_id(message_id: str) -> Optional[str]:
    session: Session = SessionLocal()
    try:
        entry = session.query(Reasoning).filter_by(message_id=message_id).first()
        return entry.content if entry else None
    finally:
        session.close()


def get_history(character_id: str, limit: int = 20):
    """Получение истории сообщений"""
    session: Session = SessionLocal()
    try:
        return (
            session.query(History)
            .options(joinedload(History.reasoning))
            .filter_by(character_id=character_id)
            .order_by(History.timestamp.desc())
            .limit(limit)
            .all()
        )
    finally:
        session.close()


def delete_message(message_id: str) -> bool:
    """Удаление одного сообщения по ID"""
    session: Session = SessionLocal()
    try:
        message = (
            session.query(History)
            .options(joinedload(History.reasoning))
            .filter_by(id=message_id)
            .first()
        )
        if not message:
            return False

        session.delete(message)
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"Error deleting message {message_id}: {e}")
        return False
    finally:
        session.close()


def delete_message_chain(user_message_id: str) -> int:
    """Удаление цепочки сообщений (пользователь + ассистент)"""
    session: Session = SessionLocal()
    try:
        # Находим пользовательское сообщение
        user_msg = (
            session.query(History)
            .options(joinedload(History.reasoning))
            .filter_by(id=user_message_id)
            .first()
        )
        if not user_msg or user_msg.role != "user":
            return 0

        # Находим следующее сообщение ассистента
        assistant_msg = (
            session.query(History)
            .options(joinedload(History.reasoning))
            .filter(
                History.character_id == user_msg.character_id,
                History.timestamp > user_msg.timestamp,
                History.role == "assistant",
            )
            .order_by(History.timestamp.asc())
            .first()
        )

        count = 0
        session.delete(user_msg)
        count += 1

        if assistant_msg:
            session.delete(assistant_msg)
            count += 1

        session.commit()
        return count
    except Exception as e:
        session.rollback()
        print(f"Error deleting message chain {user_message_id}: {e}")
        return 0
    finally:
        session.close()


def get_message_by_id(message_id: str):
    """Получение сообщения по ID"""
    session: Session = SessionLocal()
    try:
        message = session.query(History).filter_by(id=message_id).first()
        if not message:
            return None

        return {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "timestamp": format_user_datetime(message.timestamp),
            "character_id": message.character_id,
        }
    finally:
        session.close()


def get_full_history(character_id: str):
    """Получение полной истории"""
    session: Session = SessionLocal()
    try:
        messages = (
            session.query(History)
            .filter_by(character_id=character_id)
            .order_by(History.timestamp.asc())
            .all()
        )

        return [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "timestamp": format_user_datetime(msg.timestamp),
            }
            for msg in messages
        ]
    finally:
        session.close()


def get_last_user_message_time(character_id: str):
    """Получение времени последнего сообщения пользователя"""
    session: Session = SessionLocal()
    try:
        last_user_msg = (
            session.query(History)
            .filter_by(character_id=character_id, role="user")
            .order_by(History.timestamp.desc())
            .first()
        )

        return last_user_msg.timestamp if last_user_msg else None
    finally:
        session.close()


def get_last_messages(character_id: str, limit: int = 10):
    """Получение последних сообщений"""
    session: Session = SessionLocal()
    try:
        messages = (
            session.query(History)
            .filter_by(character_id=character_id)
            .order_by(History.timestamp.desc())
            .limit(limit)
            .all()
        )

        return [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "timestamp": format_user_datetime(msg.timestamp),
            }
            for msg in reversed(messages)
        ]
    finally:
        session.close()


# =========================
# REROLL функционал
# =========================
def get_message_from_database(session, filters: dict, expected_role: str = None):
    """Получение сообщения по фильтрам"""
    query = session.query(History).filter_by(**filters)
    result = query.first()

    if not result:
        raise ValueError("Message not found.")

    if expected_role and result.role != expected_role:
        raise ValueError(
            f"Message found, but role '{result.role}' does not match expected '{expected_role}'."
        )

    return result


def get_last_user_message_before(session, character_id, before_timestamp):
    """Получение последнего пользовательского сообщения до определенного времени"""
    result = (
        session.query(History)
        .filter(
            History.character_id == character_id,
            History.timestamp < before_timestamp,
            History.role == "user",
        )
        .order_by(History.timestamp.desc())
        .first()
    )

    if not result:
        raise ValueError("No matching user message found.")

    return result


def delete_messages_from_database(session, messages: list):
    """Удаление списка сообщений"""
    try:
        for msg in messages:
            session.delete(msg)
        session.commit()
    except Exception as e:
        session.rollback()
        raise


def build_history_up_to_user_message(session, character_id, user_msg, limit=32):
    """Сбор истории до пользовательского сообщения"""
    try:
        user_timestamp = user_msg.timestamp

        # Берем последние N сообщений ДО пользовательского сообщения
        history_before_user = (
            session.query(History)
            .filter(
                History.character_id == character_id, History.timestamp < user_timestamp
            )
            .order_by(History.timestamp.desc())
            .limit(limit)
            .all()
        )

        # Переворачиваем, чтобы время шло вперед
        history = [
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat(),
            }
            for msg in reversed(history_before_user)
        ]

        # Вставляем само пользовательское сообщение в конец
        history.append(
            {
                "role": "user",
                "content": user_msg.content,
                "timestamp": user_timestamp.isoformat(),
            }
        )

        return history

    except Exception as e:
        raise


async def reroll_assistant_message(message_id: str) -> dict:
    """Перегенерация сообщения ассистента"""
    session: Session = SessionLocal()
    try:
        print(f"[DEBUG] Reroll called with message_id: {message_id}")

        # 1. Ищем сообщение ассистента
        try:
            assistant_msg = get_message_from_database(
                session, filters={"id": message_id}, expected_role="assistant"
            )
            print(f"[DEBUG] Found assistant message: {assistant_msg.id}")
        except ValueError as e:
            print(f"[ERROR] Message not found: {e}")
            raise

        assistant_timestamp = assistant_msg.timestamp
        print(f"[DEBUG] Assistant timestamp: {assistant_timestamp}")

        # 2. Ищем соответствующее пользовательское сообщение
        user_msg = get_last_user_message_before(
            session,
            character_id=assistant_msg.character_id,
            before_timestamp=assistant_msg.timestamp,
        )
        print(f"[DEBUG] Found user message: {user_msg.id}")

        # 3. Удаляем сообщения
        print(
            "[DEBUG] Deleting assistant:",
            assistant_msg.id,
            "=>",
            assistant_msg.content[:30],
        )
        print("[DEBUG] Deleting user:", user_msg.id, "=>", user_msg.content[:30])
        delete_messages_from_database(session, [assistant_msg, user_msg])
        print(f"[DEBUG] Messages deleted")

        # Проверка — жив ли ассистент
        check = session.query(History).filter_by(id=assistant_msg.id).first()
        print("[DEBUG] Assistant still in DB?", check is not None)

        # Проверка — жив ли пользователь
        check = session.query(History).filter_by(id=user_msg.id).first()
        print("[DEBUG] User still in DB?", check is not None)

        # 4. Собираем историю до пользовательского сообщения
        history = build_history_up_to_user_message(
            session, character_id=user_msg.character_id, user_msg=user_msg, limit=32
        )
        print(f"[DEBUG] History built, length: {len(history)}")

        from services import api_service

        new_response = await api_service.run_standard(history=history, return_full=True)
        print(f"[DEBUG] New response generated")

        return {
            "role": "assistant",
            "content": new_response["content"],
            "timestamp": (
                new_response["timestamp"].isoformat()
                if hasattr(new_response["timestamp"], "isoformat")
                else str(new_response["timestamp"])
            ),
            "id": new_response["id"],
        }

    finally:
        session.close()


def get_lorebook_entries(character_name: str):
    """Получение записей из лорбука (заглушка)"""
    # TODO: реализовать работу с лорбуком
    return []
