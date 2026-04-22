from sqlalchemy import (
    Column,
    String,
    Text,
    DateTime,
    ForeignKey,
    Boolean,
    Integer,
    Float,
    Date,
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid
from modules.database.core import Base


# Character Table
class Character(Base):
    __tablename__ = "characters"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, unique=True, index=True, nullable=False)
    configs = Column(Text, default="{}")  # JSON as a string
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    history = relationship("History", back_populates="character")


# History table
class History(Base):
    __tablename__ = "history"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    character_id = Column(String, ForeignKey("characters.id"), nullable=False)
    role = Column(String, nullable=False)  # 'user' / 'assistant'
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.now(timezone.utc))
    tags = Column(Text, default='[]')
    runtime_meta = Column(Text, default='{}')

    character = relationship("Character", back_populates="history")
    reasoning = relationship(
        "Reasoning",
        back_populates="message",
        uselist=False,
        cascade="all, delete-orphan",
    )
    media = relationship(
        "Storage",
        back_populates="message",
        cascade="all, delete-orphan",
    )


# =======================
# Users
# =======================
class User(Base):
    __tablename__ = "users"

    uuid = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    trust_level = Column(Integer, default=0)  # 0=anon, 1=friend, 2=owner
    email = Column(String, unique=True, index=True, nullable=True)
    login = Column(String, unique=True, index=True, nullable=True)
    password_hash = Column(String, nullable=True)
    role = Column(String, nullable=False, default="anonymous")
    auth_provider = Column(String, nullable=False, default="local")
    is_active = Column(Boolean, default=True)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    settings = relationship(
        "UserSettings",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    sessions = relationship(
        "AuthSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    config = relationship(
        "UserConfig",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    tts_settings = relationship(
        "UserTtsSettings",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    vision_settings = relationship(
        "UserVisionSettings",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )


# =======================
# Messages
# =======================
class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.uuid"), nullable=False)
    dialog_id = Column(String, nullable=True)  # group messages by dialog
    role = Column(String, nullable=False)  # 'user' / 'assistant'
    content = Column(Text, nullable=False)  # plain text for now; encryption later
    volatile = Column(Boolean, default=False)  # temporary message
    timestamp = Column(DateTime, default=datetime.now(timezone.utc))
    tags = Column(Text, default='[]')

    user = relationship("User")


class UserSettings(Base):
    __tablename__ = "user_settings"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_uuid = Column(
        String,
        ForeignKey("users.uuid", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    active_character_id = Column(
        String,
        ForeignKey("characters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    language = Column(String, default="en-US")
    timezone_name = Column("timezone", String, default="UTC")
    ui_prefs = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User", back_populates="settings")
    active_character = relationship("Character")


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_uuid = Column(String, ForeignKey("users.uuid", ondelete="CASCADE"), nullable=False)
    refresh_token_hash = Column(String, nullable=False, index=True)
    user_agent = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User", back_populates="sessions")


class UserConfig(Base):
    __tablename__ = "user_configs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_uuid = Column(
        String,
        ForeignKey("users.uuid", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    config_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User", back_populates="config")


class UserTtsSettings(Base):
    __tablename__ = "user_tts_settings"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_uuid = Column(
        String,
        ForeignKey("users.uuid", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    settings_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User", back_populates="tts_settings")


class UserVisionSettings(Base):
    __tablename__ = "user_vision_settings"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_uuid = Column(
        String,
        ForeignKey("users.uuid", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    settings_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User", back_populates="vision_settings")



class ShortTermMemory(Base):
    __tablename__ = "short_term_memory"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    summary = Column(Text, nullable=False)
    dialogue_ids = Column(Text, nullable=False)
    themes = Column(Text, default='[]')
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class Storage(Base):
    __tablename__ = "storage"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id = Column(
        String, ForeignKey("history.id", ondelete="CASCADE"), nullable=False
    )
    file_name = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    mime_type = Column(String, nullable=False, default="application/octet-stream")
    size = Column(Integer, default=0)
    category = Column(String, nullable=False, default="other")
    description = Column(Text, nullable=True)
    meta = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    message = relationship("History", back_populates="media")


class Reasoning(Base):
    __tablename__ = "reasoning"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id = Column(
        String,
        ForeignKey("history.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    message = relationship("History", back_populates="reasoning")


class LorebookEntry(Base):
    __tablename__ = "lorebook_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String, nullable=False, default="Untitled")
    content = Column(Text, nullable=False)
    keywords = Column(Text, default="")
    category = Column(String, default="general")
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class EmotionalTrace(Base):
    __tablename__ = "emotional_traces"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    character_id = Column(String, ForeignKey("characters.id"), nullable=False)
    message_id = Column(String, ForeignKey("history.id", ondelete="SET NULL"))
    trigger_role = Column(String, nullable=False, default="assistant")
    primary_emotion = Column(String, nullable=False, default="neutral")
    secondary_emotion = Column(String, nullable=True)
    intensity = Column(Float, default=0.0)
    emotion_vector = Column(Text, default="{}")  # JSON blob with intensities
    user_tone = Column(String, nullable=True)
    cause = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    character = relationship("Character")
    message = relationship("History")


class DailyMoralSummary(Base):
    __tablename__ = "daily_moral_summaries"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    character_id = Column(String, ForeignKey("characters.id"), nullable=False)
    date = Column(Date, nullable=False)
    dominant_emotion = Column(String, nullable=False, default="neutral")
    average_intensity = Column(Float, default=0.0)
    emotion_vector = Column(Text, default="{}")
    trust = Column(Float, default=0.5)
    stability = Column(Float, default=0.5)
    sociability = Column(Float, default=0.5)
    resentment = Column(Float, default=0.0)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    character = relationship("Character")


class MoralStateSnapshot(Base):
    __tablename__ = "moral_state_snapshots"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    character_id = Column(String, ForeignKey("characters.id"), nullable=False)
    message_id = Column(String, ForeignKey("history.id", ondelete="SET NULL"))
    trust = Column(Float, default=0.5)
    stability = Column(Float, default=0.5)
    sociability = Column(Float, default=0.5)
    resentment = Column(Float, default=0.0)
    mood = Column(String, nullable=False, default="neutral")
    recommendations = Column(Text, default="[]")  # JSON array
    hard_directives = Column(Text, default="[]")  # JSON array
    meta = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    character = relationship("Character")
    message = relationship("History")


class ConversationStateLog(Base):
    __tablename__ = "conversation_state_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    character_id = Column(String, ForeignKey("characters.id", ondelete="SET NULL"))
    message_id = Column(String, nullable=True, index=True)
    source = Column(String, nullable=False, default="memory_module")
    last_message_at = Column(DateTime, nullable=True)
    hours_since_last_message = Column(Float, nullable=True)
    inactivity_bucket = Column(String, nullable=False, default="unknown")
    last_topic = Column(Text, nullable=False, default="")
    recent_tone_summary = Column(Text, nullable=False, default="neutral")
    payload = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.now(timezone.utc), index=True)

    character = relationship("Character")
