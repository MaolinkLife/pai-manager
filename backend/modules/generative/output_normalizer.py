from __future__ import annotations

import re
from typing import Optional

from modules.system import config as config_service


SINGLE_ASTERISK_BLOCK_RE = re.compile(
    r"(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)",
    re.DOTALL,
)


def is_output_normalization_enabled() -> bool:
    return bool(config_service.get_config_value("generate_settings.normalize_messages", False))


def normalize_output_text(text: str, *, enabled: Optional[bool] = None) -> str:
    if enabled is None:
        enabled = is_output_normalization_enabled()
    if not enabled:
        return str(text or "")

    cleaned = SINGLE_ASTERISK_BLOCK_RE.sub("", str(text or ""))
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n[ \t]+", "\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


class StreamingOutputNormalizer:
    def __init__(self, *, enabled: Optional[bool] = None) -> None:
        self.enabled = is_output_normalization_enabled() if enabled is None else bool(enabled)
        self._inside_asterisk_block = False
        self._last_output_char = ""

    def feed(self, chunk: str) -> str:
        text = str(chunk or "")
        if not self.enabled or not text:
            return text

        output: list[str] = []
        for index, char in enumerate(text):
            if char == "*" and not self._is_double_asterisk(text, index):
                self._inside_asterisk_block = not self._inside_asterisk_block
                continue
            if self._inside_asterisk_block:
                continue
            output.append(char)

        cleaned = "".join(output)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        if self._last_output_char.isspace():
            cleaned = cleaned.lstrip(" \t")
        if cleaned:
            self._last_output_char = cleaned[-1]
        return cleaned

    def normalize_final(self, text: str) -> str:
        return normalize_output_text(text, enabled=self.enabled)

    @staticmethod
    def _is_double_asterisk(text: str, index: int) -> bool:
        return (
            (index > 0 and text[index - 1] == "*")
            or (index + 1 < len(text) and text[index + 1] == "*")
        )
