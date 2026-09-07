"""Parsers for interaction-history archives exported from external services.

An archive is one session — a single chat on the source service. Parsing is
pure: nothing here touches the database, so a preview can be shown before the
user commits to the import.

Two shapes are recognised today:

``chatgpt_script``
    ``[{role, time, text}]`` produced by the browser console script we hand to
    the user. ``role`` is user / assistant / tool; ``time`` is unix seconds and
    may be missing.

``qa_pairs``
    ``[{question, answer}]`` — an older, hand-assembled shape with no
    timestamps at all. ``question`` is the user turn, ``answer`` is hers.
    Absolute time is unrecoverable, but the order of the array is the order the
    conversation happened in, and that is preserved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

FORMAT_CHATGPT_SCRIPT = "chatgpt_script"
FORMAT_QA_PAIRS = "qa_pairs"
FORMAT_UNKNOWN = "unknown"

PRECISION_EXACT = "exact"
PRECISION_UNKNOWN = "unknown"

ARTIFACT_IMAGE_CAPTION = "image_caption"

# The extraction script joined `content.parts` with newlines; object parts became
# the literal string below and their payload is gone for good.
_LOST_PART = re.compile(r"^(\[object Object\]\s*)+$")
_CAPTION = re.compile(r"Model caption:\s*(.+)", re.DOTALL)


@dataclass
class ParsedMessage:
    sequence: int
    role: str  # 'user' | 'assistant'
    content: str
    occurred_at: Optional[datetime]
    time_precision: str
    external_id: Optional[str] = None


@dataclass
class ParsedArtifact:
    sequence: int
    kind: str
    content: str
    occurred_at: Optional[datetime]
    time_precision: str
    source_name: Optional[str] = None
    # Sequence of the assistant turn this artifact belongs to, when derivable.
    # Resolved to a real message id at insert time.
    message_sequence: Optional[int] = None


@dataclass
class ParsedArchive:
    source_format: str
    messages: list[ParsedMessage] = field(default_factory=list)
    artifacts: list[ParsedArtifact] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


def detect_format(data: Any) -> str:
    """Identify the archive shape. Never raises — unknown input says so."""
    if not isinstance(data, list) or not data:
        return FORMAT_UNKNOWN
    sample = next((item for item in data if isinstance(item, dict)), None)
    if sample is None:
        return FORMAT_UNKNOWN
    keys = set(sample.keys())
    if {"question", "answer"} <= keys:
        return FORMAT_QA_PAIRS
    if "role" in keys and ("text" in keys or "content" in keys):
        return FORMAT_CHATGPT_SCRIPT
    return FORMAT_UNKNOWN


def _to_datetime(value: Any) -> Optional[datetime]:
    """Unix seconds -> aware datetime. Anything unusable becomes None, which is
    an honest 'unknown' rather than a guess."""
    if value in (None, "", 0):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _classify_tool(text: str) -> tuple[str, str]:
    """Return (kind, content) for a tool entry.

    Only image captions carry meaning worth keeping: they describe what she drew
    and let her later say "I made something like this back then". Saved-file
    paths point at a server that no longer exists, and service chatter is not
    memory — both are counted in stats and dropped.
    """
    body = (text or "").strip()
    if not body or _LOST_PART.match(body):
        return "lost_at_export", ""
    caption = _CAPTION.search(body)
    if caption:
        return ARTIFACT_IMAGE_CAPTION, caption.group(1).strip()
    if body.startswith("Generated images from the last"):
        return "image_saved_paths", ""
    return "service_noise", ""


def _parse_chatgpt_script(data: list[dict[str, Any]]) -> ParsedArchive:
    archive = ParsedArchive(source_format=FORMAT_CHATGPT_SCRIPT)
    stats = {
        "messages": 0,
        "without_time": 0,
        "artifacts_kept": 0,
        "artifacts_lost_at_export": 0,
        "artifacts_dropped": 0,
        "skipped_empty": 0,
    }
    sequence = 0
    last_assistant_sequence: Optional[int] = None

    for item in data:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        text = str(item.get("text") or item.get("content") or "")
        occurred_at = _to_datetime(item.get("time"))
        precision = PRECISION_EXACT if occurred_at else PRECISION_UNKNOWN

        if role in ("user", "assistant"):
            if not text.strip():
                stats["skipped_empty"] += 1
                continue
            archive.messages.append(
                ParsedMessage(
                    sequence=sequence,
                    role=role,
                    content=text,
                    occurred_at=occurred_at,
                    time_precision=precision,
                    external_id=str(item.get("id")) if item.get("id") else None,
                )
            )
            if role == "assistant":
                last_assistant_sequence = sequence
            stats["messages"] += 1
            if occurred_at is None:
                stats["without_time"] += 1
            sequence += 1
            continue

        if role == "tool":
            kind, content = _classify_tool(text)
            if kind == "lost_at_export":
                stats["artifacts_lost_at_export"] += 1
                continue
            if not content:
                stats["artifacts_dropped"] += 1
                continue
            archive.artifacts.append(
                ParsedArtifact(
                    sequence=sequence,
                    kind=kind,
                    content=content,
                    occurred_at=occurred_at,
                    time_precision=precision,
                    source_name=str(item.get("author_name")) if item.get("author_name") else None,
                    message_sequence=last_assistant_sequence,
                )
            )
            stats["artifacts_kept"] += 1
            sequence += 1

    archive.stats = stats
    return archive


def _parse_qa_pairs(data: list[dict[str, Any]]) -> ParsedArchive:
    """Hand-assembled question/answer pairs.

    No timestamps exist anywhere in this shape, so every turn is stored with
    `occurred_at = None`. The array order is the conversation order, so
    `sequence` still answers "this came after that" precisely.
    """
    archive = ParsedArchive(source_format=FORMAT_QA_PAIRS)
    stats = {"messages": 0, "without_time": 0, "skipped_empty": 0, "pairs": 0}
    sequence = 0

    for item in data:
        if not isinstance(item, dict):
            continue
        stats["pairs"] += 1
        for role, key in (("user", "question"), ("assistant", "answer")):
            text = str(item.get(key) or "")
            if not text.strip():
                stats["skipped_empty"] += 1
                continue
            archive.messages.append(
                ParsedMessage(
                    sequence=sequence,
                    role=role,
                    content=text,
                    occurred_at=None,
                    time_precision=PRECISION_UNKNOWN,
                )
            )
            stats["messages"] += 1
            stats["without_time"] += 1
            sequence += 1

    archive.stats = stats
    return archive


def parse_archive(data: Any, *, source_format: Optional[str] = None) -> ParsedArchive:
    """Parse an archive into messages and artifacts without touching the DB."""
    fmt = source_format or detect_format(data)
    if fmt == FORMAT_CHATGPT_SCRIPT:
        return _parse_chatgpt_script(data)
    if fmt == FORMAT_QA_PAIRS:
        return _parse_qa_pairs(data)
    return ParsedArchive(source_format=FORMAT_UNKNOWN, stats={"messages": 0})
