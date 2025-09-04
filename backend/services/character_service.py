# ==========================================================
# Module: character_service.py
# Purpose: CRUD for Character table
# ==========================================================

import uuid
from sqlalchemy.orm import Session
from models.models import Character
from services.db_core import SessionLocal


def get_or_create_character(name: str) -> Character:
    session: Session = SessionLocal()
    try:
        char = session.query(Character).filter_by(name=name).first()
        if char:
            return char
        new_char = Character(id=str(uuid.uuid4()), name=name)
        session.add(new_char)
        session.commit()
        session.refresh(new_char)
        return new_char
    finally:
        session.close()


def get_character(name: str) -> Character:
    session: Session = SessionLocal()
    try:
        return session.query(Character).filter_by(name=name).first()
    finally:
        session.close()
