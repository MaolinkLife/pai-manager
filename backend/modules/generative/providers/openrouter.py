from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Dict, Iterable, List

from openai import OpenAI

from constants.settings import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    OPENROUTER_BASE_URL,
)
from modules.generative.providers.base import GenerateProvider, ProviderError
from modules.generative.types import (
    GenerateRequest,
    GenerateResult,
    GenerateStreamChunk,
)
from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry


class OpenRouterGenerateProvider(GenerateProvider):
    name = "openrouter"

    def is_available(self) -> bool:
        return bool(self._get_provider_config().get("api_key"))

    def supports_streaming(self) -> bool:
        return True

    def _get_provider_config(self) -> Dict[str, Any]:
        cfg = config_service.get_config_value("api.providers.openrouter", {}) or {}
        return {
            "api_key": cfg.get("api_key", ""),
            "model": cfg.get("model", "openai/gpt-4o-mini"),
            "temperature": cfg.get("temperature", DEFAULT_TEMPERATURE),
            "max_tokens": cfg.get("max_tokens", DEFAULT_MAX_TOKENS),
            "base_url": cfg.get("base_url", OPENROUTER_BASE_URL),
        }

    @staticmethod
    def _ensure_list(messages: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not isinstance(messages, list):
            messages = list(messages)
        sanitized: List[Dict[str, Any]] = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            if not role:
                continue
            payload: Dict[str, Any] = {
                "role": role,
                "content": item.get("content") if item.get("content") is not None else "",
            }
            if role == "assistant" and isinstance(item.get("tool_calls"), list):
                payload["tool_calls"] = OpenRouterGenerateProvider._sanitize_tool_calls(
                    item.get("tool_calls") or []
                )
            if role == "tool":
                tool_call_id = str(item.get("tool_call_id") or "").strip()
                if tool_call_id:
                    payload["tool_call_id"] = tool_call_id
                name = str(item.get("name") or "").strip()
                if name:
                    payload["name"] = name
            name = str(item.get("name") or "").strip()
            if role in {"system", "user", "assistant"} and name:
                payload["name"] = name
            sanitized.append(payload)
        return sanitized

    @staticmethod
    def _sanitize_tool_calls(tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        sanitized: List[Dict[str, Any]] = []
        for idx, call in enumerate(tool_calls):
            if not isinstance(call, dict):
                continue
            function = call.get("function") or {}
            if not isinstance(function, dict):
                function = {}
            name = str(function.get("name") or "").strip()
            if not name:
                continue
            arguments = function.get("arguments", "{}")
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments or {}, ensure_ascii=False)
            sanitized.append(
                {
                    "id": str(call.get("id") or f"tool_call_{idx + 1}"),
                    "type": str(call.get("type") or "function"),
                    "function": {"name": name, "arguments": arguments},
                }
            )
        return sanitized

    def _compose_settings(
        self, request: GenerateRequest, cfg: Dict[str, Any]
    ) -> Dict[str, Any]:
        options = request.options or {}
        return {
            "temperature": float(options.get("temperature", cfg["temperature"])),
            "max_tokens": int(options.get("max_tokens", cfg["max_tokens"])),
            "top_p": options.get("top_p"),
        }

    @staticmethod
    def _normalize_tool_calls(raw_tool_calls: Any) -> List[Dict[str, Any]]:
        if not raw_tool_calls:
            return []
        normalized: List[Dict[str, Any]] = []
        for idx, call in enumerate(raw_tool_calls):
            try:
                if isinstance(call, dict):
                    function = call.get("function") or {}
                    if not isinstance(function, dict):
                        function = {}
                    name = str(function.get("name") or "").strip()
                    arguments = function.get("arguments", "{}")
                    call_id = str(call.get("id") or f"openrouter_tool_{idx + 1}")
                    call_type = str(call.get("type") or "function")
                else:
                    function = getattr(call, "function", None)
                    name = str(getattr(function, "name", "") or "").strip()
                    arguments = getattr(function, "arguments", "{}")
                    call_id = str(getattr(call, "id", "") or f"openrouter_tool_{idx + 1}")
                    call_type = str(getattr(call, "type", "function") or "function")
                if not name:
                    continue
                if isinstance(arguments, str):
                    args_payload = arguments
                else:
                    args_payload = json.dumps(arguments or {}, ensure_ascii=False)
                normalized.append(
                    {
                        "id": call_id,
                        "type": call_type,
                        "function": {
                            "name": name,
                            "arguments": args_payload,
                        },
                    }
                )
            except Exception:
                continue
        return normalized

    def _build_client(self, cfg: Dict[str, Any]) -> OpenAI:
        if not cfg.get("api_key"):
            raise ProviderError("OpenRouter provider: отсутствует API ключ")
        return OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"])

    def generate(self, request: GenerateRequest) -> GenerateResult:
        cfg = self._get_provider_config()
        client = self._build_client(cfg)
        messages = self._ensure_list(request.messages)
        settings = self._compose_settings(request, cfg)

        print("[Generator] OpenRouter: синхронная генерация.")
        log_audit_entry(
            event_type="generator_openrouter_start",
            msg="[Generator/OpenRouter] Запуск синхронной генерации",
            status=AuditStatus.INFO,
            details={
                "model": cfg["model"],
                "messages": messages,
                "options": request.options,
                "metadata": request.metadata,
                "settings": settings,
            },
        )

        try:
            payload: Dict[str, Any] = {
                "model": cfg["model"],
                "messages": messages,
                "temperature": settings["temperature"],
                "max_tokens": settings["max_tokens"],
                "top_p": settings["top_p"],
            }
            if request.tools:
                payload["tools"] = request.tools
            if request.tool_choice is not None:
                payload["tool_choice"] = request.tool_choice
            completion = client.chat.completions.create(**payload)
        except Exception as exc:  # pragma: no cover - внешняя библиотека
            raise ProviderError(str(exc)) from exc

        choice = completion.choices[0]
        content = (choice.message.content or "").strip()
        tool_calls = self._normalize_tool_calls(getattr(choice.message, "tool_calls", None))

        log_audit_entry(
            event_type="generator_openrouter_success",
            msg="[Generator/OpenRouter] Генерация завершена",
            status=AuditStatus.SUCCESS,
            details={
                "model": cfg["model"],
                "response": completion.model_dump(),
                "content_length": len(content),
            },
        )
        print("[Generator] OpenRouter: ответ получен.")

        return GenerateResult(
            provider=self.name,
            content=content,
            raw=completion.model_dump(),
            metadata={"model": cfg["model"]},
            tool_calls=tool_calls,
        )

    async def stream(
        self, request: GenerateRequest
    ) -> AsyncIterator[GenerateStreamChunk]:
        cfg = self._get_provider_config()
        client = self._build_client(cfg)
        messages = self._ensure_list(request.messages)
        settings = self._compose_settings(request, cfg)

        print("[Generator] OpenRouter: потоковая генерация.")
        log_audit_entry(
            event_type="generator_openrouter_stream_start",
            msg="[Generator/OpenRouter] Запуск потоковой генерации",
            status=AuditStatus.INFO,
            details={
                "model": cfg["model"],
                "messages": messages,
                "options": request.options,
                "metadata": request.metadata,
                "settings": settings,
            },
        )

        try:
            payload: Dict[str, Any] = {
                "model": cfg["model"],
                "messages": messages,
                "temperature": settings["temperature"],
                "max_tokens": settings["max_tokens"],
                "top_p": settings["top_p"],
                "stream": True,
            }
            if request.tools:
                payload["tools"] = request.tools
            if request.tool_choice is not None:
                payload["tool_choice"] = request.tool_choice
            stream = client.chat.completions.create(**payload)
        except Exception as exc:  # pragma: no cover
            raise ProviderError(str(exc)) from exc

        loop = asyncio.get_running_loop()

        async def iterate() -> AsyncIterator[GenerateStreamChunk]:
            try:
                while True:
                    chunk = await loop.run_in_executor(None, self._next_chunk, stream)
                    if chunk is None:
                        break
                    yield chunk
            finally:
                stream.close()

        index = 0
        async for chunk in iterate():
            index += 1
            raw_payload = (
                chunk.raw
                if isinstance(chunk.raw, (dict, list, str, int, float, bool, type(None)))
                else str(chunk.raw)
            )
            # log_audit_entry(
            #     event_type="generator_openrouter_stream_chunk",
            #     msg="[Generator/OpenRouter] Получен потоковый chunk.",
            #     status=AuditStatus.INFO,
            #     details={
            #         "model": cfg["model"],
            #         "index": index,
            #         "content": chunk.content,
            #         "done": chunk.done,
            #         "raw": raw_payload,
            #     },
            # )
            yield chunk

        log_audit_entry(
            event_type="generator_openrouter_stream_success",
            msg="[Generator/OpenRouter] Потоковая генерация завершена",
            status=AuditStatus.SUCCESS,
            details={"model": cfg["model"], "chunks": index},
        )
        print("[Generator] OpenRouter: поток завершён.")

    def _next_chunk(self, stream) -> GenerateStreamChunk | None:
        try:
            event = next(stream)
        except StopIteration:
            return None

        if not event or not getattr(event, "choices", None):
            return GenerateStreamChunk(
                provider=self.name, content="", raw=None, done=False
            )

        choice = event.choices[0]
        delta = getattr(choice, "delta", None)
        content = ""
        tool_calls: List[Dict[str, Any]] = []
        if delta and getattr(delta, "content", None):
            content = delta.content
        if delta and getattr(delta, "tool_calls", None):
            tool_calls = self._normalize_tool_calls(delta.tool_calls)

        done = bool(choice.finish_reason)

        return GenerateStreamChunk(
            provider=self.name,
            content=content or "",
            raw=event.model_dump() if hasattr(event, "model_dump") else event,
            done=done,
            tool_calls=tool_calls,
        )
