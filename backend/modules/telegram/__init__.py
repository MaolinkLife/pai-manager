"""Telegram transport module (MTProto account mode via Telethon)."""

from .runtime import (
    autostart_telegram_bridge,
    get_telegram_bridge_status,
    ping_telegram_bridge,
    request_telegram_code,
    stop_telegram_bridge,
    submit_telegram_code,
    submit_telegram_password,
    telegram_bridge_runtime,
)

__all__ = [
    "autostart_telegram_bridge",
    "get_telegram_bridge_status",
    "ping_telegram_bridge",
    "request_telegram_code",
    "stop_telegram_bridge",
    "submit_telegram_code",
    "submit_telegram_password",
    "telegram_bridge_runtime",
]
