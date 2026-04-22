"""Provider manager for analyzer module."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry
from modules.system.localization import get_text
from modules.system.runtime_profile import should_release_resources

from .base import AnalyzerProvider
from .openrouter import OpenRouterAnalyzerProvider
from .ollama import OllamaAnalyzerProvider


class AnalyzerProviderManager:
    """Manages the chain of analyzer providers with fallbacks."""

    def __init__(self) -> None:
        self._registry: Dict[str, AnalyzerProvider] = {
            "openrouter": OpenRouterAnalyzerProvider(),
            "ollama": OllamaAnalyzerProvider(),
        }

    async def analyze(
        self, content: str, context: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], List[str]]:
        errors: List[str] = []
        for provider in self._resolve_providers():
            if not provider.is_available():
                log_audit_entry(
                    "analyzer_provider_unavailable",
                    get_text(
                        "analyzer.provider_unavailable",
                        params={"provider": provider.name},
                        default=f"[Analyzer] Provider '{provider.name}' unavailable.",
                    ),
                    AuditStatus.INFO,
                    message_key="analyzer.provider_unavailable",
                    message_args={"provider": provider.name},
                )
                errors.append(f"{provider.name}_unavailable")
                continue

            try:
                result = await provider.analyze(content, context)
                if result:
                    return result, provider.name, errors
                errors.append(f"{provider.name}_failed")
            finally:
                if should_release_resources("analyzer"):
                    try:
                        provider.release_resources()
                    except Exception as exc:
                        log_audit_entry(
                            "analyzer_provider_release_error",
                            f"[Analyzer] Provider '{provider.name}' release failed.",
                            AuditStatus.WARNING,
                            details={"provider": provider.name, "error": str(exc)},
                        )

        return None, None, errors

    def register(self, provider: AnalyzerProvider) -> None:
        self._registry[provider.name] = provider

    def set_providers(self, providers: Iterable[AnalyzerProvider]) -> None:
        self._registry = {provider.name: provider for provider in providers}

    def _resolve_providers(self) -> List[AnalyzerProvider]:
        active = config_service.get_config_value("analyzer.active_provider", "openrouter")
        fallback = config_service.get_config_value("analyzer.fallback_order", [])

        order: List[str] = []
        if isinstance(active, str) and active:
            order.append(active)

        if isinstance(fallback, list):
            for name in fallback:
                if isinstance(name, str):
                    order.append(name)

        resolved: List[AnalyzerProvider] = []
        for name in order:
            provider = self._registry.get(name)
            if provider and provider not in resolved:
                resolved.append(provider)

        for provider in self._registry.values():
            if provider not in resolved:
                resolved.append(provider)

        return resolved

