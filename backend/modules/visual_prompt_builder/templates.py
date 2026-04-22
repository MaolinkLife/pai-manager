from __future__ import annotations


def join_parts(parts: list[str]) -> str:
    return ", ".join(part.strip() for part in parts if str(part or "").strip())


STYLE_PRESET_PROMPTS: dict[str, str] = {
    "anime": (
        "classic 2D anime style, sharp cel shading, clean lineart, strong contrast, "
        "expressive anime face, stylized not realistic, soft cinematic lighting"
    ),
    "semi_real_anime": (
        "semi-real anime style, clean contours, soft skin texture, balanced cinematic light, "
        "high facial detail while preserving stylization"
    ),
    "illustration": (
        "high-quality digital illustration, painterly details, controlled contrast, cinematic atmosphere"
    ),
}


QUALITY_PROMPT = (
    "high quality, coherent anatomy, stable identity, consistent hairstyle and eye color, "
    "clean composition, soft filmic atmosphere"
)


DEFAULT_NEGATIVE_PROMPT = (
    "photorealistic, realistic skin pores, western cartoon, childlike, chibi, "
    "bad anatomy, extra fingers, extra limbs, deformed face, asymmetrical eyes, "
    "wrong hair color, wrong eye color, mirror selfie, third-person view, "
    "photographed from outside, full phone visible, watermark, text, signature"
)
