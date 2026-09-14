"""After an image is generated: look at it and tell how well it came out.

Vision describes the result, a judge model compares
it with what was asked (relevance) and, if enabled, holds it to a strict
quality bar. A result below a threshold is still delivered unless a reroll is
enabled, and it is always recorded in DebugVault: which model, which prompt,
which image, how far off. A check that could not run says why; it never
passes as a score.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from constants.paths import STORAGE_DIR
from constants.prompts import (
    SYNTHESIS_IMAGE_CHECK_DESCRIBE_PROMPT,
    SYNTHESIS_IMAGE_CHECK_SYSTEM_PROMPT,
    SYNTHESIS_IMAGE_CHECK_USER_TEMPLATE,
)
from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry
from modules.system.technical_prompts import fill_template, prompt_or_built_in

VAULT_KIND = "image_check_low"
MAX_GENERATIONS_CAP = 10
CHECK_NAMES = ("relevance", "quality")


def _threshold(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return round(min(1.0, max(0.1, number)), 2)


@dataclass
class CheckGate:
    enabled: bool
    threshold: float
    reroll: bool


@dataclass
class ImageCheckSettings:
    relevance: CheckGate
    quality: CheckGate
    max_generations: int
    describe_prompt: str = SYNTHESIS_IMAGE_CHECK_DESCRIBE_PROMPT
    system_prompt: str = SYNTHESIS_IMAGE_CHECK_SYSTEM_PROMPT
    user_template: str = SYNTHESIS_IMAGE_CHECK_USER_TEMPLATE

    @classmethod
    def from_config(cls) -> "ImageCheckSettings":
        cfg = config_service.get_config_value("synthesis.image_check", {}) or {}

        def gate(name: str, enabled: bool, threshold: float) -> CheckGate:
            section = cfg.get(name) if isinstance(cfg.get(name), dict) else {}
            return CheckGate(
                enabled=bool(section.get("enabled", enabled)),
                threshold=_threshold(section.get("threshold", threshold), threshold),
                reroll=bool(section.get("reroll", False)),
            )

        try:
            generations = int(cfg.get("max_generations", 2))
        except (TypeError, ValueError):
            generations = 2
        return cls(
            relevance=gate("relevance", True, 0.6),
            quality=gate("quality", False, 0.82),
            max_generations=max(1, min(generations, MAX_GENERATIONS_CAP)),
            describe_prompt=prompt_or_built_in(cfg.get("describe_prompt"), SYNTHESIS_IMAGE_CHECK_DESCRIBE_PROMPT),
            system_prompt=prompt_or_built_in(cfg.get("system_prompt"), SYNTHESIS_IMAGE_CHECK_SYSTEM_PROMPT),
            user_template=prompt_or_built_in(cfg.get("user_template"), SYNTHESIS_IMAGE_CHECK_USER_TEMPLATE),
        )

    @property
    def any_enabled(self) -> bool:
        return self.relevance.enabled or self.quality.enabled

    def generations_allowed(self) -> int:
        """One generation, or up to max_generations when an enabled check may reroll."""
        rerolls = any(gate.enabled and gate.reroll for gate in (self.relevance, self.quality))
        return self.max_generations if rerolls else 1


@dataclass
class ImageCheckResult:
    status: str  # passed | low | not_checked | disabled
    description: str = ""
    relevance: Optional[float] = None
    quality: Optional[float] = None
    failed: List[str] = field(default_factory=list)
    mismatches: List[str] = field(default_factory=list)
    feedback: str = ""
    reason: str = ""

    def should_reroll(self, settings: ImageCheckSettings) -> bool:
        return self.status == "low" and any(getattr(settings, name).reroll for name in self.failed)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _describe_with_vision(image_bytes: bytes, prompt: str = SYNTHESIS_IMAGE_CHECK_DESCRIBE_PROMPT) -> Dict[str, Any]:
    from PIL import Image

    from modules.vision.visual_module import VisualModule

    try:
        with Image.open(BytesIO(image_bytes)) as image:
            return VisualModule().describe_image(image.convert("RGB"), prompt)
    except Exception as exc:
        return {"status": "error", "summary": f"vision failed: {exc}"}


def _judge_with_model(system: str, user: str) -> str:
    from modules.generative.manager import generation_manager
    from modules.generative.types import GenerateRequest

    result = generation_manager.generate(
        GenerateRequest(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            options={"temperature": 0.1, "num_predict": 600, "__think": False},
            metadata={"mode": "synthesis_image_check"},
        )
    )
    return str(getattr(result, "content", "") or "").strip() or str(getattr(result, "reasoning", "") or "")


def _parse_verdict(raw: str) -> Optional[Dict[str, Any]]:
    text = re.sub(r"^```(?:json)?|```$", "", str(raw or "").strip(), flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        verdict = json.loads(match.group(0))
    except ValueError:
        return None
    return verdict if isinstance(verdict, dict) else None


def _score(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(min(1.0, max(0.0, number)), 3)


def _judge_user_message(settings: ImageCheckSettings, **values: str) -> str:
    """Fill the judge template; a template broken in the settings falls back to the built-in one."""
    return fill_template(
        settings.user_template,
        SYNTHESIS_IMAGE_CHECK_USER_TEMPLATE,
        path="synthesis.image_check.user_template",
        **values,
    )


def _not_checked(reason: str, description: str = "") -> ImageCheckResult:
    log_audit_entry(
        "synthesis_image_check_not_run",
        "[Synthesis] The generated image could not be checked.",
        AuditStatus.WARNING,
        details={"reason": reason},
    )
    return ImageCheckResult(status="not_checked", description=description, reason=reason)


def check_generated_image(
    image_bytes: bytes,
    *,
    request_text: str,
    prompt: str,
    settings: ImageCheckSettings,
    describe: Optional[Callable[[bytes], Dict[str, Any]]] = None,
    judge: Optional[Callable[[str, str], str]] = None,
) -> ImageCheckResult:
    """Describe the image once, then score every enabled check in one judge call."""
    if not settings.any_enabled:
        return ImageCheckResult(status="disabled")

    if describe is None:
        described = _describe_with_vision(image_bytes, settings.describe_prompt) or {}
    else:
        described = describe(image_bytes) or {}
    description = str(described.get("summary") or "").strip()
    if described.get("status") != "success" or not description:
        return _not_checked(f"vision could not describe the image: {description or 'no answer'}")

    enabled = [name for name in CHECK_NAMES if getattr(settings, name).enabled]
    user = _judge_user_message(
        settings,
        scores=", ".join(enabled),
        request=str(request_text or "").strip() or "<none>",
        prompt=str(prompt or "").strip() or "<none>",
        description=description,
    )
    try:
        raw = (judge or _judge_with_model)(settings.system_prompt, user)
    except Exception as exc:
        return _not_checked(f"the judge model is unavailable: {exc}", description)

    verdict = _parse_verdict(raw)
    if verdict is None:
        return _not_checked("the judge answer is not valid JSON", description)

    scores: Dict[str, float] = {}
    for name in enabled:
        score = _score(verdict.get(name))
        if score is None:
            return _not_checked(f"the judge gave no {name} score", description)
        scores[name] = score

    failed = [name for name in enabled if scores[name] < getattr(settings, name).threshold]
    mismatches = verdict.get("mismatches") if isinstance(verdict.get("mismatches"), list) else []
    result = ImageCheckResult(
        status="low" if failed else "passed",
        description=description,
        relevance=scores.get("relevance"),
        quality=scores.get("quality"),
        failed=failed,
        mismatches=[str(item).strip() for item in mismatches if str(item).strip()][:10],
        feedback=str(verdict.get("feedback") or "").strip(),
    )
    log_audit_entry(
        "synthesis_image_checked",
        "[Synthesis] Generated image checked against its request.",
        AuditStatus.WARNING if failed else AuditStatus.INFO,
        details={
            "status": result.status,
            "scores": scores,
            "thresholds": {name: getattr(settings, name).threshold for name in enabled},
            "failed": failed,
            "mismatches": result.mismatches[:5],
        },
    )
    return result


@dataclass
class CheckedAttempt:
    attempt: int
    prompt: str
    negative_prompt: str
    image_bytes: bytes
    check: ImageCheckResult


def _save_attempt_image(folder: Path, batch: str, attempt: CheckedAttempt) -> Optional[str]:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{batch}_attempt{attempt.attempt}.png"
        path.write_bytes(attempt.image_bytes)
        return path.relative_to(Path(STORAGE_DIR)).as_posix()
    except Exception as exc:
        log_audit_entry(
            "synthesis_image_check_image_not_saved",
            "[Synthesis] Could not save a checked image for DebugVault.",
            AuditStatus.WARNING,
            details={"error": str(exc), "attempt": attempt.attempt},
        )
        return None


def _score_line(check: ImageCheckResult, settings: ImageCheckSettings) -> str:
    parts = [
        f"{name} {getattr(check, name):.2f} < {getattr(settings, name).threshold:.2f}"
        for name in check.failed
    ]
    return ", ".join(parts)


def record_low_results(
    attempts: List[CheckedAttempt],
    *,
    request_text: str,
    model_id: Optional[str],
    provider: Optional[str],
    source: str,
    settings: ImageCheckSettings,
) -> Optional[str]:
    """One DebugVault entry per request when any attempt scored below its threshold."""
    low_attempts = [attempt for attempt in attempts if attempt.check.status == "low"]
    if not low_attempts:
        return None

    from modules.debug_vault.service import write_vault_entry

    folder = Path(STORAGE_DIR) / "outputs" / "image_checks"
    batch = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    delivered = attempts[-1]
    worst = low_attempts[-1]
    outcome = "delivered below threshold" if delivered.check.status == "low" else f"passed on attempt {delivered.attempt}"
    summary = (
        f"Image model {model_id or 'unknown'}: {_score_line(worst.check, settings)} "
        f"({len(attempts)} generation(s), {outcome})"
    )
    context = {
        "model_id": model_id,
        "provider": provider,
        "source": source,
        "request": request_text,
        "thresholds": {name: getattr(settings, name).threshold for name in CHECK_NAMES if getattr(settings, name).enabled},
        "delivered_attempt": delivered.attempt,
        "attempts": [
            {
                "attempt": attempt.attempt,
                "prompt": attempt.prompt,
                "negative_prompt": attempt.negative_prompt,
                "image_path": _save_attempt_image(folder, batch, attempt),
                **{key: value for key, value in attempt.check.as_dict().items()},
            }
            for attempt in attempts
        ],
    }
    return write_vault_entry(
        kind=VAULT_KIND,
        summary=summary,
        severity="warning",
        context=context,
        output=delivered.check.description,
        violations=delivered.check.mismatches or worst.check.mismatches,
    )
