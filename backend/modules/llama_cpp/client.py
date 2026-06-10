"""HTTP client for llama-server's OpenAI-compatible endpoints.

llama.cpp exposes ``/v1/chat/completions``, ``/v1/embeddings``, ``/v1/models``,
``/props`` and ``/slots``. This module wraps them as plain functions so the
domain adapters in ``modules/generative/providers/llama_cpp.py`` (and later
analyzer/vision adapters) stay free of HTTP plumbing.

Naming convention matches ``modules.ollama.client``: callers pass
``base_url`` explicitly and pick a ``purpose`` tag that shows up in console
logs to make it easy to attribute traffic on a busy server.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Iterator

import httpx
import requests


def _payload_shape(payload: dict[str, Any]) -> dict[str, Any]:
    """Compact, log-safe summary of a chat payload."""
    messages = payload.get("messages") if isinstance(payload, dict) else []
    shapes: list[dict[str, Any]] = []
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, dict):
            shapes.append({"message_kind": type(message).__name__})
            continue
        content = message.get("content")
        shape: dict[str, Any] = {"role": message.get("role")}
        if isinstance(content, list):
            shape["content_kind"] = "list"
            shape["part_types"] = [
                part.get("type") if isinstance(part, dict) else type(part).__name__
                for part in content
            ]
            shape["image_parts"] = sum(
                1 for part in content
                if isinstance(part, dict) and part.get("type") == "image_url"
            )
        elif isinstance(content, str):
            shape["content_kind"] = "str"
            shape["content_length"] = len(content)
        else:
            shape["content_kind"] = type(content).__name__
        shapes.append(shape)
    return {
        "keys": sorted(payload.keys()),
        "model": payload.get("model"),
        "stream": payload.get("stream"),
        "message_count": len(messages) if isinstance(messages, list) else None,
        "messages": shapes,
    }


def _raise_for_status_with_body(response: requests.Response, *, payload: dict[str, Any]) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        body = (response.text or "")[:2000]
        raise requests.HTTPError(
            f"{exc}; response_body={body!r}; payload_shape={_payload_shape(payload)!r}",
            response=response,
        ) from exc


_SAMPLER_KEYS = (
    "max_tokens",
    "temperature",
    "top_p",
    "top_k",
    "min_p",
    "presence_penalty",
    "repeat_penalty",
)


def _chat_payload(
    *,
    messages: list[dict[str, Any]],
    stream: bool,
    model: str | None,
    sampler: dict[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"messages": messages, "stream": stream}
    if model:
        payload["model"] = model
    if sampler:
        for key in _SAMPLER_KEYS:
            value = sampler.get(key)
            if value is not None:
                payload[key] = value
    return payload


def chat_completion(
    *,
    base_url: str,
    messages: list[dict[str, Any]],
    model: str | None = None,
    sampler: dict[str, Any] | None = None,
    timeout: float,
    purpose: str = "chat_completion",
) -> dict[str, Any]:
    """Synchronous chat completion. Returns the parsed JSON response."""
    payload = _chat_payload(messages=messages, stream=False, model=model, sampler=sampler)
    print(
        f"[LLAMA CPP HTTP] purpose={purpose} endpoint=/v1/chat/completions "
        f"payload_shape={_payload_shape(payload)}",
        flush=True,
    )
    response = requests.post(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        json=payload,
        timeout=timeout,
    )
    _raise_for_status_with_body(response, payload=payload)
    data = response.json()
    return data if isinstance(data, dict) else {"raw": data}


def stream_chat_completion(
    *,
    base_url: str,
    messages: list[dict[str, Any]],
    model: str | None = None,
    sampler: dict[str, Any] | None = None,
    timeout: float,
    purpose: str = "chat_stream",
) -> Iterator[dict[str, Any]]:
    """SSE-style streaming chat completion. Yields each delta dict; final yield is ``{'done': True}``."""
    payload = _chat_payload(messages=messages, stream=True, model=model, sampler=sampler)
    with requests.post(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        json=payload,
        timeout=timeout,
        stream=True,
    ) as response:
        print(
            f"[LLAMA CPP HTTP] purpose={purpose} endpoint=/v1/chat/completions "
            f"payload_shape={_payload_shape(payload)}",
            flush=True,
        )
        _raise_for_status_with_body(response, payload=payload)
        for raw_line in response.iter_lines(decode_unicode=False):
            if isinstance(raw_line, bytes):
                line = raw_line.decode("utf-8", errors="replace").strip()
            else:
                line = str(raw_line or "").strip()
            if not line:
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            if line == "[DONE]":
                yield {"done": True}
                break
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                yield data


async def astream_chat_completion(
    *,
    base_url: str,
    messages: list[dict[str, Any]],
    model: str | None = None,
    sampler: dict[str, Any] | None = None,
    timeout: float,
    purpose: str = "chat_stream",
) -> AsyncIterator[dict[str, Any]]:
    """Async streaming variant for use from FastAPI/asyncio code paths."""
    payload = _chat_payload(messages=messages, stream=True, model=model, sampler=sampler)
    print(
        f"[LLAMA CPP HTTP] purpose={purpose} endpoint=/v1/chat/completions "
        f"payload_shape={_payload_shape(payload)}",
        flush=True,
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            f"{base_url.rstrip('/')}/v1/chat/completions",
            json=payload,
        ) as response:
            if response.status_code >= 400:
                # Drain a short body for diagnostics, mirror sync version.
                body = ""
                try:
                    body = (await response.aread()).decode("utf-8", errors="replace")[:2000]
                except Exception:
                    pass
                raise httpx.HTTPStatusError(
                    f"{response.status_code} from llama-server; "
                    f"response_body={body!r}; payload_shape={_payload_shape(payload)!r}",
                    request=response.request,
                    response=response,
                )
            async for raw_line in response.aiter_lines():
                line = (raw_line or "").strip()
                if not line:
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    yield {"done": True}
                    break
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    yield data


def embeddings(
    *,
    base_url: str,
    inputs: list[str],
    model: str | None = None,
    timeout: float,
) -> dict[str, Any]:
    """Batch embeddings via ``/v1/embeddings``."""
    payload: dict[str, Any] = {"input": inputs}
    if model:
        payload["model"] = model
    print(
        f"[LLAMA CPP HTTP] purpose=embedding endpoint=/v1/embeddings inputs={len(inputs)}",
        flush=True,
    )
    response = requests.post(
        f"{base_url.rstrip('/')}/v1/embeddings",
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {"raw": data}


def list_models(*, base_url: str, timeout: float = 5.0) -> dict[str, Any]:
    response = requests.get(f"{base_url.rstrip('/')}/v1/models", timeout=timeout)
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {"raw": data}


def server_props(*, base_url: str, timeout: float = 5.0) -> dict[str, Any]:
    response = requests.get(f"{base_url.rstrip('/')}/props", timeout=timeout)
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {"raw": data}


def server_slots(*, base_url: str, timeout: float = 5.0) -> dict[str, Any]:
    response = requests.get(f"{base_url.rstrip('/')}/slots", timeout=timeout)
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {"raw": data}


def ping(*, base_url: str, timeout: float = 2.0) -> bool:
    """Cheap reachability check. Used by adapters and runtime status endpoints."""
    try:
        response = requests.get(f"{base_url.rstrip('/')}/health", timeout=timeout)
        if response.status_code == 200:
            return True
        # Older builds may not expose /health; fall back to /props.
        response = requests.get(f"{base_url.rstrip('/')}/props", timeout=timeout)
        return response.status_code == 200
    except Exception:
        return False
