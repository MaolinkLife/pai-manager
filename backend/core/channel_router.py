from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from modules.system import config as config_service


KNOWN_CHANNELS = ("main_chat", "telegram")


def _default_policy() -> Dict[str, Any]:
    return {
        "priority": ["main_chat", "telegram"],
        "channels": {
            "main_chat": {"enabled": True, "allow_fallback": False},
            "telegram": {"enabled": True, "allow_fallback": False},
        },
    }


def get_policy() -> Dict[str, Any]:
    raw = config_service.get_config_value("communication", {}) or {}
    return normalize_policy(raw if isinstance(raw, dict) else {})


def normalize_policy(policy: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _default_policy()
    channels_raw = policy.get("channels")
    if isinstance(channels_raw, dict):
        for name in KNOWN_CHANNELS:
            channel_cfg = channels_raw.get(name)
            if not isinstance(channel_cfg, dict):
                continue
            normalized["channels"][name]["enabled"] = bool(
                channel_cfg.get("enabled", normalized["channels"][name]["enabled"])
            )
            normalized["channels"][name]["allow_fallback"] = bool(
                channel_cfg.get(
                    "allow_fallback",
                    normalized["channels"][name]["allow_fallback"],
                )
            )

    priority_raw = policy.get("priority")
    if isinstance(priority_raw, list):
        seen = set()
        priority: List[str] = []
        for item in priority_raw:
            channel = str(item or "").strip()
            if channel not in KNOWN_CHANNELS or channel in seen:
                continue
            seen.add(channel)
            priority.append(channel)
        for channel in KNOWN_CHANNELS:
            if channel not in seen:
                priority.append(channel)
        if priority:
            normalized["priority"] = priority

    return normalized


def enabled_channels(policy: Optional[Dict[str, Any]] = None) -> List[str]:
    effective = policy or get_policy()
    channels = effective.get("channels") if isinstance(effective, dict) else {}
    if not isinstance(channels, dict):
        return []
    out: List[str] = []
    for name in KNOWN_CHANNELS:
        cfg = channels.get(name)
        if isinstance(cfg, dict) and bool(cfg.get("enabled")):
            out.append(name)
    return out


def primary_channel(policy: Optional[Dict[str, Any]] = None) -> str:
    effective = policy or get_policy()
    priority = effective.get("priority") if isinstance(effective, dict) else None
    enabled = set(enabled_channels(effective))
    if isinstance(priority, list):
        for item in priority:
            name = str(item or "").strip()
            if name in enabled:
                return name
    return "main_chat" if "main_chat" in enabled else "telegram"


def can_accept_ingress(channel: str, policy: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    effective = policy or get_policy()
    channel_name = str(channel or "").strip()
    if channel_name not in KNOWN_CHANNELS:
        return False, "unknown_channel"

    channels = effective.get("channels") if isinstance(effective, dict) else {}
    channel_cfg = channels.get(channel_name) if isinstance(channels, dict) else {}
    if not isinstance(channel_cfg, dict) or not bool(channel_cfg.get("enabled")):
        return False, "channel_disabled"

    # Hard rule: if main chat is the current primary, telegram is excluded from routing.
    if channel_name == "telegram" and primary_channel(effective) == "main_chat":
        return False, "main_chat_priority_exclusive"

    return True, "ok"


def resolve_channel_with_fallback(
    preferred: str,
    *,
    availability: Optional[Dict[str, bool]] = None,
    policy: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[str], str]:
    effective = policy or get_policy()
    preferred_name = str(preferred or "").strip()
    if preferred_name not in KNOWN_CHANNELS:
        return None, "unknown_channel"

    allowed, reason = can_accept_ingress(preferred_name, effective)
    if not allowed:
        return None, reason

    availability_map = availability or {}
    if availability_map.get(preferred_name, True):
        return preferred_name, "ok"

    # Main chat as primary means no fallback to other channels by requirement.
    if primary_channel(effective) == "main_chat":
        return None, "main_chat_priority_no_fallback"

    channels = effective.get("channels") if isinstance(effective, dict) else {}
    preferred_cfg = channels.get(preferred_name) if isinstance(channels, dict) else {}
    if not isinstance(preferred_cfg, dict) or not bool(preferred_cfg.get("allow_fallback", False)):
        return None, "fallback_disabled"

    priority = effective.get("priority") if isinstance(effective, dict) else []
    if not isinstance(priority, list):
        priority = [name for name in KNOWN_CHANNELS]

    for candidate in priority:
        candidate_name = str(candidate or "").strip()
        if candidate_name == preferred_name:
            continue
        candidate_ok, _ = can_accept_ingress(candidate_name, effective)
        if not candidate_ok:
            continue
        if availability_map.get(candidate_name, True):
            return candidate_name, "fallback"

    return None, "fallback_unavailable"
