"""llama.cpp adapter for the generative manager.

Mirrors the role of ``OllamaGenerateProvider`` but talks to a llama-server
instance over its OpenAI-compatible HTTP endpoints. Lives next to the other
generation providers — the transport itself is in ``modules.llama_cpp.client``.

Scope of this adapter:
  * sync + async streaming chat completions;
  * sampler parameters from DB-first config (``api.providers.llama_cpp``);
  * no tool calling / no vision / no reasoning split — those are tracked under
    follow-up phases. When the user enables tools or images the manager will
    fall back to the next provider in ``api.fallback_order``.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, Iterable, List

import requests

from modules.generative.providers.base import (
    GenerateProvider,
    ProviderError,
    ProviderNotAvailable,
)
from modules.generative.types import (
    GenerateRequest,
    GenerateResult,
    GenerateStreamChunk,
)
from modules.llama_cpp import client as llama_client
from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry


_DEFAULT_BASE_URL = "http://127.0.0.1:8080"
_DEFAULT_REQUEST_TIMEOUT = 300.0
_DEFAULT_STREAM_TIMEOUT = 600.0


class LlamaCppGenerateProvider(GenerateProvider):
    name = "llama_cpp"

    def supports_streaming(self) -> bool:
        return True

    def is_available(self) -> bool:
        cfg = self._get_provider_config()
        return bool(cfg.get("enabled"))

    def release_resources(self) -> None:
        # Phase 3 will wire this into the module lifecycle service so the
        # embedded llama-server can be unloaded after idle timeout. For now
        # the server is either externally managed or kept warm by the user.
        return None

    # ------------------------------------------------------------------
    # config / sampler helpers
    # ------------------------------------------------------------------

    def _get_provider_config(self) -> Dict[str, Any]:
        cfg = config_service.get_config_value("api.providers.llama_cpp", {}) or {}
        return cfg if isinstance(cfg, dict) else {}

    def _base_url(self, cfg: Dict[str, Any]) -> str:
        return str(cfg.get("base_url") or _DEFAULT_BASE_URL).rstrip("/")

    def _request_timeout(self, cfg: Dict[str, Any]) -> float:
        try:
            return float(cfg.get("request_timeout") or _DEFAULT_REQUEST_TIMEOUT)
        except (TypeError, ValueError):
            return _DEFAULT_REQUEST_TIMEOUT

    def _stream_timeout(self, cfg: Dict[str, Any]) -> float:
        try:
            return float(cfg.get("stream_timeout") or _DEFAULT_STREAM_TIMEOUT)
        except (TypeError, ValueError):
            return _DEFAULT_STREAM_TIMEOUT

    def _sampler_from(self, request: GenerateRequest, cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Merge DB sampler defaults with per-request overrides in ``request.options``."""
        options = request.options or {}

        def pick(key: str, *aliases: str, default: Any = None) -> Any:
            for source in (options, cfg):
                for name in (key, *aliases):
                    if name in source and source[name] is not None:
                        return source[name]
            return default

        sampler: Dict[str, Any] = {}
        for key, aliases in (
            ("temperature", ()),
            ("top_p", ()),
            ("top_k", ()),
            ("min_p", ()),
            ("repeat_penalty", ()),
            ("presence_penalty", ()),
            ("max_tokens", ("num_predict",)),
        ):
            value = pick(key, *aliases)
            if value is not None:
                sampler[key] = value
        return sampler

    # ------------------------------------------------------------------
    # message normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_chat_messages(messages: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        sanitized: List[Dict[str, Any]] = []
        for item in messages or []:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            if not role:
                continue
            content = item.get("content")
            if content is None:
                content = ""
            # llama-server expects string content for plain chat; multimodal
            # arrays are forwarded as-is so a future vision adapter can reuse
            # this helper.
            sanitized.append({"role": role, "content": content})
        return sanitized

    # ------------------------------------------------------------------
    # generate (sync)
    # ------------------------------------------------------------------

    def generate(self, request: GenerateRequest) -> GenerateResult:
        cfg = self._get_provider_config()
        if not cfg.get("enabled"):
            raise ProviderNotAvailable("llama_cpp provider disabled")

        model = (request.metadata or {}).get("model") or cfg.get("model")
        messages = self._ensure_chat_messages(request.messages)
        sampler = self._sampler_from(request, cfg)

        print("[Generator] llama.cpp: синхронная генерация.")
        log_audit_entry(
            event_type="generator_llama_cpp_start",
            msg="[Generator] llama.cpp sync request prepared.",
            status=AuditStatus.INFO,
            details={
                "model": model,
                "messages": messages,
                "sampler": sampler,
                "base_url": self._base_url(cfg),
            },
        )

        try:
            raw = llama_client.chat_completion(
                base_url=self._base_url(cfg),
                messages=messages,
                model=model,
                sampler=sampler,
                timeout=self._request_timeout(cfg),
            )
        except requests.RequestException as exc:
            raise ProviderError(f"llama.cpp transport error: {exc}") from exc

        choices = raw.get("choices") or []
        first = choices[0] if isinstance(choices, list) and choices else {}
        message_payload = (first.get("message") if isinstance(first, dict) else {}) or {}
        content = str(message_payload.get("content") or "")
        finish_reason = first.get("finish_reason") if isinstance(first, dict) else None

        log_audit_entry(
            event_type="generator_llama_cpp_success",
            msg="[Generator] llama.cpp sync response received.",
            status=AuditStatus.SUCCESS,
            details={
                "model": model,
                "content_length": len(content),
                "finish_reason": finish_reason,
                "usage": raw.get("usage"),
            },
        )
        print("[Generator] llama.cpp: ответ получен.")

        return GenerateResult(
            provider=self.name,
            content=content,
            raw=raw,
            reasoning=None,
            metadata={"model": model, "finish_reason": finish_reason, "usage": raw.get("usage")},
            tool_calls=[],
        )

    # ------------------------------------------------------------------
    # stream (async)
    # ------------------------------------------------------------------

    async def stream(self, request: GenerateRequest) -> AsyncIterator[GenerateStreamChunk]:
        cfg = self._get_provider_config()
        if not cfg.get("enabled"):
            raise ProviderNotAvailable("llama_cpp provider disabled")

        model = (request.metadata or {}).get("model") or cfg.get("model")
        messages = self._ensure_chat_messages(request.messages)
        sampler = self._sampler_from(request, cfg)

        print("[Generator] llama.cpp: потоковая генерация.")
        log_audit_entry(
            event_type="generator_llama_cpp_stream_start",
            msg="[Generator] llama.cpp streaming request prepared.",
            status=AuditStatus.INFO,
            details={
                "model": model,
                "messages": messages,
                "sampler": sampler,
                "base_url": self._base_url(cfg),
            },
        )

        try:
            async for chunk in llama_client.astream_chat_completion(
                base_url=self._base_url(cfg),
                messages=messages,
                model=model,
                sampler=sampler,
                timeout=self._stream_timeout(cfg),
            ):
                if chunk.get("done"):
                    yield GenerateStreamChunk(
                        provider=self.name,
                        content="",
                        raw=chunk,
                        done=True,
                        metadata={"model": model},
                    )
                    return

                # llama-server SSE deltas follow the OpenAI shape:
                # {"choices":[{"delta":{"content":"..."},"finish_reason":null}], ...}
                choices = chunk.get("choices") or []
                first = choices[0] if isinstance(choices, list) and choices else {}
                delta = (first.get("delta") if isinstance(first, dict) else {}) or {}
                content_piece = str(delta.get("content") or "")
                finish_reason = first.get("finish_reason") if isinstance(first, dict) else None

                if content_piece:
                    yield GenerateStreamChunk(
                        provider=self.name,
                        content=content_piece,
                        raw=chunk,
                        done=False,
                        metadata={"model": model},
                    )

                if finish_reason:
                    yield GenerateStreamChunk(
                        provider=self.name,
                        content="",
                        raw=chunk,
                        done=True,
                        metadata={"model": model, "finish_reason": finish_reason},
                    )
                    return
        except Exception as exc:
            raise ProviderError(f"llama.cpp stream error: {exc}") from exc
