"""Who is in a chat or proactive image, and the scene the model writes for it.

The rules:
a proactive image is always her, as a selfie; a request about her is her; an
image nobody named a subject for rolls the composer's dice; anything else is
only what was asked. Time and season go only into images of her.

The roles: the composer decides and supplies, the model writes the scene, the
appearance anchor goes first word for word. The pose comes from the persona
settings; with none set the model composes the selfie itself. When the model
gives no scene, her picture falls back to the composer's own template and
anything else to the request text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from typing import Any, Dict, Optional

from constants.prompts import IMAGE_SCENE_FORMAT_PROMPT, IMAGE_SCENE_SYSTEM_PROMPT
from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry
from modules.visual_intent_composer import VisualIntentInput, VisualProfile, visual_intent_composer_service
from modules.visual_prompt_builder import visual_prompt_builder_service
from modules.visual_prompt_builder.templates import QUALITY_PROMPT, STYLE_PRESET_PROMPTS, join_parts

SUBJECTS = ("self", "other", "free")
HER_SUBJECT_MODES = ("self", "self_plus_environment")
_ROLL_TEXT = {
    "self": "the character herself (write it as for self)",
    "self_plus_environment": "the character herself in her surroundings (write it as for self)",
    "environment_only": "a place, without the character",
    "symbolic_mood": "a symbolic mood image, without the character",
    "object_focus": "an object, without the character",
}


def shows_her(subject: Optional[str], free_roll: str = "") -> bool:
    return subject == "self" or (subject == "free" and free_roll in HER_SUBJECT_MODES)


@dataclass
class ImageScene:
    # self / other / free; None when the model gave no answer the system can read.
    subject: Optional[str]
    scene: str
    negative_prompt: str = ""
    free_roll: str = ""
    provider: str = ""
    raw: Any = None


def scene_format_prompt() -> str:
    """The answer format from the settings; an empty field means the built-in one."""
    value = config_service.get_config_value("synthesis.image_scene.format_prompt", "")
    return value if isinstance(value, str) and value.strip() else IMAGE_SCENE_FORMAT_PROMPT


def _parse_answer(text: str) -> Optional[Dict[str, Any]]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(text or "").strip(), flags=re.IGNORECASE).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return None
    try:
        answer = json.loads(match.group(0))
    except ValueError:
        return None
    return answer if isinstance(answer, dict) else None


def _no_scene(reason: str, subject: Optional[str], free_roll: str, **details: Any) -> None:
    log_audit_entry(
        "image_scene_not_written",
        "[ImageScene] The model gave no scene; the pipeline falls back.",
        AuditStatus.WARNING,
        details={"reason": reason, "subject": subject, "free_roll": free_roll, **details},
    )


def write_image_scene(
    *,
    request_text: str,
    context: Dict[str, Any],
    profile: VisualProfile,
    subject: Optional[str] = None,
) -> ImageScene:
    """One call: who is in the picture and the scene. `subject` is passed when already decided."""
    from modules.generative.manager import generation_manager
    from modules.generative.types import GenerateRequest

    free_roll = "" if subject else visual_intent_composer_service.roll_subject(profile)
    payload: Dict[str, Any] = {"request": str(request_text or "").strip()}
    payload.update({key: value for key, value in (context or {}).items() if value})
    if subject:
        payload["subject_is_decided"] = subject
    else:
        payload["if_the_request_names_no_subject_the_image_shows"] = _ROLL_TEXT.get(free_roll, free_roll)
    outfit = str(profile.default_outfit or "").strip()
    if outfit:
        payload["her_usual_outfit"] = outfit
    payload["her_selfie_pose"] = (
        "set separately: do not describe the camera or the pose"
        if visual_intent_composer_service.has_selfie_pose(profile)
        else "compose it yourself as a selfie she takes with her own phone"
    )

    try:
        result = generation_manager.generate(
            GenerateRequest(
                messages=[
                    {"role": "system", "content": f"{IMAGE_SCENE_SYSTEM_PROMPT}\n\n{scene_format_prompt()}"},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
                ],
                options={"temperature": 0.75, "max_tokens": 700},
                metadata={"mode": "image_scene"},
            )
        )
    except Exception as exc:
        _no_scene("the chat model is unavailable", subject, free_roll, error=str(exc))
        return ImageScene(subject=subject, scene="", free_roll=free_roll)

    provider = str(getattr(result, "provider", "") or "")
    raw = getattr(result, "raw", None)
    answer = _parse_answer(getattr(result, "content", "") or "") or _parse_answer(getattr(result, "reasoning", "") or "")
    if answer is None:
        _no_scene("the answer is not valid JSON", subject, free_roll)
        return ImageScene(subject=subject, scene="", free_roll=free_roll, provider=provider, raw=raw)

    answered = str(answer.get("subject") or "").strip().lower()
    return ImageScene(
        subject=subject or (answered if answered in SUBJECTS else None),
        scene=str(answer.get("prompt") or answer.get("scene") or "").strip(),
        negative_prompt=str(answer.get("negative_prompt") or "").strip(),
        free_roll=free_roll,
        provider=provider,
        raw=raw,
    )


def _owner_zone() -> tzinfo:
    try:
        from zoneinfo import ZoneInfo

        from models.models import User
        from modules.database.core import SessionLocal
        from modules.system.config import _get_owner_user_uuid

        owner_uuid = _get_owner_user_uuid()
        if owner_uuid:
            with SessionLocal() as session:
                user = session.query(User).filter(User.uuid == owner_uuid).first()
                name = getattr(getattr(user, "settings", None), "timezone_name", None)
                if isinstance(name, str) and name.strip():
                    return ZoneInfo(name.strip())
    except Exception:
        pass
    return timezone.utc


def world_state(now: Optional[datetime] = None) -> Dict[str, str]:
    """Time of day and season in the configured timezone (northern hemisphere seasons)."""
    local = (now or datetime.now(timezone.utc)).astimezone(_owner_zone())
    hour = local.hour
    if 5 <= hour < 12:
        period = "morning"
    elif 12 <= hour < 17:
        period = "day"
    elif 17 <= hour < 22:
        period = "evening"
    elif hour >= 22:
        period = "late_evening"
    else:
        period = "night"
    season = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
              6: "summer", 7: "summer", 8: "summer"}.get(local.month, "autumn")
    return {"local_time": local.strftime("%H:%M"), "day_period": period, "time_of_day": period, "season": season}


def her_prompt(scene: str, profile: VisualProfile, *, purpose_hint: str = "", now: Optional[datetime] = None) -> tuple[str, str]:
    """Her picture: the anchor word for word, the pose, the scene, the time and season, her style."""
    world = world_state(now)
    if not str(scene or "").strip():
        context = {"decided_subject": "self"}
        if purpose_hint:
            context["purpose_hint"] = purpose_hint
        payload = VisualIntentInput(visual_profile=profile, world_state=world, self_expression_context=context)
        plan = visual_intent_composer_service.compose(payload)
        return visual_prompt_builder_service.build_prompt_pair(profile=payload.visual_profile, plan=plan)

    style = STYLE_PRESET_PROMPTS.get(str(profile.style_preset or "").strip().lower(), STYLE_PRESET_PROMPTS["anime"])
    positive = join_parts(
        [
            str(profile.appearance_textarea or "").strip(),
            visual_intent_composer_service.pick_selfie_pose(profile),
            str(scene).strip(),
            f"{world['day_period'].replace('_', ' ')}, {world['season']}",
            style,
            QUALITY_PROMPT,
        ]
    )
    return positive, ""
