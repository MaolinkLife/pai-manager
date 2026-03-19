"""Utility for loading character system prompts (DB-first)."""

from __future__ import annotations

from services import character_service, config_service
from services.logger_service import AuditStatus, log_audit_entry


def load_system_prompt() -> str:
    char_name = character_service.resolve_active_character_name_for_user(
        config_service.get_active_user_uuid(),
        fallback_char_name="default",
    )
    try:
        prompt = character_service.get_character_prompt(char_name)
        if prompt:
            return prompt
        log_audit_entry(
            event_type="character_prompt_not_found",
            msg="[PromptLoader]: Character prompt not found",
            status=AuditStatus.ERROR,
            details={"char_name": char_name},
        )
        return "[System Error] Character prompt not found."
    except Exception as exc:  # pragma: no cover
        log_audit_entry(
            event_type="prompt_loading_failed",
            msg="[PromptLoader]: Prompt loading failed",
            status=AuditStatus.ERROR,
            details={"error": str(exc)},
        )
        return "[System Error] Prompt loading failed."
