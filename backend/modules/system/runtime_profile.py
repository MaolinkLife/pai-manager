"""Runtime resource profile helpers.

Controls aggressive vs relaxed model/resource release policy.
"""

from __future__ import annotations

from modules.system import config as config_service

MODEL_MEMORY_PROFILE_DEFAULT = "low_memory_strict"
MODEL_MEMORY_PROFILES = {
    "low_memory_strict",
    "balanced",
    "max_speed",
}


def get_model_memory_profile() -> str:
    raw = config_service.get_config_value(
        "system.runtime.model_memory_profile",
        MODEL_MEMORY_PROFILE_DEFAULT,
    )
    profile = str(raw or "").strip().lower()
    if profile not in MODEL_MEMORY_PROFILES:
        return MODEL_MEMORY_PROFILE_DEFAULT
    return profile


def should_release_resources(component: str) -> bool:
    profile = get_model_memory_profile()
    if profile == "low_memory_strict":
        return True
    if profile == "max_speed":
        return False

    # balanced profile:
    # - keep LLM/SLM layers warm for lower latency
    # - release heavier visual synthesis paths
    comp = str(component or "").strip().lower()
    if comp in {"synthesis", "vision"}:
        return True
    return False

