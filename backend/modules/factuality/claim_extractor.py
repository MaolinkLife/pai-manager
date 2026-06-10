"""Regex-based factual claim extractor.

We deliberately keep this CPU-only and primitive. It is meant to spot the
TYPES of statements that hallucinate most often (years, dates, numeric
quantities, named entities) and produce short query strings for the
lorebook lookup. False positives are fine — they just produce a memory
search that returns nothing.

LLM-based claim extraction is an option for later, but for MVP this is
enough — and it's free (no extra LLM call beyond §3.8 confidence).
"""

from __future__ import annotations

import re
from typing import List, Sequence


# Year mentions — most common factual hook in conversational output.
_YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")

# Dates in various separators: 12.03.1999, 12/03/99, 2024-01-15
_DATE_PATTERN = re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b")

# Numbers with units — both Latin and Cyrillic short units.
_NUMBER_UNIT_PATTERN = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*"
    r"(?:%|км|кг|г|м|мм|см|л|"
    r"GB|MB|KB|TB|km|kg|g|m|mm|cm|"
    r"°C|°F|years?|лет|года?|месяцев|дн(?:ей|я)|"
    r"USD|EUR|RUB|долл(?:аров)?|евро|руб(?:лей)?)"
    r"\b",
    re.IGNORECASE,
)

# Capitalized name-like phrase: 1-3 consecutive Title-case tokens (Latin or
# Cyrillic). Heuristic — produces noise (sentence-initial words trigger it),
# but the noise is filtered by min_length and dedup downstream.
_CAPITALIZED_PHRASE_PATTERN = re.compile(
    r"\b(?:[A-ZА-ЯЁ][a-zа-яё]+)(?:\s+(?:[A-ZА-ЯЁ][a-zа-яё]+|[a-zа-яё]+)){0,2}\b"
)


def extract_claims(
    text: str,
    *,
    max_claims: int = 8,
    min_length: int = 3,
    drop_sentence_initial: bool = True,
) -> List[str]:
    """Return a deduplicated list of short claim snippets.

    The output is shape-agnostic — it's just a list of query strings the
    lorebook lookup will try. Each claim is a literal substring of the
    input, not a structured triple — we don't need that for an MVP gate.
    """
    if not text or not text.strip():
        return []

    found: List[str] = []
    seen: set[str] = set()

    def _add(snippet: str) -> None:
        snippet = snippet.strip()
        if len(snippet) < min_length:
            return
        key = snippet.lower()
        if key in seen:
            return
        seen.add(key)
        found.append(snippet)

    for match in _YEAR_PATTERN.finditer(text):
        _add(match.group(0))
        if len(found) >= max_claims:
            return found

    for match in _DATE_PATTERN.finditer(text):
        _add(match.group(0))
        if len(found) >= max_claims:
            return found

    for match in _NUMBER_UNIT_PATTERN.finditer(text):
        _add(match.group(0))
        if len(found) >= max_claims:
            return found

    sentence_starts: set[int] = set()
    if drop_sentence_initial:
        # Mark every position that looks like the start of a sentence so
        # we can ignore "Сегодня" / "Today" / etc. (capitalized only
        # because of grammar, not because it's a proper noun).
        for sentence_match in re.finditer(r"(?:^|[.!?]\s+|\n+)", text):
            sentence_starts.add(sentence_match.end())

    for match in _CAPITALIZED_PHRASE_PATTERN.finditer(text):
        if drop_sentence_initial and match.start() in sentence_starts:
            continue
        phrase = match.group(0)
        # Filter out single short capitalized tokens — too noisy.
        if " " not in phrase and len(phrase) < 5:
            continue
        _add(phrase)
        if len(found) >= max_claims:
            return found

    return found


def has_factual_claims(text: str, *, min_length: int = 3) -> bool:
    """Cheap gate: True if at least one numeric / date / capitalized
    phrase is present. Used by the service to short-circuit lookups."""
    return bool(extract_claims(text, max_claims=1, min_length=min_length))
