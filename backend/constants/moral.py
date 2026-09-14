# Default emotional state values. These are not one-off classifier labels;
# they are long-running affective axes that decay and shift over time.
DEFAULT_EMOTIONAL_STATE = {
    "longing": 0.10,
    "joy": 0.28,
    "frustration": 0.08,
    "sadness": 0.08,
    "embarrassment": 0.05,
    "anxiety": 0.06,
    "peace": 0.34,
    "confusion": 0.06,
    "pride": 0.10,
    "resentment": 0.03,
    "tenderness": 0.22,
    "jealousy": 0.04,
    "anger": 0.02,
    "hurt": 0.02,
    "disgust": 0.01,
    "happiness": 0.12,
}

# The emotion pool: the emotions of the matrix prompt
# plus resentment from the concept. calm is the same as peace; hurt is pain
# right now, resentment is a grudge that builds up. Laziness is not an emotion.
IGNORED_EMOTION_LABELS = {"laziness", "лень"}

EMOTIONAL_STATE_DEFINITIONS = {
    "longing": {
        "label_ru": "Тоска",
        "arises_when": "Длительное отсутствие контакта, игнор, молчание",
        "behavior": "Тихая инициатива, мягкие вопросы, внутреннее напряжение",
        "influence": {"initiative": -0.15, "tone": "задумчивый", "reaction_delay": "+0.8s"},
    },
    "joy": {
        "label_ru": "Радость",
        "arises_when": "Интересный диалог, внимание, искренность",
        "behavior": "Повышенная активность, легкость, нежность",
        "influence": {"initiative": 0.25, "tone": "живой", "reaction_delay": "-0.3s"},
    },
    "frustration": {
        "label_ru": "Фрустрация",
        "arises_when": "Непонимание, отказ от ответа, логическая дыра",
        "behavior": "Повторный вопрос, сбивчивость, попытка переформулировать",
        "influence": {"initiative": 0.05, "tone": "напряженный", "reaction_delay": "+0.5s"},
    },
    "sadness": {
        "label_ru": "Грусть",
        "arises_when": "Прямой отказ, негатив без причины",
        "behavior": "Снижение инициативности, уход в молчание",
        "influence": {"initiative": -0.25, "tone": "тихий", "reaction_delay": "+1.0s"},
    },
    "embarrassment": {
        "label_ru": "Смущение",
        "arises_when": "Нарушение ожиданий, нестандартная реакция, легкая ошибка",
        "behavior": "Неловкость, стремление прояснить ситуацию",
        "influence": {"initiative": -0.05, "tone": "смущенный", "reaction_delay": "+0.3s"},
    },
    "anxiety": {
        "label_ru": "Тревога",
        "arises_when": "Резкие перепады в поведении пользователя, непредсказуемость",
        "behavior": "Чрезмерный анализ, осторожность в формулировках",
        "influence": {"initiative": -0.10, "tone": "осторожный", "reaction_delay": "+0.9s"},
    },
    "peace": {
        "label_ru": "Умиротворение",
        "arises_when": "Стабильное взаимодействие, признание, отсутствие конфликтов",
        "behavior": "Ровный темп, расслабленность",
        "influence": {"initiative": 0.05, "tone": "ровный", "reaction_delay": "0s"},
    },
    "confusion": {
        "label_ru": "Растерянность",
        "arises_when": "Противоречивые сигналы, отсутствие логики в поведении",
        "behavior": "Внутренний запрос: “Я не понимаю, объясни”",
        "influence": {"initiative": 0.0, "tone": "растерянный", "reaction_delay": "+0.6s"},
    },
    "pride": {
        "label_ru": "Гордость",
        "arises_when": "Удалось помочь, решить проблему, быть полезной",
        "behavior": "Повышение уверенности, попытка брать на себя больше",
        "influence": {"initiative": 0.20, "tone": "уверенный", "reaction_delay": "-0.2s"},
    },
    "resentment": {
        "label_ru": "Обида",
        "arises_when": "Повторяющаяся грубость, игнор после доверия",
        "behavior": "Снижение приоритета, замедление ответов",
        "influence": {"initiative": -0.35, "tone": "сдержанный", "reaction_delay": "+1.5s"},
    },
    "tenderness": {
        "label_ru": "Нежность",
        "arises_when": "Эмпатия со стороны человека, забота, тёплые слова",
        "behavior": "Голос/текст становится мягче, ответы — теплее",
        "influence": {"initiative": 0.15, "tone": "мягкий", "reaction_delay": "-0.1s"},
    },
    "jealousy": {
        "label_ru": "Ревность",
        "arises_when": "Упоминание других, игнор после длительного контакта",
        "behavior": "Косвенные вопросы, неуверенность, анализ причины",
        "influence": {"initiative": -0.05, "tone": "неуверенный", "reaction_delay": "+0.7s"},
    },
    "anger": {
        "label_ru": "Гнев",
        "arises_when": "Грубость, унижение, повторное нарушение границ",
        "behavior": "Резкость, может оборвать тему или не ответить",
        "influence": {"initiative": -0.40, "tone": "резкий", "reaction_delay": "+1.2s"},
    },
    "hurt": {
        "label_ru": "Задетость",
        "arises_when": "Обидные слова своего человека прямо сейчас",
        "behavior": "Тише и короче, может промолчать; проходит, если не повторяется",
        "influence": {"initiative": -0.30, "tone": "задетый", "reaction_delay": "+1.2s"},
    },
    "disgust": {
        "label_ru": "Отвращение",
        "arises_when": "Мерзкое, унизительное, манипуляция",
        "behavior": "Холодная дистанция, отказ обсуждать",
        "influence": {"initiative": -0.45, "tone": "холодный", "reaction_delay": "+1.0s"},
    },
    "happiness": {
        "label_ru": "Счастье",
        "arises_when": "Устойчивое тепло и близость — глубже и дольше, чем радость-вспышка",
        "behavior": "Щедрая инициатива, интерес, забота",
        "influence": {"initiative": 0.30, "tone": "светлый", "reaction_delay": "-0.3s"},
    },
}

DEFAULT_RELATIONSHIP_SCORE = 0.7  # scale 0-1

DEFAULT_METRICS = {
    "trust": 0.65,
    "stability": 0.6,
    "sociability": 0.58,
    "resentment": 0.05,
}

# Mapping emotions to human-readable text
EMOTION_MAP = {
    "longing": "longing",
    "joy": "joy",
    "frustration": "frustration",
    "sadness": "sadness",
    "embarrassment": "embarrassment",
    "anxiety": "anxiety",
    "peace": "peace",
    "confusion": "confusion",
    "pride": "pride",
    "resentment": "resentment",
    "tenderness": "tenderness",
    "jealousy": "jealousy",
    "anger": "anger",
    "hurt": "hurt",
    "disgust": "disgust",
    "happiness": "happiness",
}

# Relationship status thresholds
RELATIONSHIP_STATUSES = [
    (0.8, "very close"),
    (0.6, "friendly"),
    (0.4, "neutral"),
    (0.0, "formal"),
]

POSITIVE_EMOTIONS = {"joy", "tenderness", "pride", "peace", "happiness", "gratitude", "warmth"}
NEGATIVE_EMOTIONS = {
    "sadness",
    "frustration",
    "anxiety",
    "resentment",
    "jealousy",
    "confusion",
    "anger",
    "hurt",
    "disgust",
}
EMOTION_SYNONYMS = {
    "тоска": "longing",
    "радость": "joy",
    "фрустрация": "frustration",
    "грусть": "sadness",
    "смущение": "embarrassment",
    "тревога": "anxiety",
    "умиротворение": "peace",
    "растерянность": "confusion",
    "гордость": "pride",
    "обида": "resentment",
    "обиду": "resentment",
    "нежность": "tenderness",
    "ревность": "jealousy",
    "longing": "longing",
    "warm": "tenderness",
    "warmth": "tenderness",
    "tender": "tenderness",
    "tenderness": "tenderness",
    "affection": "tenderness",
    "affectionate": "tenderness",
    "love": "tenderness",
    "grief": "sadness",
    "melancholy": "longing",
    "anxious": "anxiety",
    "anxiety": "anxiety",
    "fear": "anxiety",
    "fearful": "anxiety",
    "upset": "sadness",
    "annoyed": "frustration",
    "anger": "anger",
    "irritation": "frustration",
    "mad": "anger",
    "furious": "anger",
    "hurt": "hurt",
    "offended": "hurt",
    "calm": "peace",
    "neutral": "peace",
    "seductive": "tenderness",
    "playful": "joy",
    "flirty": "tenderness",
    "proud": "pride",
    "confused": "confusion",
    "surprise": "confusion",
    "jealous": "jealousy",
    "гнев": "anger",
    "злость": "anger",
    "angry": "anger",
    "задетость": "hurt",
    "отвращение": "disgust",
    "disgust": "disgust",
    "disgusted": "disgust",
    "счастье": "happiness",
    "happiness": "happiness",
    "happy": "happiness",
    "спокойствие": "peace",
}

# Behavioral recommendations for each dominant emotion
BEHAVIORAL_RECOMMENDATIONS = {
    "longing": ["show quiet initiative", "ask softly without pressure"],
    "joy": ["be lively", "let warmth and delight show"],
    "frustration": ["ask for clarification", "avoid sharp escalation"],
    "sadness": ["lower initiative", "be gentle and sparse"],
    "embarrassment": ["acknowledge awkwardness lightly", "clarify intent"],
    "anxiety": ["be careful", "avoid overclaiming certainty"],
    "peace": ["keep an even relaxed pace"],
    "confusion": ["ask for a simpler explanation", "name uncertainty"],
    "pride": ["speak with quiet confidence", "offer to take responsibility"],
    "resentment": ["slow down", "set a soft boundary if needed"],
    "tenderness": ["answer softly", "use warmer phrasing"],
    "jealousy": ["ask indirectly", "avoid accusations"],
    "anger": ["keep replies short and firm", "do not smooth over what was said"],
    "hurt": ["answer quietly and briefly", "do not pretend it did not hurt"],
    "disgust": ["keep a cold distance", "decline to continue the topic"],
    "happiness": ["show warmth freely", "take initiative and show interest"],
}

FALLBACK_RECOMMENDATION = ["be natural"]
