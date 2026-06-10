"""Valence classifier and mismatch scorer.

Maps emotion / tone labels to coarse valence buckets (positive / negative
/ neutral). The mapping is deliberately broad — PAI's emotional vocabulary
varies between providers and prompts, so we accept any unknown label as
'neutral' rather than failing.
"""

from __future__ import annotations


_POSITIVE_LABELS = frozenset({
    # English
    "joy", "happy", "happiness", "love", "tenderness", "warmth", "warm",
    "amused", "amusement", "playful", "playfulness", "calm", "content",
    "pride", "proud", "curious", "curiosity", "excited", "excitement",
    "grateful", "gratitude", "affection", "satisfied", "satisfaction",
    "relief", "relieved", "positive",
    # Russian
    "радость", "радостный", "счастье", "любовь", "нежность", "теплота",
    "тёплый", "веселье", "игривость", "спокойствие", "довольство",
    "гордость", "любопытство", "благодарность", "удовлетворение",
    "облегчение", "интерес", "симпатия", "позитив",
})

_NEGATIVE_LABELS = frozenset({
    # English
    "anger", "angry", "frustration", "frustrated", "annoyed", "annoyance",
    "sadness", "sad", "grief", "lonely", "loneliness", "disappointment",
    "disappointed", "hurt", "resentment", "jealousy", "anxious", "anxiety",
    "fear", "afraid", "worry", "worried", "shame", "guilt", "disgust",
    "irritated", "irritation", "bitter", "bitterness", "hostile",
    "hostility", "contempt", "negative",
    # Russian
    "гнев", "злость", "раздражение", "фрустрация", "грусть", "печаль",
    "тоска", "одиночество", "разочарование", "обида", "ревность",
    "тревога", "страх", "беспокойство", "стыд", "вина", "отвращение",
    "негодование", "горечь", "враждебность", "презрение", "негатив",
})


def classify_valence(label: str) -> str:
    """Coarse valence bucket for an emotion / tone label.

    Returns one of: 'positive', 'negative', 'neutral'. Unknown labels
    default to 'neutral' — we'd rather under-detect mismatches than
    fire false positives on labels we don't know.
    """
    text = str(label or "").strip().lower()
    if not text:
        return "neutral"
    if text in _POSITIVE_LABELS:
        return "positive"
    if text in _NEGATIVE_LABELS:
        return "negative"
    return "neutral"


def score_mismatch(
    *,
    predicted_valence: str,
    actual_valence: str,
    predicted_intensity: float = 0.5,
    actual_intensity: float = 0.5,
) -> float:
    """Compute a mismatch score in [0.0, 1.0].

      * Same valence → 0.0 (no mismatch)
      * One side neutral + the other not → mild mismatch (~0.3)
      * Positive vs negative → strong mismatch, scaled by intensities

    Intensities default to 0.5 when callers don't have one; they amplify
    a hard opposition (positive vs negative) toward 1.0.
    """
    p = str(predicted_valence or "").strip().lower()
    a = str(actual_valence or "").strip().lower()

    if not p or not a:
        return 0.0
    if p == a:
        return 0.0

    pi = max(0.0, min(1.0, float(predicted_intensity or 0.0)))
    ai = max(0.0, min(1.0, float(actual_intensity or 0.0)))
    avg = (pi + ai) / 2.0

    if "neutral" in (p, a):
        # One side is neutral — mild signal. Scale by the non-neutral
        # intensity so a calm response to a hot turn still registers.
        non_neutral_intensity = ai if p == "neutral" else pi
        return round(0.2 + 0.4 * non_neutral_intensity, 4)

    # Hard opposition (positive vs negative).
    return round(0.6 + 0.4 * avg, 4)
