import re
from typing import Dict, List

EMOTION_KEYWORDS = {
    "грусть": ["печально", "жаль", "одиноко", "слёзы", "не хватает", "тоска"],
    "радость": ["счастлив", "рад", "ура", "восторг", "приятно", "улыбка"],
    "злость": ["ненавижу", "раздражает", "бесит", "злой", "убил бы", "ярость"],
    "любовь": ["дорога", "люблю", "нравишься", "значишь", "ценю", "не безразлична"],
    "страх": ["боюсь", "страшно", "тревожно", "опасаюсь", "паника", "дрожь"]
}

INTENT_PATTERNS = {
    "признание": r"(люблю|нравишься|дорога|значишь|ценю)",
    "угроза": r"(убью|разнесу|уничтожу|поквитаюсь)",
    "вопрос": r"(ты\s+знаешь|можешь|почему|зачем|что если)",
    "обида": r"(всегда так|опять|ты даже не|как всегда|обидно)",
    "забота": r"(волнуешься|тебе важно|позаботиться|будь осторожна)"
}

POLARITY_MAP = {
    "sadness": "negative",
    "gladness": "positive",
    "anger": "negative",
    "love": "positive",
    "fear": "negative"
}

def analyze_emotion(text: str) -> Dict:
    text_lower = text.lower()

    detected_emotions: List[str] = []
    for emotion, keywords in EMOTION_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            detected_emotions.append(emotion)

    tone = "neutral"
    if "love" in detected_emotions and "sadness" in detected_emotions:
        tone = "sadness with a warm undertone"
    elif "sadness" in detected_emotions:
        tone = "sad"
    elif "gladness" in detected_emotions:
        tone = "glad"
    elif "anger" in detected_emotions:
        tone = "irritated"
    elif "love" in detected_emotions:
        tone = "warm"
    elif "fear" in detected_emotions:
        tone = "anxious"

    intent = "undefined"
    for label, pattern in INTENT_PATTERNS.items():
        if re.search(pattern, text_lower):
            intent = label
            break

    polarity_scores = [POLARITY_MAP.get(e, "neutral") for e in detected_emotions]
    dominant_polarity = "neutral"
    if polarity_scores:
        pos = polarity_scores.count("positive")
        neg = polarity_scores.count("negative")
        if pos > neg:
            dominant_polarity = "positive"
        elif neg > pos:
            dominant_polarity = "negative"

    return {
        "tone": tone,
        "intent": intent,
        "confidence": round(min(1.0, len(detected_emotions) * 0.25), 2),
        "meta": {
            "detected_emotions": detected_emotions,
            "dominant_emotions": detected_emotions[:2],
            "secondary_emotions": detected_emotions[2:],
            "polarity": dominant_polarity
        }
    }

def generate_instruction(analysis: Dict) -> str:
    tone = analysis["tone"]
    polarity = analysis["meta"]["polarity"]
    primary = ", ".join(analysis["meta"]["dominant_emotions"])
    secondary = ", ".join(analysis["meta"]["secondary_emotions"])
    
    description = f"You feel {primary} ({polarity} emotions)"
    if secondary:
        description += f", also present {secondary}."
    description += f" Answer in tone: {tone}."
    return description
