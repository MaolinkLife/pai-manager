from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list_of_dicts(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _transport_from_runtime(runtime_meta: Dict[str, Any]) -> Dict[str, Any]:
    transport = runtime_meta.get("transport")
    return transport if isinstance(transport, dict) else {}


@dataclass
class InputEnvelope:
    source: str = "main_chat"
    text: str = ""
    media: List[Dict[str, Any]] = field(default_factory=list)
    user: Dict[str, Any] = field(default_factory=dict)
    channel: Dict[str, Any] = field(default_factory=dict)
    runtime: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)
    message_id: Optional[str] = None
    message_type: str = "user_message"
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_message(cls, message: Dict[str, Any]) -> "InputEnvelope":
        payload = _as_dict(message)
        runtime = dict(_as_dict(payload.get("runtime_meta")))
        transport = _transport_from_runtime(runtime)
        source = str(
            payload.get("source")
            or runtime.get("source")
            or transport.get("name")
            or "main_chat"
        ).strip().lower() or "main_chat"

        channel = {
            "id": transport.get("chat_id") or runtime.get("chat_id"),
            "kind": transport.get("chat_kind") or runtime.get("chat_kind"),
            "title": transport.get("chat_title") or runtime.get("chat_title"),
            "transport": source,
        }
        user = {
            "actor_user_uuid": payload.get("actor_user_uuid") or runtime.get("actor_user_uuid"),
            "role": payload.get("actor_role") or runtime.get("actor_role"),
        }

        return cls(
            source=source,
            text=str(payload.get("content") or payload.get("text") or ""),
            media=_as_list_of_dicts(payload.get("media")),
            user={k: v for k, v in user.items() if v is not None},
            channel={k: v for k, v in channel.items() if v is not None},
            runtime=runtime,
            history=_as_list_of_dicts(payload.get("history")),
            message_id=str(payload.get("id")) if payload.get("id") is not None else None,
            message_type=str(payload.get("message_type") or "user_message"),
            raw=dict(payload),
        )

    def to_message(self) -> Dict[str, Any]:
        message = dict(self.raw)
        message["content"] = self.text
        message["media"] = [dict(item) for item in self.media]
        message["runtime_meta"] = dict(self.runtime)
        message["source"] = self.source
        message["message_type"] = self.message_type
        if self.message_id is not None:
            message["id"] = self.message_id
        if self.history:
            message["history"] = [dict(item) for item in self.history]
        actor_user_uuid = self.user.get("actor_user_uuid")
        if actor_user_uuid:
            message["actor_user_uuid"] = actor_user_uuid
        return message

    def to_audit_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "message_id": self.message_id,
            "message_type": self.message_type,
            "text_length": len(self.text),
            "media_count": len(self.media),
            "channel": self.channel,
            "user": self.user,
        }
