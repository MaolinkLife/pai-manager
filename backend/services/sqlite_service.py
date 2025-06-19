# ===========================================================
# Module: sqlite_service.py
# Purpose: SQLite database management:
# table creation, connection, sessions.
# Used in: database_service.py
# Features:
# - Uses SQLAlchemy ORM
# - Creates a DB file on first run
# - Tables: Characters, History (ready for extension)
# ========================================================

import os
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    create_engine, Column, String, Text, ForeignKey, DateTime
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

from services.logger_service import log_audit_entry, AuditStatus
from utils.time_utils import format_user_datetime

# Path to the database (will be created in storage/database/)
DB_PATH = os.path.join("storage", "database", "core.db")
DB_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False)
Base = declarative_base()


# Character Table
class Character(Base):
    __tablename__ = "characters"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, unique=True, index=True, nullable=False)
    configs = Column(Text, default="{}")  # JSON as a string
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    history = relationship("History", back_populates="character")


# History table
class History(Base):
    __tablename__ = "history"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    character_id = Column(String, ForeignKey("characters.id"), nullable=False)
    role = Column(String, nullable=False)  # 'user' / 'assistant'
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.now(timezone.utc))

    character = relationship("Character", back_populates="history")


# Initialize the database
def create_sqlite_database():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    Base.metadata.create_all(bind=engine)


def build_history_message(character_id, role, content, timestamp, message_id=None):
    message = History(
        id=message_id or str(uuid.uuid4()),
        character_id=character_id,
        role=role,
        content=content,
        timestamp=timestamp
    )

    log_audit_entry(
        event_type="History.BuildEntry",
        msg="Message object created",
        status=AuditStatus.INFO,
        details={
            "input": {
                "character_id": character_id,
                "role": role,
                "content": content,
                "timestamp": timestamp.isoformat() if timestamp else datetime.now(timezone.utc).isoformat(),
                "message_id": message_id
            },
            "output": {
                "id": message.id,
                "role": message.role
            }
        }
    )

    return message


def add_message_to_database_sqlite(session, message: History):
    try:
        session.add(message)
        session.commit()

        log_audit_entry(
            event_type="History.InsertEntry",
            msg="The message has been successfully added to the database.",
            status=AuditStatus.SUCCESS,
            details={
                "id": message.id,
                "character_id": message.character_id,
                "role": message.role,
                "content": message.content,
                "timestamp": message.timestamp.isoformat()
            }
        )

        return message

    except Exception as e:
        log_audit_entry(
            event_type="History.InsertEntry",
            msg="Error adding message to DB",
            status=AuditStatus.ERROR,
            details={
                "error": str(e),
                "message": {
                    "id": message.id,
                    "role": message.role
                }
            }
        )
        raise

def add_history_entry(character_name: str, role: str, content: str, timestamp: datetime,  message_id: str = None):
    session = SessionLocal()
    try:
        character = get_character_from_database(session, character_name)
        template = build_history_message(character.id, role, content, timestamp, message_id)
        message = add_message_to_database_sqlite(session, template)

        return {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "timestamp": format_user_datetime(message.timestamp)
        }
    finally:
        session.close()
        
        
def get_character_from_database(session, character_name: str):
    log_audit_entry(
        event_type="Character.Fetch",
        msg="Search for a character in the database",
        status=AuditStatus.INFO,
        details={"input": {"character_name": character_name}}
    )

    character = session.query(Character).filter(Character.name == character_name).first()

    if not character:
        log_audit_entry(
            event_type="Character.Fetch",
            msg="Character not found in the database",
            status=AuditStatus.ERROR,
            details={"input": {"character_name": character_name}}
        )
        raise ValueError(f"Персонаж '{character_name}' не найден.")

    log_audit_entry(
        event_type="Character.Fetch",
        msg="Character successfully retrieved from the database",
        status=AuditStatus.SUCCESS,
        details={
            "input": {"character_name": character_name},
            "output": {"character_id": character.id}
        }
    )

    return character
        
        
def get_or_create_character_sqlite(name: str):
    session = SessionLocal()
    try:
        character = session.query(Character).filter_by(name=name).first()
        if character:
            return character

        new_character = Character(id=str(uuid.uuid4()), name=name)
        session.add(new_character)
        session.commit()
        session.refresh(new_character)
        return new_character

    except IntegrityError:
        session.rollback()
        # In case of a race, let's try again
        return session.query(Character).filter_by(name=name).first()

    finally:
        log_audit_entry(
            event_type="create_new_char",
            msg=f"[SQLite Service]: Create New Character By Name: {name}",
            status=AuditStatus.INFO,
            details={
                "name": name
            },
            meta={
                "status": "info",
                "module": "sqlite"
            }
        )
        session.close()
        

def get_history_sqlite(character_name: str, limit: int = 20):
    session = SessionLocal()
    try:
        character = session.query(Character).filter_by(name=character_name).first()
        if not character:
            return []

        messages = (
            session.query(History)
            .filter_by(character_id=character.id)
            .order_by(History.timestamp.desc())
            .limit(limit)
            .all()
        )
        
        log_audit_entry(
            event_type="get_history_from_database",
            msg="[SQLite Service]: Getting history from the database for a character.",
            status=AuditStatus.INFO,
            details={
                "character_name": character_name,
                "limit": limit,
                "character": {
                    "id": character.id
                }
            },
            meta={
              "status": "info",
              "module": "sqlite"
            }
        )
        return [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "timestamp": format_user_datetime(msg.timestamp)
            }
            for msg in reversed(messages)
        ]
    finally:
        session.close()
        
        
def delete_message_sqlite(message_id: str) -> bool:
    session = SessionLocal()
    try:
        message = session.query(History).filter_by(id=message_id).first()
        if not message:
            return False

        session.delete(message)
        session.commit()
        return True
    finally:
        session.close()
        
        
def delete_message_chain_sqlite(user_message_id: str) -> int:
    session = SessionLocal()
    try:
        user_msg = session.query(History).filter_by(id=user_message_id).first()
        if not user_msg or user_msg.role != "user":
            return 0

        assistant_msg = (
            session.query(History)
            .filter(
                History.character_id == user_msg.character_id,
                History.timestamp > user_msg.timestamp,
                History.role == "assistant"
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
    finally:
        session.close()
        

def get_message_from_database_sqlite(session, filters: dict, expected_role: str = None, context: str = "GenericFetch"):
    log_audit_entry(
        event_type=f"History.{context}",
        msg=f"[SQLite Service]: Поиск сообщения по фильтру",
        status=AuditStatus.INFO,
        details={
            "input": filters,
            "expected_role": expected_role
        }
    )

    query = session.query(History).filter_by(**filters)
    result = query.first()

    if not result:
        log_audit_entry(
            event_type=f"History.{context}",
            msg="[SQLite Service]: Message not found",
            status=AuditStatus.ERROR,
            details={
                "input": filters,
                "expected_role": expected_role,
                "error": "No results for filter"
            }
        )
        raise ValueError("Message not found.")

    if expected_role and result.role != expected_role:
        log_audit_entry(
            event_type=f"History.{context}",
            msg="[SQLite Service]: The message found does not match the role",
            status=AuditStatus.ERROR,
            details={
                "input": filters,
                "expected": expected_role,
                "actual": result.role
            }
        )
        raise ValueError(f"Message found, but role '{result.role}' does not match expected '{expected_role}'.")

    log_audit_entry(
        event_type=f"History.{context}",
        msg="[SQLite Service]: Message successfully found",
        status=AuditStatus.SUCCESS,
        details={
            "input": filters,
            "output": {
                "id": result.id,
                "role": result.role,
                "timestamp": result.timestamp.isoformat(),
                "character_id": result.character_id,
                "content": result.content
            }
        }
    )

    return result  


def get_last_user_message_before(session, character_id, before_timestamp, context="FetchLastUserMessage"):
    log_audit_entry(
        event_type=f"History.{context}",
        msg="Find the last message of a user before a certain time",
        status=AuditStatus.INFO,
        details={
            "input": {
                "character_id": character_id,
                "before_timestamp": before_timestamp.isoformat(),
                "role": "user"
            }
        }
    )

    result = (
        session.query(History)
        .filter(
            History.character_id == character_id,
            History.timestamp < before_timestamp,
            History.role == "user"
        )
        .order_by(History.timestamp.desc())
        .first()
    )

    if not result:
        log_audit_entry(
            event_type=f"History.{context}",
            msg="No matching user message found",
            status=AuditStatus.ERROR,
            details={
                "input": {
                    "character_id": character_id,
                    "before_timestamp": before_timestamp.isoformat()
                }
            }
        )
        raise ValueError("No matching user message found.")

    log_audit_entry(
        event_type=f"History.{context}",
        msg="Last user message found",
        status=AuditStatus.SUCCESS,
        details={
            "output": {
                "id": result.id,
                "timestamp": result.timestamp.isoformat(),
                "content": result.content
            }
        }
    )

    return result
    
    

def delete_messages_from_database_sqlite(session, messages: list, context="DeletePairedMessages"):
    try:
        ids = []

        for msg in messages:
            ids.append(msg.id)
            session.delete(msg)

        session.commit()

        log_audit_entry(
            event_type=f"History.{context}",
            msg=f"[SQLite Service]: {len(messages)} messages removed from database",
            status=AuditStatus.SUCCESS,
            details={
                "deleted_ids": ids
            }
        )

    except Exception as e:
        log_audit_entry(
            event_type=f"History.{context}",
            msg=f"[SQLite Service]: Error deleting messages",
            status=AuditStatus.ERROR,
            details={
                "error": str(e),
                "attempted_delete_ids": [msg.id for msg in messages]
            }
        )
        raise
    

def build_history_up_to_user_message(session, character_id, user_msg, limit=32, context="BuildBeforeUserHistory"):
    try:
        user_timestamp = user_msg.timestamp

        # Take the last N messages BEFORE user_msg
        history_before_user = (
            session.query(History)
            .filter(
                History.character_id == character_id,
                History.timestamp < user_timestamp
            )
            .order_by(History.timestamp.desc())
            .limit(limit)
            .all()
        )

        # Turn it over so that the time is up
        history = [
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat()
            }
            for msg in reversed(history_before_user)
        ]

        # Insert user_msg itself at the end
        history.append({
            "role": "user",
            "content": user_msg.content,
            "timestamp": user_timestamp.isoformat()
        })

        log_audit_entry(
            event_type=f"History.{context}",
            msg=f"History collected up to user-message (limited by {limit})",
            status=AuditStatus.SUCCESS,
            details={
                "inputs": {
                    "character_id": character_id,
                    "before_timestamp": user_timestamp.isoformat(),
                    "limit": limit
                },
                "outputs": history
            }
        )

        return history

    except Exception as e:
        log_audit_entry(
            event_type=f"History.{context}",
            msg="Error collecting history",
            status=AuditStatus.ERROR,
            details={
                "error": str(e),
                "input": {
                    "character_id": character_id,
                    "before_timestamp": user_timestamp.isoformat(),
                    "limit": limit
                }
            }
        )
        raise


    except Exception as e:
        log_audit_entry(
            event_type=f"History.{context}",
            msg="Error collecting history",
            status=AuditStatus.ERROR,
            details={
                "error": str(e),
                "input": {
                    "character_id": character_id,
                    "before_timestamp": user_timestamp.isoformat()
                }
            }
        )
        raise


def reroll_assistant_message_sqlite(assistant_message_id: str) -> dict:
    session = SessionLocal()
    try:
        # 1. Search for assistant message
        assistant_msg = get_message_from_database_sqlite(
            session,
            filters={"id": assistant_message_id},
            expected_role="assistant",
            context="FetchAssistantMessage"
        )
        
        assistant_timestamp = assistant_msg.timestamp
        
        # 2. Search for the corresponding user message
        user_msg = get_last_user_message_before(
            session,
            character_id=assistant_msg.character_id,
            before_timestamp=assistant_msg.timestamp
        )

        # 3. Deleting messages
        delete_messages_from_database_sqlite(session, [assistant_msg, user_msg])

        # 4. Collecting history up to user_msg
        history = build_history_up_to_user_message(
            session,
            character_id=user_msg.character_id,
            user_msg=user_msg,
            limit=32
        )

        from services import api_service
        new_response = api_service.run_standard(history=history)
        
        return {
            "role": "assistant",
            "content": new_response,
            "timestamp": assistant_timestamp.isoformat()
        }

    finally:
        session.close()


def get_last_user_message_time_sqlite(character_name: str):
    session = SessionLocal()
    try:
        character = session.query(Character).filter_by(name=character_name).first()
        if not character:
            return None

        last_user_msg = (
            session.query(History)
            .filter_by(character_id=character.id, role="user")
            .order_by(History.timestamp.desc())
            .first()
        )

        return last_user_msg.timestamp if last_user_msg else None
    finally:
        session.close()
        

def get_message_pattern_sqlite(character_name: str, limit: int = 10):
    session = SessionLocal()
    try:
        character = session.query(Character).filter_by(name=character_name).first()
        if not character:
            return []

        messages = (
            session.query(History)
            .filter_by(character_id=character.id)
            .order_by(History.timestamp.desc())
            .limit(limit)
            .all()
        )

        # We collect messages in the order they were received
        return [
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp
            } for msg in reversed(messages)
        ]
    finally:
        session.close()
        
        
def get_message_by_id_sqlite(message_id: str):
    session = SessionLocal()
    try:
        message = session.query(History).filter_by(id=message_id).first()
        if not message:
            return None
        
        log_audit_entry(
            event_type="History.GetMessageById",
            msg="Message received by ID",
            status=AuditStatus.SUCCESS,
            details={
                "id": message.id,
                "role": message.role,
                "character_id": message.character_id
            }
        )

        return {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "timestamp": format_user_datetime(message.timestamp),
            "character_id": message.character_id
        }
    finally:
        session.close()
        

def get_full_history_sqlite(character_name: str):
    session = SessionLocal()
    try:
        character = session.query(Character).filter_by(name=character_name).first()
        if not character:
            return []

        messages = (
            session.query(History)
            .filter_by(character_id=character.id)
            .order_by(History.timestamp.asc())  # now from oldest to newest
            .all()
        )

        return [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "timestamp": format_user_datetime(msg.timestamp)
            }
            for msg in messages
        ]
    finally:
        session.close()