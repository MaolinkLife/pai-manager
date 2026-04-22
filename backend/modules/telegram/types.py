from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

ChatKind = Literal["private", "group", "channel", "unknown"]
NotificationKind = Literal[
    "dialog_message",
    "public_post",
    "daily_digest_tick",
    "scheduled_checkin",
    "idle_reflection",
    "reflection_tick",
    "system",
]


@dataclass(slots=True)
class TelegramMessageEnvelope:
    chat_id: int
    message_id: int
    chat_kind: ChatKind
    chat_title: str = ""
    sender_id: Optional[int] = None
    sender_name: str = ""
    sender_username: str = ""
    text: str = ""
    media: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw: Any = None


@dataclass(slots=True)
class TelegramNotification:
    kind: NotificationKind
    source_chat_id: int
    source_message_id: int
    source_chat_kind: ChatKind
    source_chat_title: str = ""
    sender_id: Optional[int] = None
    sender_name: str = ""
    sender_username: str = ""
    text: str = ""
    media: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    runtime_meta: dict[str, Any] = field(default_factory=dict)
    raw: Any = None


@dataclass(slots=True)
class TelegramImageArtifact:
    image_bytes: bytes
    mime_type: str = "image/png"
    filename: str = ""
    prompt: str = ""
    description: str = ""
    caption: str = ""
    provider: str = ""
    model_id: str = ""
    width: int = 0
    height: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_notification_kind: str = ""


@dataclass(slots=True)
class TelegramReply:
    text: str
    reasoning: str = ""
    provider: str = ""
    raw: str = ""
    images: list[TelegramImageArtifact] = field(default_factory=list)
