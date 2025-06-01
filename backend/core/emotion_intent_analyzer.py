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
    "грусть": "негативная",
    "радость": "положительная",
    "злость": "негативная",
    "любовь": "положительная",
    "страх": "негативная"
}

def analyze_emotion(text: str) -> Dict:
    text_lower = text.lower()

    detected_emotions: List[str] = []
    for emotion, keywords in EMOTION_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            detected_emotions.append(emotion)

    tone = "нейтральный"
    if "любовь" in detected_emotions and "грусть" in detected_emotions:
        tone = "грусть с тёплым подтекстом"
    elif "грусть" in detected_emotions:
        tone = "печальный"
    elif "радость" in detected_emotions:
        tone = "радостный"
    elif "злость" in detected_emotions:
        tone = "раздражённый"
    elif "любовь" in detected_emotions:
        tone = "тёплый"
    elif "страх" in detected_emotions:
        tone = "тревожный"

    intent = "неопределено"
    for label, pattern in INTENT_PATTERNS.items():
        if re.search(pattern, text_lower):
            intent = label
            break

    polarity_scores = [POLARITY_MAP.get(e, "нейтральная") for e in detected_emotions]
    dominant_polarity = "нейтральная"
    if polarity_scores:
        pos = polarity_scores.count("положительная")
        neg = polarity_scores.count("негативная")
        if pos > neg:
            dominant_polarity = "положительная"
        elif neg > pos:
            dominant_polarity = "негативная"

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
    
    description = f"Ты ощущаешь {primary} ({polarity} эмоции)"
    if secondary:
        description += f", также присутствуют {secondary}."
    description += f" Отвечай в тоне: {tone}."
    return description
