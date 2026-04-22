from __future__ import annotations

from modules.system.logger import AuditStatus, log_audit_entry

telegram_bridge_runtime = None


def _get_runtime():
    global telegram_bridge_runtime
    if telegram_bridge_runtime is None:
        from .service import TelegramBridgeService

        telegram_bridge_runtime = TelegramBridgeService()
    return telegram_bridge_runtime


def autostart_telegram_bridge() -> bool:
    runtime = _get_runtime()
    started = runtime.start()
    if started:
        log_audit_entry(
            "telegram_bridge_autostart",
            "[TelegramBridge] Autostart enabled.",
            AuditStatus.INFO,
        )
    else:
        log_audit_entry(
            "telegram_bridge_autostart_skipped",
            "[TelegramBridge] Autostart skipped (disabled by config).",
            AuditStatus.INFO,
        )
    return started


def stop_telegram_bridge() -> bool:
    runtime = _get_runtime()
    was_running = runtime.is_running()
    runtime.stop()
    return was_running


def get_telegram_bridge_status() -> dict:
    runtime = _get_runtime()
    return runtime.get_status()


def ping_telegram_bridge(timeout: float = 8.0) -> dict:
    runtime = _get_runtime()
    return runtime.ping(timeout=timeout)


def request_telegram_code(phone_number: str | None = None, timeout: float = 15.0) -> dict:
    runtime = _get_runtime()
    return runtime.request_code(phone_number=phone_number, timeout=timeout)


def submit_telegram_code(code: str, timeout: float = 20.0) -> dict:
    runtime = _get_runtime()
    return runtime.submit_code(code=code, timeout=timeout)


def submit_telegram_password(password: str, timeout: float = 20.0) -> dict:
    runtime = _get_runtime()
    return runtime.submit_password(password=password, timeout=timeout)


def list_telegram_chats(
    *,
    limit: int = 200,
    include_blocked: bool = True,
    timeout: float = 15.0,
) -> dict:
    runtime = _get_runtime()
    return runtime.list_chats(
        limit=limit,
        include_blocked=include_blocked,
        timeout=timeout,
    )


def run_public_reflection_probe(
    *,
    source_chat_id: int | None = None,
    timeout: float = 45.0,
) -> dict:
    runtime = _get_runtime()
    return runtime.probe_public_reflection(
        source_chat_id=source_chat_id,
        timeout=timeout,
    )


def send_telegram_test_image(
    *,
    prompt: str | None = None,
    target_chat_id: int | None = None,
    caption: str | None = None,
    timeout: float = 120.0,
) -> dict:
    runtime = _get_runtime()
    return runtime.send_test_image(
        prompt=prompt,
        target_chat_id=target_chat_id,
        caption=caption,
        timeout=timeout,
    )
