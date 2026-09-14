"""HTTP client helpers for interacting with the local Ollama server."""

from __future__ import annotations

import json
import time
import asyncio
from typing import Any, AsyncIterator, Dict, Iterable, Optional

import aiohttp
import requests

from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry, log_error
from modules.system.localization import get_text

# 127.0.0.1, not localhost: on Windows "localhost" tries IPv6 first, which
# doubles the wait whenever Ollama is not running.
OLLAMA_API_URL = "http://127.0.0.1:11434/api"
OLLAMA_STREAM_READ_TIMEOUT_SEC = 900
# A stopped Ollama costs a whole connection timeout per probe (about 2 s on
# Windows), so once it is found unreachable that is remembered for a while.
OLLAMA_UNAVAILABLE_TTL_SEC = 30.0
_unavailable_until = 0.0


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _resolve_text_model(model: Optional[str]) -> str:
    return model or config_service.get_config_value("api.model")


def _resolve_visual_model(model: Optional[str]) -> str:
    # The vision model comes from the vision settings only.
    return str(model or "").strip()


def _post_json_with_retries(
    url: str,
    *,
    payload: Dict[str, Any],
    timeout: int,
    retries: int = 2,
    retry_backoff_sec: float = 0.6,
) -> requests.Response:
    last_exc: Exception | None = None
    max_attempts = max(1, int(retries) + 1)

    for attempt in range(1, max_attempts + 1):
        try:
            log_audit_entry(
                event_type="ollama_http_post_json",
                msg="[Ollama] Sending HTTP JSON request.",
                status=AuditStatus.INFO,
                details={
                    "url": url,
                    "attempt": attempt,
                    "timeout": timeout,
                    "payload": payload,
                },
            )
            response = requests.post(url, json=payload, timeout=timeout)
        except requests.RequestException as exc:
            last_exc = exc
            if attempt >= max_attempts:
                break
            time.sleep(retry_backoff_sec * attempt)
            continue

        # Retry only transient statuses.
        log_audit_entry(
            event_type="ollama_http_response",
            msg="[Ollama] HTTP response received.",
            status=AuditStatus.INFO if response.status_code < 400 else AuditStatus.WARNING,
            details={
                "url": url,
                "attempt": attempt,
                "status_code": response.status_code,
                "reason": response.reason,
                "payload": payload,
            },
        )
        if response.status_code in {429, 500, 502, 503, 504} and attempt < max_attempts:
            time.sleep(retry_backoff_sec * attempt)
            continue
        return response

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Ollama request failed after retries.")


# ---------------------------------------------------------------------------
# Chat helpers
# ---------------------------------------------------------------------------

def _messages_to_prompts(messages: Iterable[Dict[str, Any]]) -> tuple[str, str]:
    system_segments: list[str] = []
    dialogue_segments: list[str] = []

    for message in messages:
        role = (message or {}).get("role")
        content = (message or {}).get("content", "")
        if not content:
            continue
        if role == "system":
            system_segments.append(content)
        elif role == "user":
            dialogue_segments.append(f"User: {content}")
        elif role == "assistant":
            dialogue_segments.append(f"Assistant: {content}")
        else:
            dialogue_segments.append(content)

    system_prompt = "\n\n".join(system_segments).strip()
    prompt = "\n\n".join(dialogue_segments).strip()
    return system_prompt, prompt


def _response_error_message(response: requests.Response) -> str:
    try:
        data = response.json()
    except Exception:
        data = None

    if isinstance(data, dict):
        error = data.get("error")
        if error:
            return str(error)

    text = (response.text or "").strip()
    return text or response.reason or f"HTTP {response.status_code}"


def _is_model_not_found(response: requests.Response) -> bool:
    if response.status_code != 404:
        return False
    error_text = _response_error_message(response).lower()
    return "model" in error_text and "not found" in error_text


def _raise_ollama_response_error(
    response: requests.Response,
    *,
    endpoint: str,
    model: str,
) -> None:
    error = _response_error_message(response)
    if _is_model_not_found(response):
        raise RuntimeError(
            f"Ollama model '{model}' is not installed. Pull it in Ollama or select another model."
        )
    raise RuntimeError(f"Ollama {endpoint} HTTP {response.status_code}: {error}")


def _chat_via_generate(
    messages: Iterable[Dict[str, Any]],
    options: Dict[str, Any],
    model: str,
) -> Dict[str, Any]:
    system_prompt, prompt = _messages_to_prompts(messages)
    request_options = dict(options or {})
    think_override = request_options.pop("__think", None)
    payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt or "",
        "stream": False,
        "options": request_options,
    }
    if think_override is not None:
        payload["think"] = bool(think_override)
    if system_prompt:
        payload["system"] = system_prompt

    response = requests.post(
        f"{OLLAMA_API_URL}/generate",
        json=payload,
        timeout=300,
    )
    if response.status_code >= 400:
        _raise_ollama_response_error(response, endpoint="/api/generate", model=model)
    data = response.json()
    text = data.get("response", "")
    return {
        "message": {
            "role": "assistant",
            "content": text,
        }
    }


def chat(messages: Iterable[Dict[str, Any]], options: Dict[str, Any], model: str | None = None) -> Dict[str, Any]:
    return chat_with_tools(messages, options, model=model)


def _has_tool_round(messages: Iterable[Dict[str, Any]]) -> bool:
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        if role == "tool":
            return True
        if role == "assistant" and isinstance(message.get("tool_calls"), list) and message.get("tool_calls"):
            return True
    return False


def chat_with_tools(
    messages: Iterable[Dict[str, Any]],
    options: Dict[str, Any],
    model: str | None = None,
    *,
    tools: Optional[Iterable[Dict[str, Any]]] = None,
    tool_choice: Optional[Any] = None,
) -> Dict[str, Any]:
    ollama_model = _resolve_text_model(model)
    message_list = list(messages)
    force_plain_after_tool_round = bool(tools) and _has_tool_round(message_list)
    request_options = dict(options or {})
    think_override = request_options.pop("__think", None)
    payload = {
        "model": ollama_model,
        "messages": message_list,
        "options": request_options,
        "stream": False,
    }
    if think_override is not None:
        payload["think"] = bool(think_override)
    if tools and not force_plain_after_tool_round:
        payload["tools"] = list(tools)
    if tool_choice is not None and not force_plain_after_tool_round:
        payload["tool_choice"] = tool_choice
    if force_plain_after_tool_round:
        log_audit_entry(
            event_type="ollama_chat_force_plain_after_tool_round",
            msg="[Ollama] Tool round detected; forcing plain chat for the next request.",
            status=AuditStatus.WARNING,
            details={"model": ollama_model},
        )
    try:
        response = _post_json_with_retries(
            f"{OLLAMA_API_URL}/chat",
            payload=payload,
            timeout=300,
            retries=2,
            retry_backoff_sec=0.8,
        )
        if response.status_code == 404:
            if _is_model_not_found(response):
                _raise_ollama_response_error(response, endpoint="/api/chat", model=ollama_model)
            return _chat_via_generate(message_list, request_options, ollama_model)
        if response.status_code == 400 and not tools:
            # Some Ollama/model combos sporadically reject chat payload format.
            # Gracefully fallback to /generate when no tool-calls are requested.
            return _chat_via_generate(messages, options, ollama_model)
        if response.status_code == 400 and ("tools" in payload or "tool_choice" in payload):
            # 4xx is not transient. Do not retry the same body; degrade once.
            log_audit_entry(
                event_type="ollama_chat_400_with_tools",
                msg="[Ollama] /chat returned 400 with tool payload; degrading to plain chat once.",
                status=AuditStatus.WARNING,
                details={"model": ollama_model, "payload": payload, "status_code": response.status_code},
            )
            degraded_payload = dict(payload)
            degraded_payload.pop("tool_choice", None)
            degraded_payload.pop("tools", None)
            degraded_response = _post_json_with_retries(
                f"{OLLAMA_API_URL}/chat",
                payload=degraded_payload,
                timeout=300,
                retries=0,
                retry_backoff_sec=0.0,
            )
            if degraded_response.status_code == 404:
                if _is_model_not_found(degraded_response):
                    _raise_ollama_response_error(
                        degraded_response,
                        endpoint="/api/chat",
                        model=ollama_model,
                    )
                return _chat_via_generate(message_list, request_options, ollama_model)
            if degraded_response.status_code == 400:
                log_audit_entry(
                    event_type="ollama_chat_400_degrade_failed",
                    msg="[Ollama] Plain-chat degrade after tool payload also returned 400; stopping retries.",
                    status=AuditStatus.ERROR,
                    details={"model": ollama_model, "payload": degraded_payload},
                )
            if degraded_response.status_code < 400:
                log_audit_entry(
                    event_type="ollama_chat_degraded_without_tools",
                    msg="[Ollama] Degraded retry without tools succeeded.",
                    status=AuditStatus.WARNING,
                    details={"model": ollama_model},
                )
                response = degraded_response
            else:
                response = degraded_response

        if response.status_code >= 400:
            _raise_ollama_response_error(response, endpoint="/api/chat", model=ollama_model)
        data = response.json()

        if "error" in data:
            log_audit_entry(
                event_type="ollama_error",
                msg=get_text(
                    "logger.ollama_error",
                    params={"error": data["error"]},
                    default=f"[Ollama] Error: {data['error']}",
                ),
                status=AuditStatus.ERROR,
                details={"model": ollama_model, "error": data["error"]},
                message_key="logger.ollama_error",
                message_args={"error": data["error"]},
            )
            raise RuntimeError(data["error"])

        return data
    except Exception as exc:
        log_error(f"[Ollama] HTTP error: {exc}")
        raise


async def stream_chat(
    messages: Iterable[Dict[str, Any]],
    options: Dict[str, Any],
    model: str | None = None,
    *,
    tools: Optional[Iterable[Dict[str, Any]]] = None,
    tool_choice: Optional[Any] = None,
) -> AsyncIterator[Dict[str, Any]]:
    ollama_model = _resolve_text_model(model)
    url = f"{OLLAMA_API_URL}/chat"
    message_list = list(messages)
    force_plain_after_tool_round = bool(tools) and _has_tool_round(message_list)
    request_options = dict(options or {})
    think_override = request_options.pop("__think", None)
    payload = {
        "model": ollama_model,
        "messages": message_list,
        "options": request_options,
        "stream": True,
    }
    if think_override is not None:
        payload["think"] = bool(think_override)
    if tools and not force_plain_after_tool_round:
        payload["tools"] = list(tools)
    if tool_choice is not None and not force_plain_after_tool_round:
        payload["tool_choice"] = tool_choice
    if force_plain_after_tool_round:
        log_audit_entry(
            event_type="ollama_stream_force_plain_after_tool_round",
            msg="[Ollama] Tool round detected; forcing plain stream chat for the next request.",
            status=AuditStatus.WARNING,
            details={"model": ollama_model},
        )

    log_audit_entry(
        event_type="ollama_http_post_json",
        msg="[Ollama] Sending HTTP JSON request.",
        status=AuditStatus.INFO,
        details={
            "url": url,
            "attempt": 1,
            "timeout": None,
            "payload": payload,
        },
    )

    timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_connect=30, sock_read=OLLAMA_STREAM_READ_TIMEOUT_SEC)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload) as resp:
            log_audit_entry(
                event_type="ollama_http_response",
                msg="[Ollama] HTTP response received.",
                status=AuditStatus.INFO if resp.status < 400 else AuditStatus.WARNING,
                details={
                    "url": url,
                    "attempt": 1,
                    "status_code": resp.status,
                    "reason": resp.reason,
                    "payload": payload,
                },
            )
            try:
                async for line in resp.content:
                    if not line.strip():
                        continue
                    try:
                        data = line.decode("utf-8").strip()
                        obj = json.loads(data)
                        if "error" in obj:
                            yield {"error": obj["error"]}
                            return
                        yield obj
                    except Exception as exc:
                        log_error(f"[Ollama stream parse error]: {exc}")
                        return
            except asyncio.TimeoutError:
                message = (
                    "Ollama stream read timeout: no chunks received for "
                    f"{OLLAMA_STREAM_READ_TIMEOUT_SEC}s"
                )
                log_audit_entry(
                    event_type="ollama_stream_read_timeout",
                    msg="[Ollama] Stream read timed out.",
                    status=AuditStatus.ERROR,
                    details={"model": ollama_model, "timeout_sec": OLLAMA_STREAM_READ_TIMEOUT_SEC},
                )
                yield {"error": message}
                return


# ---------------------------------------------------------------------------
# Visual helpers
# ---------------------------------------------------------------------------

def chat_image_response(
    messages: Iterable[Dict[str, Any]],
    model: str | None = None,
    *,
    options: Optional[Dict[str, Any]] = None,
    keep_alive: Optional[Any] = None,
) -> Dict[str, Any]:
    """The whole answer of a multimodal chat call.

    Returns ``{"content", "thinking", "done_reason"}`` or ``{"error"}``, so a
    caller can tell an empty answer from one the token limit cut. The
    ``__think`` option switches the model's reasoning on or off, as in the
    other chat helpers.
    """
    ollama_model_visual = _resolve_visual_model(model)
    request_options = dict(options or {})
    think_override = request_options.pop("__think", None)
    payload: Dict[str, Any] = {
        "model": ollama_model_visual,
        "messages": list(messages),
        "stream": False,
    }
    if request_options:
        payload["options"] = request_options
    if think_override is not None:
        payload["think"] = bool(think_override)
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
    try:
        response = _post_json_with_retries(
            f"{OLLAMA_API_URL}/chat",
            payload=payload,
            timeout=300,
            retries=2,
            retry_backoff_sec=0.8,
        )
        if response.status_code >= 400:
            body_preview = (response.text or "")[:500]
            log_error(
                f"[Ollama visual HTTP {response.status_code}] model={ollama_model_visual} body={body_preview}"
            )
            return {"error": f"Ollama HTTP {response.status_code}: {body_preview or response.reason}"}
        data = response.json()

        if "error" in data:
            log_error(f"[Ollama visual error]: {data['error']}")
            return {"error": str(data["error"])}

        message = data.get("message") or {}
        return {
            "content": message.get("content") or "",
            "thinking": message.get("thinking") or "",
            "done_reason": data.get("done_reason") or "",
        }
    except Exception as exc:
        log_error(f"[Ollama visual HTTP error]: {exc}")
        return {"error": f"Visual model request failed: {exc}"}


def chat_image(
    messages: Iterable[Dict[str, Any]],
    model: str | None = None,
    *,
    options: Optional[Dict[str, Any]] = None,
    keep_alive: Optional[Any] = None,
) -> str:
    result = chat_image_response(messages, model, options=options, keep_alive=keep_alive)
    if result.get("error"):
        return f"[ERROR] {result['error']}"
    return result.get("content", "")


async def stream_chat_image(
    messages: Iterable[Dict[str, Any]],
    model: str | None = None,
    *,
    options: Optional[Dict[str, Any]] = None,
    keep_alive: Optional[Any] = None,
) -> AsyncIterator[Dict[str, Any]]:
    ollama_model_visual = _resolve_visual_model(model)
    url = f"{OLLAMA_API_URL}/chat"
    request_options = dict(options or {})
    think_override = request_options.pop("__think", None)
    payload = {
        "model": ollama_model_visual,
        "messages": list(messages),
        "stream": True,
    }
    if request_options:
        payload["options"] = request_options
    if think_override is not None:
        payload["think"] = bool(think_override)
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            async for line in resp.content:
                if not line.strip():
                    continue
                try:
                    data = line.decode("utf-8").strip()
                    obj = json.loads(data)
                    if "error" in obj:
                        yield {"error": obj["error"]}
                        return
                    yield obj
                except Exception as exc:
                    log_error(f"[Ollama visual stream parse error]: {exc}")
                    return


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def is_available() -> bool:
    global _unavailable_until
    if time.monotonic() < _unavailable_until:
        return False
    try:
        response = requests.get(f"{OLLAMA_API_URL}/tags", timeout=5)
        available = response.status_code == 200
    except Exception:
        available = False
    _unavailable_until = 0.0 if available else time.monotonic() + OLLAMA_UNAVAILABLE_TTL_SEC
    return available


def list_models() -> Dict[str, Any]:
    if not is_available():
        return {
            "status": "error",
            "message": "Ollama not installed, not running or not accessible",
        }

    try:
        response = requests.get(f"{OLLAMA_API_URL}/tags", timeout=10)
        response.raise_for_status()
        data = response.json()
        models = [m["name"] for m in data.get("models", [])]
        return {"status": "ok", "models": models}
    except Exception as exc:
        return {"status": "error", "message": f"Ollama error: {exc}"}


async def pull_model_stream(model: str) -> AsyncIterator[Dict[str, Any]]:
    """Stream pull progress objects from the Ollama registry.

    Yields raw /api/pull JSON lines: {"status", "digest", "total", "completed"}
    and finally {"status": "success"}. Errors surface as {"error": "..."}.
    """
    url = f"{OLLAMA_API_URL}/pull"
    payload = {"model": model, "stream": True}
    timeout = aiohttp.ClientTimeout(total=None, sock_read=OLLAMA_STREAM_READ_TIMEOUT_SEC)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload) as resp:
            async for line in resp.content:
                raw = line.decode("utf-8", errors="ignore").strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except Exception:
                    continue
                yield obj
                if obj.get("error") or obj.get("status") == "success":
                    return


def delete_model(model: str) -> Dict[str, Any]:
    """Remove an installed model from the local Ollama store."""
    try:
        response = requests.delete(
            f"{OLLAMA_API_URL}/delete", json={"model": model}, timeout=30
        )
        if response.status_code == 404:
            return {"status": "error", "message": "Model not found"}
        response.raise_for_status()
        log_audit_entry(
            "ollama_model_deleted",
            "[Ollama] Model removed from local store.",
            AuditStatus.INFO,
            details={"model": model},
        )
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "message": f"Ollama error: {exc}"}


def list_runtime_models() -> Dict[str, Any]:
    if not is_available():
        return {
            "status": "error",
            "message": "Ollama not installed, not running or not accessible",
            "models": [],
        }

    try:
        installed_response = requests.get(f"{OLLAMA_API_URL}/tags", timeout=10)
        installed_response.raise_for_status()
        installed_data = installed_response.json()
        installed_models = installed_data.get("models", []) or []

        runtime_response = requests.get(f"{OLLAMA_API_URL}/ps", timeout=10)
        runtime_response.raise_for_status()
        runtime_data = runtime_response.json()
        loaded_models = runtime_data.get("models", []) or []
        loaded_by_name = {
            str(item.get("name") or item.get("model") or "").strip(): item
            for item in loaded_models
            if item.get("name") or item.get("model")
        }

        models = []
        for item in installed_models:
            name = str(item.get("name") or item.get("model") or "").strip()
            if not name:
                continue
            loaded = loaded_by_name.get(name)
            models.append(
                {
                    "name": name,
                    "model": name,
                    "loaded": loaded is not None,
                    "size": item.get("size"),
                    "digest": item.get("digest"),
                    "modified_at": item.get("modified_at"),
                    "details": item.get("details") or {},
                    "runtime": loaded or None,
                    "expires_at": (loaded or {}).get("expires_at") if loaded else None,
                    "size_vram": (loaded or {}).get("size_vram") if loaded else None,
                    "processor": ((loaded or {}).get("details") or {}).get("parameter_size") if loaded else None,
                }
            )

        installed_names = {item["name"] for item in models}
        for name, loaded in loaded_by_name.items():
            if name in installed_names:
                continue
            models.append(
                {
                    "name": name,
                    "model": name,
                    "loaded": True,
                    "size": loaded.get("size"),
                    "digest": loaded.get("digest"),
                    "modified_at": None,
                    "details": loaded.get("details") or {},
                    "runtime": loaded,
                    "expires_at": loaded.get("expires_at"),
                    "size_vram": loaded.get("size_vram"),
                    "processor": (loaded.get("details") or {}).get("parameter_size"),
                }
            )

        return {"status": "ok", "models": models}
    except Exception as exc:
        return {"status": "error", "message": f"Ollama runtime error: {exc}", "models": []}


def show_model(model: str) -> Dict[str, Any]:
    model_name = str(model or "").strip()
    if not model_name:
        return {"status": "error", "message": "model is required"}
    if not is_available():
        return {
            "status": "error",
            "message": "Ollama not installed, not running or not accessible",
        }

    try:
        response = requests.post(f"{OLLAMA_API_URL}/show", json={"model": model_name}, timeout=10)
        response.raise_for_status()
        return {"status": "ok", "model": model_name, "data": response.json()}
    except Exception as exc:
        return {"status": "error", "model": model_name, "message": f"Ollama error: {exc}"}


def model_capabilities(model: str) -> Dict[str, Any]:
    """What the model can do, as Ollama itself declares it (`/api/show` capabilities).

    No generation is run to find out, and nothing is guessed from the model name:
    a capability Ollama does not declare is absent. The owner marks what a
    model can do by hand in the model index.
    """
    model_name = str(model or "").strip()
    if not model_name:
        return {"status": "error", "model": model_name, "reason": "model is required", "capabilities": []}

    metadata = show_model(model_name)
    if metadata.get("status") != "ok":
        return {
            "status": "error",
            "model": model_name,
            "reason": metadata.get("message") or "model metadata unavailable",
            "capabilities": [],
        }
    declared = (metadata.get("data") or {}).get("capabilities")
    if not isinstance(declared, list):
        return {
            "status": "ok",
            "model": model_name,
            "declared": False,
            "reason": "Ollama does not report the model's capabilities; update Ollama",
            "capabilities": [],
        }
    return {
        "status": "ok",
        "model": model_name,
        "declared": True,
        "capabilities": sorted({str(item).strip().lower() for item in declared if str(item).strip()}),
    }


def model_supports_vision(model: str) -> Dict[str, Any]:
    info = model_capabilities(model)
    capabilities = info.get("capabilities") or []
    if "vision" in capabilities:
        return {"supported": True, "source": "ollama_show.capabilities", "capabilities": capabilities}
    return {
        "supported": False,
        "source": "ollama_show.capabilities" if info.get("status") == "ok" else "ollama_show_error",
        "reason": info.get("reason") or "model metadata does not declare vision",
        "capabilities": capabilities,
    }


def release_model(model: str | None = None) -> Dict[str, Any]:
    target_model = _resolve_text_model(model)
    if not target_model:
        return {"status": "error", "message": "model is required"}
    payload = {
        "model": target_model,
        "prompt": "",
        "stream": False,
        "keep_alive": 0,
    }
    try:
        response = requests.post(
            f"{OLLAMA_API_URL}/generate",
            json=payload,
            timeout=30,
        )
        if response.status_code >= 400:
            message = response.text[:300] or response.reason
            log_audit_entry(
                event_type="ollama_release_model_failed",
                msg="[Ollama] Failed to release model memory.",
                status=AuditStatus.WARNING,
                details={
                    "model": target_model,
                    "status_code": response.status_code,
                    "reason": response.reason,
                    "body": message,
                },
            )
            return {
                "status": "error",
                "model": target_model,
                "message": message,
                "status_code": response.status_code,
            }
        log_audit_entry(
            event_type="ollama_release_model_success",
            msg="[Ollama] Model memory released.",
            status=AuditStatus.INFO,
            details={"model": target_model},
        )
        return {"status": "ok", "model": target_model}
    except Exception as exc:
        log_audit_entry(
            event_type="ollama_release_model_error",
            msg="[Ollama] Error while releasing model memory.",
            status=AuditStatus.WARNING,
            details={"model": target_model, "error": str(exc)},
        )
        return {"status": "error", "model": target_model, "message": str(exc)}
