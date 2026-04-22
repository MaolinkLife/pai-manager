import uuid

from sqlalchemy.orm import Session

from models.models import User
from modules.database.core import SessionLocal


def get_or_create_user(name: str, trust_level: int = 0):
    session: Session = SessionLocal()
    try:
        user = session.query(User).filter_by(name=name).first()
        if user:
            return user

        new_user = User(uuid=str(uuid.uuid4()), name=name, trust_level=trust_level)
        session.add(new_user)
        session.commit()
        session.refresh(new_user)
        return new_user
    finally:
        session.close()


def get_owner():
    session: Session = SessionLocal()
    try:
        return session.query(User).filter_by(trust_level=2).first()
    finally:
        session.close()
