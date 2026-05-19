from __future__ import annotations
import re
import json
from typing import Any, AsyncIterator, Dict, Iterable, List

from modules.generative.providers.base import GenerateProvider, ProviderError
from modules.generative.types import (
    GenerateRequest,
    GenerateResult,
    GenerateStreamChunk,
)
from modules.ollama import client as ollama_client
from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry


class OllamaGenerateProvider(GenerateProvider):
    name = "ollama"
    _TOKEN_SEGMENT_PATTERN = re.compile(r"\S+\s*")
    _REASONING_MODEL_HINTS = (
        "r1",
        "qwq",
        "reason",
        "thinking",
    )

    def supports_streaming(self) -> bool:
        return True

    def release_resources(self) -> None:
        cfg = self._get_provider_config()
        model = cfg.get("model")
        ollama_client.release_model(model=model)

    def _get_provider_config(self) -> Dict[str, Any]:
        provider_cfg = config_service.get_config_value("api.providers.ollama", {}) or {}
        # Backward compatibility: падаем в api.model, если в providers нет model.
        legacy_model = config_service.get_config_value("api.model")
        if legacy_model and "model" not in provider_cfg:
            provider_cfg["model"] = legacy_model
        return provider_cfg

    def _looks_reasoning_model(self, model: str | None) -> bool:
        model_name = (model or "").strip().lower()
        if not model_name:
            return False
        return any(hint in model_name for hint in self._REASONING_MODEL_HINTS)

    def _prepare_options_for_request(
        self,
        request: GenerateRequest,
        *,
        model: str | None,
        cfg: Dict[str, Any],
    ) -> tuple[Dict[str, Any], int | None]:
        """
        Best-effort policy:
        - if provider/model supports reasoning split, do not bind reasoning to output limit;
        - otherwise keep standard behavior.
        """
        options = dict(request.options or {})
        soft_output_limit: int | None = None

        base_limit_raw = options.get("num_predict", options.get("max_tokens", cfg.get("max_tokens")))
        try:
            base_limit = int(base_limit_raw) if base_limit_raw is not None else None
        except (TypeError, ValueError):
            base_limit = None

        request_mode = str((request.metadata or {}).get("mode") or "").strip()
        if "empty_content_recovery" in request_mode or "repeat_recovery" in request_mode:
            recovery_limit = min(max(int(base_limit or 512), 128), 512)
            options["num_predict"] = recovery_limit
            options["max_tokens"] = recovery_limit
            options["__think"] = False
            return options, None

        enable_unbounded = bool(
            config_service.get_config_value(
                "generate_settings.unbounded_reasoning_if_supported",
                True,
            )
        )
        if not (enable_unbounded and self._looks_reasoning_model(model) and base_limit and base_limit > 0):
            return options, None

        headroom_raw = config_service.get_config_value(
            "generate_settings.reasoning_headroom_tokens",
            512,
        )
        try:
            headroom = max(0, min(int(headroom_raw), 2048))
        except (TypeError, ValueError):
            headroom = 512

        expanded_limit = base_limit + headroom
        options["num_predict"] = expanded_limit
        options["max_tokens"] = expanded_limit
        soft_output_limit = base_limit
        return options, soft_output_limit

    def _truncate_visible_content(self, content: str, soft_limit_tokens: int | None) -> str:
        if not content or not soft_limit_tokens or soft_limit_tokens <= 0:
            return content
        segments = self._TOKEN_SEGMENT_PATTERN.findall(content)
        if len(segments) <= soft_limit_tokens:
            return content
        return "".join(segments[:soft_limit_tokens]).rstrip()

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
            images = item.get("images")
            if role == "user" and isinstance(images, list) and images:
                payload["images"] = [str(image) for image in images if str(image).strip()]
            if role == "assistant" and isinstance(item.get("tool_calls"), list):
                payload["tool_calls"] = OllamaGenerateProvider._normalize_tool_calls(
                    item.get("tool_calls")
                )
            if role == "tool":
                tool_call_id = str(item.get("tool_call_id") or "").strip()
                if tool_call_id:
                    payload["tool_call_id"] = tool_call_id
                name = str(item.get("name") or "").strip()
                if name:
                    payload["name"] = name
            sanitized.append(payload)
        return sanitized

    @staticmethod
    def _normalize_tool_calls(raw_tool_calls: Any) -> List[Dict[str, Any]]:
        if not isinstance(raw_tool_calls, list):
            return []

        normalized: List[Dict[str, Any]] = []
        for idx, item in enumerate(raw_tool_calls):
            if not isinstance(item, dict):
                continue
            function = item.get("function") or {}
            if not isinstance(function, dict):
                function = {}
            name = str(function.get("name") or "").strip()
            if not name:
                continue
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                args_payload = arguments
            else:
                try:
                    args_payload = json.dumps(arguments or {}, ensure_ascii=False)
                except Exception:
                    args_payload = "{}"

            normalized.append(
                {
                    "id": str(item.get("id") or f"ollama_tool_{idx + 1}"),
                    "type": str(item.get("type") or "function"),
                    "function": {
                        "name": name,
                        "arguments": args_payload,
                    },
                }
            )
        return normalized

    def generate(self, request: GenerateRequest) -> GenerateResult:
        cfg = self._get_provider_config()
        model = (request.metadata or {}).get("model") or cfg.get("model")
        if not model:
            raise ProviderError("Ollama provider: не задана модель")

        messages = self._ensure_list(request.messages)
        prepared_options, soft_output_limit = self._prepare_options_for_request(
            request,
            model=model,
            cfg=cfg,
        )

        print("[Generator] Ollama: синхронная генерация.")
        log_audit_entry(
            event_type="generator_ollama_start",
            msg="[Generator] Запуск синхронной генерации",
            status=AuditStatus.INFO,
            details={
                "model": model,
                "messages": messages,
                "options": prepared_options,
                "metadata": request.metadata,
            },
        )

        raw = ollama_client.chat_with_tools(
            messages,
            prepared_options,
            model=model,
            tools=request.tools,
            tool_choice=request.tool_choice,
        )
        message_payload = raw.get("message", {}) or {}
        content = self._truncate_visible_content(
            message_payload.get("content", ""),
            soft_output_limit,
        )
        reasoning = message_payload.get("thinking") or raw.get("thinking") or ""
        tool_calls = self._normalize_tool_calls(message_payload.get("tool_calls"))

        log_audit_entry(
            event_type="generator_ollama_success",
            msg="[Generator] Генерация завершена",
            status=AuditStatus.SUCCESS,
            details={
                "model": model,
                "response": raw,
                "content_length": len(content),
            },
        )
        print("[Generator] Ollama: ответ получен.")

        return GenerateResult(
            provider=self.name,
            content=content,
            raw=raw,
            reasoning=reasoning or None,
            metadata={"model": model},
            tool_calls=tool_calls,
        )

    async def stream(
        self, request: GenerateRequest
    ) -> AsyncIterator[GenerateStreamChunk]:
        cfg = self._get_provider_config()
        model = (request.metadata or {}).get("model") or cfg.get("model")
        if not model:
            raise ProviderError("Ollama provider: не задана модель")

        messages = self._ensure_list(request.messages)
        prepared_options, soft_output_limit = self._prepare_options_for_request(
            request,
            model=model,
            cfg=cfg,
        )

        print("[Generator] Ollama: потоковая генерация.")
        log_audit_entry(
            event_type="generator_ollama_stream_start",
            msg="[Generator] Запуск потоковой генерации",
            status=AuditStatus.INFO,
            details={
                "model": model,
                "messages": messages,
                "options": prepared_options,
                "metadata": request.metadata,
                "output_soft_limit_tokens": soft_output_limit,
            },
        )

        chunk_index = 0
        async for chunk in ollama_client.stream_chat(
            messages,
            prepared_options,
            model=model,
            tools=request.tools,
            tool_choice=request.tool_choice,
        ):
            if not chunk:
                continue
            if "error" in chunk:
                raise ProviderError(chunk["error"])
            message_payload = chunk.get("message", {}) or {}
            content = message_payload.get("content", "")
            reasoning = message_payload.get("thinking") or chunk.get("thinking") or ""
            tool_calls = self._normalize_tool_calls(message_payload.get("tool_calls"))
            chunk_index += 1
            # log_audit_entry(
            #     event_type="generator_ollama_stream_chunk",
            #     msg="[Generator] Получен потоковый chunk от Ollama.",
            #     status=AuditStatus.INFO,
            #     details={
            #         "model": model,
            #         "index": chunk_index,
            #         "content": content,
            #         "done": bool(chunk.get("done")),
            #         "raw": chunk,
            #     },
            # )
            yield GenerateStreamChunk(
                provider=self.name,
                content=content,
                reasoning=reasoning or None,
                raw=chunk,
                done=bool(chunk.get("done")),
                tool_calls=tool_calls,
                metadata={
                    "model": model,
                    "output_soft_limit_tokens": soft_output_limit,
                },
            )

        log_audit_entry(
            event_type="generator_ollama_stream_success",
            msg="[Generator] Потоковая генерация завершена",
            status=AuditStatus.SUCCESS,
            details={"model": model, "chunks": chunk_index},
        )
        print("[Generator] Ollama: поток завершён.")
