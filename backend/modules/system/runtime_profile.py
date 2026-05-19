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

COMPONENT_CONFIG_PATHS = {
    "generative": "api",
    "generator": "api",
    "api": "api",
    "analyzer": "analyzer",
    "moral": "moral",
    "decision_layer": "decision_layer",
    "decision-layer": "decision_layer",
    "vision": "vision",
    "synthesis": "synthesis",
}


def _as_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None


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
    comp = str(component or "").strip().lower()
    config_path = COMPONENT_CONFIG_PATHS.get(comp, comp)
    release_override = _as_bool(
        config_service.get_config_value(f"{config_path}.release_after_use", None)
    )
    if release_override is not None:
        return release_override

    profile = get_model_memory_profile()
    if profile == "low_memory_strict":
        return True
    if profile == "max_speed":
        return False

    # balanced profile:
    # - keep LLM/SLM layers warm for lower latency
    # - release heavier visual synthesis paths
    if comp in {"synthesis", "vision"}:
        return True
    return False
