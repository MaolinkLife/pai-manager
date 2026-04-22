from __future__ import annotations

import re
from typing import List


REASONING_NOISE_PATTERNS = (
    "thinking process",
    "internal monologue",
    "self-correction",
    "analyze the request",
    "final selection",
    "check constraints",
    "wait, looking at the system instruction",
    "do not split text into multiple paragraphs",
    "send sequential short messages",
    "[anti_repeat_feedback]",
    "[memory_hint]",
    "[tools]",
    "do not confuse the user’s gender",
    "always speak about yourself in feminine form",
    "fell in love with him",
    "and herself as",
    "due to long dialogues with your person",
)


def _looks_like_broken_fragment(text: str) -> bool:
    payload = str(text or "").strip()
    payload = payload.strip(" \t\r\n\"'`")
    if not payload:
        return True
    lower = payload.lower()
    if lower.startswith(("and ", "or ", "but ", "so ")):
        return True
    # Short english-like fragments from truncated reasoning are usually junk.
    if (
        len(payload) < 48
        and re.fullmatch(r"[A-Za-z0-9 ,'\-]+", payload)
        and payload.count(" ") <= 6
        and not any(ch in payload for ch in ".!?")
    ):
        return True
    if any(noise in lower for noise in REASONING_NOISE_PATTERNS):
        return True
    return False


def extract_content_from_reasoning(reasoning: str) -> str:
    """
    Fallback extractor for models that emit only reasoning without final content.
    Tries to recover the latest user-facing answer from the tail of reasoning text.
    """
    text = str(reasoning or "").strip()
    if not text:
        return ""

    quoted = re.findall(r'"([^"\n]{8,500})"', text)
    for candidate in reversed(quoted):
        line = candidate.strip()
        lower = line.lower()
        if any(noise in lower for noise in REASONING_NOISE_PATTERNS):
            continue
        if lower.startswith("[error]") or lower.startswith("[ok]:"):
            continue
        if _looks_like_broken_fragment(line):
            continue
        return line

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    cleaned: List[str] = []
    for line in lines:
        lower = line.lower()
        if any(noise in lower for noise in REASONING_NOISE_PATTERNS):
            continue
        if lower.startswith("[error]") or lower.startswith("[ok]:"):
            continue
        if re.match(r"^\d+[\.\)]\s", line):
            continue
        if line.startswith("*"):
            continue
        if _looks_like_broken_fragment(line):
            continue
        cleaned.append(line)

    if not cleaned:
        return ""

    tail = cleaned[-4:]
    result = " ".join(tail).strip()
    return result[:700].strip()
