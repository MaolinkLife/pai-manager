"""Technical prompts: preset in the config and editable from the UI.

Every technical prompt (analysis, checks, validators) is
preset and editable. An empty field means the built-in text. A template whose
placeholders were broken in the settings falls back to the built-in one, and the
journal names the setting.
"""

from typing import Any

from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry


def prompt_or_built_in(value: Any, built_in: str) -> str:
    """A prompt edited in the settings; an empty or missing one is the built-in text."""
    return value if isinstance(value, str) and value.strip() else built_in


def configured_prompt(path: str, built_in: str) -> str:
    """The prompt at ``path`` in the config; an empty or missing one is the built-in text."""
    return prompt_or_built_in(config_service.get_config_value(path, built_in), built_in)


def fill_template(template: str, built_in: str, *, path: str, **values: Any) -> str:
    """Fill a template from the settings; a broken one falls back to the built-in template."""
    try:
        return template.format(**values)
    except (AttributeError, IndexError, KeyError, ValueError) as exc:
        log_audit_entry(
            "technical_prompt_template_invalid",
            "[Prompts] A prompt template from the settings is broken; the built-in one is used.",
            AuditStatus.WARNING,
            details={
                "path": path,
                "error": f"{type(exc).__name__}: {exc}",
                "placeholders": sorted(values),
            },
        )
        return built_in.format(**values)


def filled_prompt(path: str, built_in: str, **values: Any) -> str:
    """The prompt at ``path`` with its placeholders filled; a broken template falls back."""
    return fill_template(configured_prompt(path, built_in), built_in, path=path, **values)
