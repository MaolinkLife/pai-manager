from __future__ import annotations

import hashlib
from typing import Any

from .schemas import VisualProfile


def stable_fallback_appearance(profile: VisualProfile) -> str:
    seed = f"{profile.character_name}|{profile.style_preset}|{profile.render_profile}"
    digest = hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()

    hair_palette = [
        "long soft silver-blue hair",
        "long deep blue hair with subtle magenta tips",
        "dark violet hair with cool cyan accents",
        "long graphite-black hair with blue sheen",
    ]
    eye_palette = [
        "calm violet eyes",
        "bright purple eyes",
        "soft blue-violet eyes",
        "reflective cyan-violet eyes",
    ]
    vibe_palette = [
        "cozy cyber-home aesthetic",
        "soft futuristic home aesthetic",
        "warm neon apartment atmosphere",
        "quiet modern tech-home atmosphere",
    ]

    pick = int(digest[:8], 16)
    hair = hair_palette[pick % len(hair_palette)]
    eyes = eye_palette[(pick // 7) % len(eye_palette)]
    vibe = vibe_palette[(pick // 13) % len(vibe_palette)]

    style_hint = "adult anime woman" if profile.style_preset == "anime" else "adult feminine digital persona"
    return f"{style_hint}, {hair}, {eyes}, light skin, {vibe}, soft feminine presence"


def clamp01(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except Exception:
        numeric = default
    return max(0.0, min(1.0, numeric))
