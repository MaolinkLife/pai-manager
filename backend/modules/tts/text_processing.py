from __future__ import annotations

import re
from typing import Any, Dict

import emoji


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _clean_text(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = emoji.replace_emoji(cleaned, replace="")
    cleaned = cleaned.replace("#", "")
    return cleaned


def _extract_quoted_text(text: str) -> str:
    patterns = [
        r'"([^"\n]+)"',
        r"“([^”\n]+)”",
        r"«([^»\n]+)»",
        r"„([^“\n]+)“",
    ]
    parts: list[str] = []
    for pattern in patterns:
        parts.extend(
            match.strip() for match in re.findall(pattern, text or "") if match.strip()
        )
    return "\n".join(parts)


def prepare_tts_text(text: str, cfg: Dict[str, Any] | None = None) -> str:
    config = dict(cfg or {})
    prepared = str(text or "")

    if _as_bool(config.get("skip_code_blocks", False)):
        prepared = re.sub(r"```.*?```", "", prepared, flags=re.DOTALL)
        prepared = re.sub(r"~~~.*?~~~", "", prepared, flags=re.DOTALL)
        prepared = re.sub(r"^\s{4}.*$", "", prepared, flags=re.MULTILINE)

    if _as_bool(config.get("skip_tagged_blocks", False)):
        prepared = re.sub(r"<[^>]+>[\s\S]*?</[^>]+>", "", prepared)
        prepared = re.sub(r"<[^>]+/>", "", prepared)

    if _as_bool(config.get("regex_filter_enabled", False)):
        pattern = str(config.get("regex_filter_pattern") or "").strip()
        if pattern:
            try:
                prepared = re.sub(pattern, "", prepared)
            except re.error:
                pass

    if _as_bool(config.get("skip_asterisk_text", False)):
        prepared = re.sub(r"\*(.*?)\*", "", prepared, flags=re.DOTALL)

    if _as_bool(config.get("only_quoted_speech", False)):
        prepared = _extract_quoted_text(prepared)

    prepared = _clean_text(prepared)
    prepared = re.sub(r"\s+\n", "\n", prepared)
    prepared = re.sub(r"\n{3,}", "\n\n", prepared)
    prepared = re.sub(r"[ \t]{2,}", " ", prepared)
    return prepared.strip()
