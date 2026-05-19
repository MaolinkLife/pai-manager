from modules.generative.output_normalizer import StreamingOutputNormalizer, normalize_output_text


def test_normalize_output_text_removes_single_asterisk_actions():
    text = "Привет. *поправляет наушники*\n\nЯ тут."

    assert normalize_output_text(text, enabled=True) == "Привет.\n\nЯ тут."


def test_normalize_output_text_keeps_double_asterisk_markdown():
    text = "Это **важно**, но *машет рукой* ответ остается."

    assert normalize_output_text(text, enabled=True) == "Это **важно**, но ответ остается."


def test_streaming_output_normalizer_removes_action_across_chunks():
    normalizer = StreamingOutputNormalizer(enabled=True)

    chunks = [
        normalizer.feed("Привет *поп"),
        normalizer.feed("равляет наушники*"),
        normalizer.feed(" я тут."),
    ]

    assert "".join(chunks).strip() == "Привет я тут."
