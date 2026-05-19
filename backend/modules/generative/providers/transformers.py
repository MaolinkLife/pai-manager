from __future__ import annotations

import asyncio
import torch
from typing import Any, AsyncIterator, Dict, Iterable, List
from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer
from threading import Thread

from modules.generative.providers.base import GenerateProvider, ProviderError
from modules.generative.types import GenerateRequest, GenerateResult, GenerateStreamChunk
from modules.system import config as config_service


class TransformersGenerateProvider(GenerateProvider):
    name = "transformers"

    def __init__(self) -> None:
        self._model = None
        self._tokenizer = None
        self._loaded_model_id = None

    def supports_streaming(self) -> bool:
        return True

    def _get_provider_config(self) -> Dict[str, Any]:
        return config_service.get_config_value("api.providers.transformers", {}) or {}

    def is_available(self) -> bool:
        cfg = self._get_provider_config()
        return bool(cfg.get("model"))

    @staticmethod
    def _ensure_list(messages: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not isinstance(messages, list):
            messages = list(messages)

        sanitized = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            if not role:
                continue
            sanitized.append({
                "role": role,
                "content": item.get("content") if item.get("content") is not None else "",
            })
        return sanitized

    def _resolve_dtype(self, value: Any):
        if value in (None, "", "auto"):
            return "auto"
        if value in ("bfloat16", "bf16"):
            return torch.bfloat16
        if value in ("float16", "fp16"):
            return torch.float16
        if value in ("float32", "fp32"):
            return torch.float32
        return "auto"

    def _load(self, model_override: str | None = None):
        cfg = self._get_provider_config()
        model_id = model_override or cfg.get("model")
        if not model_id:
            raise ProviderError("Transformers provider: не задана модель")

        if self._model is not None and self._loaded_model_id == model_id:
            return self._model, self._tokenizer

        dtype = self._resolve_dtype(cfg.get("torch_dtype", "auto"))

        kwargs = {
            "device_map": cfg.get("device_map", "auto"),
            "torch_dtype": dtype,
        }

        if cfg.get("trust_remote_code") is not None:
            kwargs["trust_remote_code"] = bool(cfg.get("trust_remote_code"))

        if cfg.get("low_cpu_mem_usage") is not None:
            kwargs["low_cpu_mem_usage"] = bool(cfg.get("low_cpu_mem_usage"))

        self._model = AutoModelForCausalLM.from_pretrained(model_id, **kwargs)
        self._tokenizer = AutoTokenizer.from_pretrained(
            model_id,
            trust_remote_code=bool(cfg.get("trust_remote_code", True)),
        )
        self._loaded_model_id = model_id

        return self._model, self._tokenizer

    def _build_generate_kwargs(self, request: GenerateRequest, cfg: Dict[str, Any]) -> Dict[str, Any]:
        options = dict(request.options or {})

        max_tokens = (
            options.get("max_new_tokens")
            or options.get("num_predict")
            or options.get("max_tokens")
            or cfg.get("max_new_tokens")
            or 2048
        )

        return {
            "max_new_tokens": int(max_tokens),
            "do_sample": bool(options.get("do_sample", cfg.get("do_sample", True))),
            "temperature": float(options.get("temperature", cfg.get("temperature", 0.7))),
            "top_p": float(options.get("top_p", cfg.get("top_p", 0.8))),
            "top_k": int(options.get("top_k", cfg.get("top_k", 20))),
            "repetition_penalty": float(options.get("repetition_penalty", cfg.get("repetition_penalty", 1.1))),
        }

    def generate(self, request: GenerateRequest) -> GenerateResult:
        cfg = self._get_provider_config()
        model_override = (request.metadata or {}).get("model")
        model, tokenizer = self._load(model_override)
        messages = self._ensure_list(request.messages)

        try:
            inputs = tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                return_tensors="pt",
                return_dict=True,
            ).to(model.device)

            input_len = inputs["input_ids"].shape[-1]
            generated = model.generate(
                **inputs,
                **self._build_generate_kwargs(request, cfg),
            )

            output_ids = generated[0][input_len:]
            content = tokenizer.decode(output_ids, skip_special_tokens=True).strip()

            return GenerateResult(
                provider=self.name,
                content=content,
                raw=None,
                metadata={"model": model_override or cfg.get("model"), "source": cfg.get("source", "huggingface")},
            )
        except Exception as exc:
            raise ProviderError(f"Transformers provider: {exc}") from exc

    async def stream(self, request: GenerateRequest) -> AsyncIterator[GenerateStreamChunk]:
        cfg = self._get_provider_config()
        model_override = (request.metadata or {}).get("model")
        model, tokenizer = self._load(model_override)
        messages = self._ensure_list(request.messages)

        try:
            inputs = tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                return_tensors="pt",
                return_dict=True,
            ).to(model.device)

            streamer = TextIteratorStreamer(
                tokenizer,
                skip_prompt=True,
                skip_special_tokens=True,
            )

            kwargs = {
                **inputs,
                **self._build_generate_kwargs(request, cfg),
                "streamer": streamer,
            }

            thread = Thread(target=model.generate, kwargs=kwargs)
            thread.start()

            loop = asyncio.get_running_loop()

            while True:
                text = await loop.run_in_executor(None, self._next_stream_text, streamer)
                if text is None:
                    break
                yield GenerateStreamChunk(
                    provider=self.name,
                    content=text,
                    done=False,
                    metadata={"model": model_override or cfg.get("model"), "source": cfg.get("source", "huggingface")},
                )

            yield GenerateStreamChunk(
                provider=self.name,
                content="",
                done=True,
                metadata={"model": model_override or cfg.get("model"), "source": cfg.get("source", "huggingface")},
            )

            thread.join(timeout=1)
        except Exception as exc:
            raise ProviderError(f"Transformers provider stream: {exc}") from exc

    @staticmethod
    def _next_stream_text(streamer):
        try:
            return next(streamer)
        except StopIteration:
            return None

    def release_resources(self) -> None:
        cfg = self._get_provider_config()
        keep_loaded = bool(cfg.get("keep_loaded", True))
        if keep_loaded:
            return

        self._model = None
        self._tokenizer = None
        self._loaded_model_id = None

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
