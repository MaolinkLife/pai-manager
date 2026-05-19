import pytest
import asyncio

from modules.generative.manager import GenerationManager
from modules.generative.providers.base import GenerateProvider, ProviderError
from modules.generative.types import GenerateRequest, GenerateResult
from modules.analyzer.providers.manager import AnalyzerProviderManager
from modules.analyzer.providers.base import AnalyzerProvider
from modules.moral_matrix.service import MoralMatrixProviderManager
from modules.moral_matrix.providers.base import MoralMatrixProvider
from modules.system.runtime_profile import should_release_resources


pytestmark = pytest.mark.regression


class _GenProvider(GenerateProvider):
    name = "dummy"

    def __init__(self, *, should_fail: bool = False):
        self.should_fail = should_fail
        self.released = 0

    def generate(self, request: GenerateRequest) -> GenerateResult:
        if self.should_fail:
            raise ProviderError("fail")
        return GenerateResult(provider=self.name, content="ok", raw={})

    def release_resources(self) -> None:
        self.released += 1


class _Analyzer(AnalyzerProvider):
    name = "dummy"

    def __init__(self):
        self.released = 0

    async def analyze(self, content, context):
        return {"ok": True}

    def release_resources(self) -> None:
        self.released += 1


class _Moral(MoralMatrixProvider):
    name = "dummy"

    def __init__(self):
        self.released = 0

    async def run(self, payload):
        return {"summary": "ok", "hard_directives": []}

    def release_resources(self) -> None:
        self.released += 1


class _FailingMoral(MoralMatrixProvider):
    name = "failing"

    def __init__(self):
        self.released = 0

    async def run(self, payload):
        raise ValueError("bad provider output")

    def release_resources(self) -> None:
        self.released += 1


def test_generation_manager_releases_provider_after_generate(monkeypatch):
    monkeypatch.setattr(
        "modules.generative.manager.should_release_resources",
        lambda *_args, **_kwargs: True,
    )
    manager = GenerationManager()
    provider = _GenProvider()
    manager._providers = {"dummy": provider}
    manager._ordered_provider_names = lambda: ["dummy"]  # type: ignore[assignment]

    result = manager.generate(GenerateRequest(messages=[{"role": "user", "content": "x"}]))
    assert result.content == "ok"
    assert provider.released == 1


def test_analyzer_manager_releases_provider_after_call(monkeypatch):
    monkeypatch.setattr(
        "modules.analyzer.providers.manager.should_release_resources",
        lambda *_args, **_kwargs: True,
    )
    manager = AnalyzerProviderManager()
    provider = _Analyzer()
    manager._registry = {"dummy": provider}
    manager._resolve_providers = lambda: [provider]  # type: ignore[assignment]

    result, provider_name, errors = asyncio.run(manager.analyze("x", {}))
    assert result and provider_name == "dummy"
    assert errors == []
    assert provider.released == 1


def test_moral_manager_releases_provider_after_call():
    manager = MoralMatrixProviderManager()
    provider = _Moral()
    manager._registry = {"dummy": provider}
    manager._resolve_providers = lambda: [provider]  # type: ignore[assignment]

    result = asyncio.run(manager.run({"x": 1}))
    assert result.payload is not None and result.provider == "dummy"
    assert provider.released == 1


def test_moral_manager_falls_back_after_provider_exception(monkeypatch):
    monkeypatch.setattr(
        "modules.moral_matrix.service.should_release_resources",
        lambda *_args, **_kwargs: True,
    )
    manager = MoralMatrixProviderManager()
    failing = _FailingMoral()
    fallback = _Moral()
    manager._registry = {"failing": failing, "dummy": fallback}
    manager._resolve_providers = lambda: [failing, fallback]  # type: ignore[assignment]

    result = asyncio.run(manager.run({"x": 1}))

    assert result.payload == {"summary": "ok", "hard_directives": []}
    assert result.provider == "dummy"
    assert failing.released == 1
    assert fallback.released == 1


def test_generation_manager_skips_release_in_max_speed(monkeypatch):
    monkeypatch.setattr(
        "modules.generative.manager.should_release_resources",
        lambda *_args, **_kwargs: False,
    )
    manager = GenerationManager()
    provider = _GenProvider()
    manager._providers = {"dummy": provider}
    manager._ordered_provider_names = lambda: ["dummy"]  # type: ignore[assignment]

    result = manager.generate(GenerateRequest(messages=[{"role": "user", "content": "x"}]))
    assert result.content == "ok"
    assert provider.released == 0


def test_analyzer_manager_skips_release_in_max_speed(monkeypatch):
    monkeypatch.setattr(
        "modules.analyzer.providers.manager.should_release_resources",
        lambda *_args, **_kwargs: False,
    )
    manager = AnalyzerProviderManager()
    provider = _Analyzer()
    manager._registry = {"dummy": provider}
    manager._resolve_providers = lambda: [provider]  # type: ignore[assignment]

    result, provider_name, errors = asyncio.run(manager.analyze("x", {}))
    assert result and provider_name == "dummy"
    assert errors == []
    assert provider.released == 0


def test_moral_manager_skips_release_in_max_speed(monkeypatch):
    monkeypatch.setattr(
        "modules.moral_matrix.service.should_release_resources",
        lambda *_args, **_kwargs: False,
    )
    manager = MoralMatrixProviderManager()
    provider = _Moral()
    manager._registry = {"dummy": provider}
    manager._resolve_providers = lambda: [provider]  # type: ignore[assignment]

    result = asyncio.run(manager.run({"x": 1}))
    assert result.payload is not None and result.provider == "dummy"
    assert provider.released == 0


def test_module_release_after_use_overrides_global_profile(monkeypatch):
    values = {
        "analyzer.release_after_use": True,
        "system.runtime.model_memory_profile": "max_speed",
    }

    monkeypatch.setattr(
        "modules.system.runtime_profile.config_service.get_config_value",
        lambda path, default=None: values.get(path, default),
    )

    assert should_release_resources("analyzer") is True


def test_module_release_after_use_can_keep_generator_warm(monkeypatch):
    values = {
        "api.release_after_use": False,
        "system.runtime.model_memory_profile": "low_memory_strict",
    }

    monkeypatch.setattr(
        "modules.system.runtime_profile.config_service.get_config_value",
        lambda path, default=None: values.get(path, default),
    )

    assert should_release_resources("generative") is False
