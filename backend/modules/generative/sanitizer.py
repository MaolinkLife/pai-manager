from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List


_THINK_BLOCK_PATTERN = re.compile(
    r"<think(?:ing)?\b[^>]*>.*?</think(?:ing)?>",
    re.IGNORECASE | re.DOTALL,
)
_DANGLING_THINK_PATTERN = re.compile(
    r"<think(?:ing)?\b[^>]*>.*\Z",
    re.IGNORECASE | re.DOTALL,
)
_EXCESS_BLANK_LINES_PATTERN = re.compile(r"\n{3,}")
_INTERNAL_REASONING_FIELDS = {"reasoning", "thinking"}


def sanitize_generation_text(value: str) -> str:
    """Remove model-internal reasoning traces before they enter a new prompt."""
    if not value:
        return value

    cleaned = _THINK_BLOCK_PATTERN.sub("", value)
    cleaned = _DANGLING_THINK_PATTERN.sub("", cleaned)
    cleaned = _EXCESS_BLANK_LINES_PATTERN.sub("\n\n", cleaned)
    return cleaned.strip()


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_generation_text(value)
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_value(item) for key, item in value.items()}
    return value


def sanitize_generation_message(message: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = {
        key: value
        for key, value in message.items()
        if str(key).strip().lower() not in _INTERNAL_REASONING_FIELDS
    }
    if "content" in sanitized:
        sanitized["content"] = _sanitize_value(sanitized.get("content"))
    return sanitized


def sanitize_generation_messages(messages: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sanitized: List[Dict[str, Any]] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        sanitized.append(sanitize_generation_message(item))
    return sanitized
