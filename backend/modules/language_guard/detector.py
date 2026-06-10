"""Unicode-script-based language detector.

We deliberately do not pull a heavy NLP dep (langdetect, pycld3, fasttext).
For PAI's use case the only question is "does the dominant script match
what the user expects" — full language classification is overkill.

Mapping: a coarse script bucket → list of locales that use it as primary.
A locale tag like 'ru-RU' is normalised to its lowercase prefix 'ru'.
"""

from __future__ import annotations

import unicodedata
from typing import Tuple

# Script bucket → locale prefixes that natively use it.
# A given output is "language-compatible" with the expected locale if its
# dominant script bucket includes that locale's prefix.
SCRIPT_TO_LOCALES: dict[str, frozenset[str]] = {
    "cyrillic": frozenset({"ru", "uk", "be", "bg", "sr", "mk", "kk", "ky"}),
    "latin": frozenset({
        "en", "de", "fr", "es", "it", "pt", "nl", "pl", "cs", "sk", "sv",
        "no", "da", "fi", "ro", "hu", "tr", "id", "ms", "vi", "et", "lv", "lt",
    }),
    "cjk": frozenset({"zh", "ja", "ko"}),
    "arabic": frozenset({"ar", "fa", "ur"}),
    "hebrew": frozenset({"he"}),
    "devanagari": frozenset({"hi", "mr", "ne"}),
    "thai": frozenset({"th"}),
    "greek": frozenset({"el"}),
}


def _classify(ch: str) -> str | None:
    """Return the script bucket name for a single character or None if it
    should not affect the count (digits, punctuation, spaces, symbols)."""
    if not ch:
        return None
    category = unicodedata.category(ch)
    # Letters only — Lu, Ll, Lo, Lt, Lm
    if not category.startswith("L"):
        return None

    code = ord(ch)
    # Hebrew before Arabic block check
    if 0x0590 <= code <= 0x05FF:
        return "hebrew"
    if 0x0600 <= code <= 0x06FF or 0x0750 <= code <= 0x077F or 0xFB50 <= code <= 0xFDFF:
        return "arabic"
    if 0x0400 <= code <= 0x04FF or 0x0500 <= code <= 0x052F:
        return "cyrillic"
    if 0x0900 <= code <= 0x097F:
        return "devanagari"
    if 0x0E00 <= code <= 0x0E7F:
        return "thai"
    if 0x0370 <= code <= 0x03FF:
        return "greek"
    # CJK: unified ideographs + hiragana + katakana + hangul
    if (
        0x4E00 <= code <= 0x9FFF
        or 0x3040 <= code <= 0x309F
        or 0x30A0 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
    ):
        return "cjk"
    # ASCII letters + extended Latin
    if (0x0041 <= code <= 0x005A) or (0x0061 <= code <= 0x007A) or (0x00C0 <= code <= 0x024F):
        return "latin"
    return None


def detect_dominant_script(text: str) -> Tuple[str, float, int]:
    """Return (script_bucket, dominance, counted_letters).

    dominance is the ratio of the winning script's letters over the total
    number of *classified* letters (whitespace/digits/punct ignored). When
    the text has no classifiable letters at all, returns ("", 0.0, 0).
    """
    if not text:
        return "", 0.0, 0

    counts: dict[str, int] = {}
    total = 0
    for ch in text:
        bucket = _classify(ch)
        if bucket is None:
            continue
        counts[bucket] = counts.get(bucket, 0) + 1
        total += 1

    if total == 0:
        return "", 0.0, 0

    winner = max(counts.items(), key=lambda kv: kv[1])
    bucket, count = winner
    return bucket, count / float(total), total


def locale_prefix(tag: str) -> str:
    """ru-RU → ru, en_us → en, '' → ''. Just the leading [a-z]+ token."""
    raw = str(tag or "").strip().lower()
    if not raw:
        return ""
    out: list[str] = []
    for ch in raw:
        if "a" <= ch <= "z":
            out.append(ch)
        else:
            break
    return "".join(out)


def is_script_compatible(script_bucket: str, expected_locale: str) -> bool:
    """True when the locale natively uses this script bucket."""
    if not script_bucket or not expected_locale:
        return False
    prefix = locale_prefix(expected_locale)
    if not prefix:
        return False
    locales = SCRIPT_TO_LOCALES.get(script_bucket, frozenset())
    return prefix in locales
