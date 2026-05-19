from __future__ import annotations

from modules.system.service import get_config_value
from modules.web_runtime.providers import EXTRACTOR_PROVIDERS
from modules.web_runtime.schemas import (
    WebPageDocument,
    WebRuntimeError,
    WebRuntimeRequest,
    WebRuntimeResult,
    WebRuntimeSearchRequest,
    WebRuntimeSearchResult,
    WebRuntimeStatusResponse,
)


def _coerce_timeout(value) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 8.0
    return min(max(parsed, 1.0), 60.0)


def _coerce_int(value, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, minimum), maximum)


def get_runtime_status() -> WebRuntimeStatusResponse:
    provider = str(get_config_value("web_runtime.extractor_provider", "basic") or "basic").strip().lower()
    return WebRuntimeStatusResponse(
        enabled=bool(get_config_value("web_runtime.enabled", True)),
        extractor_provider=provider,
        available_extractors=sorted(EXTRACTOR_PROVIDERS.keys()),
        search_enabled=bool(get_config_value("web_runtime.search.enabled", False)),
        browser_enabled=bool(get_config_value("web_runtime.browser.enabled", False)),
    )


def extract(request: WebRuntimeRequest | dict) -> WebRuntimeResult:
    request_model = request if isinstance(request, WebRuntimeRequest) else WebRuntimeRequest(**(request or {}))
    if not bool(get_config_value("web_runtime.enabled", True)):
        return WebRuntimeResult(
            status="error",
            provider="disabled",
            mode=request_model.mode,
            error=WebRuntimeError(code="disabled", message="Web runtime is disabled."),
        )

    provider_name = str(
        request_model.provider
        or get_config_value("web_runtime.extractor_provider", "basic")
        or "basic"
    ).strip().lower()

    if request_model.mode == "link":
        return WebRuntimeResult(
            status="ok",
            provider=provider_name,
            mode="link",
            document=WebPageDocument(url=request_model.url, title=request_model.url),
        )

    timeout = _coerce_timeout(
        request_model.timeout
        if request_model.timeout is not None
        else get_config_value("web_runtime.timeout", 8)
    )
    max_chars = _coerce_int(
        request_model.max_chars
        if request_model.max_chars is not None
        else get_config_value("web_runtime.max_chars", 12000),
        12000,
        minimum=500,
        maximum=100000,
    )
    max_bytes = _coerce_int(
        get_config_value("web_runtime.max_bytes", 2000000),
        2000000,
        minimum=65536,
        maximum=20000000,
    )
    allow_private_urls = bool(
        request_model.allow_private_urls
        if request_model.allow_private_urls is not None
        else get_config_value("web_runtime.allow_private_urls", False)
    )

    extractor_cls = EXTRACTOR_PROVIDERS.get(provider_name)
    if extractor_cls is None:
        return WebRuntimeResult(
            status="error",
            provider=provider_name,
            mode=request_model.mode,
            error=WebRuntimeError(
                code="provider_not_available",
                message=f"Web runtime provider '{provider_name}' is not available.",
            ),
        )

    result = extractor_cls().extract(
        request_model.url,
        timeout=timeout,
        max_chars=max_chars,
        allow_private_urls=allow_private_urls,
        max_bytes=max_bytes,
    )
    result.mode = request_model.mode
    return result


def extract_many(requests: list[WebRuntimeRequest | dict]) -> list[WebRuntimeResult]:
    return [extract(item) for item in (requests or [])]


def build_chat_context_block(context_items: list[dict] | None) -> str:
    if not isinstance(context_items, list) or not context_items:
        return ""

    requests: list[WebRuntimeRequest] = []
    for item in context_items:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "webpage" or not item.get("url"):
            continue
        mode = str(item.get("processing_mode") or item.get("mode") or "extract").strip().lower()
        requests.append(
            WebRuntimeRequest(
                url=str(item.get("url")),
                mode="link" if mode == "link" else "extract",
            )
        )

    if not requests:
        return ""

    results = extract_many(requests)
    link_lines: list[str] = []
    extract_blocks: list[str] = []

    for result in results:
        if result.mode == "link":
            if result.document:
                link_lines.append(f"- {result.document.url}")
            continue

        if result.status == "ok" and result.document:
            extract_blocks.append(
                f"- {result.document.title or result.document.url}\n"
                f"  URL: {result.document.url}\n"
                f"  Provider: {result.provider}\n"
                f"  Extracted text:\n{result.document.content[:6000]}"
            )
            continue

        error = result.error.message if result.error else "unknown error"
        failed_url = result.document.url if result.document else "-"
        extract_blocks.append(
            f"- {failed_url}: extraction failed via {result.provider} ({error})"
        )

    additions: list[str] = []
    if extract_blocks:
        additions.append("Attached webpage extracted content:\n" + "\n\n".join(extract_blocks))
    if link_lines:
        additions.append("Attached webpage URLs for context:\n" + "\n".join(link_lines))
    return "\n".join(additions).strip()


def search(request: WebRuntimeSearchRequest | dict) -> WebRuntimeSearchResult:
    request_model = request if isinstance(request, WebRuntimeSearchRequest) else WebRuntimeSearchRequest(**(request or {}))
    provider = str(
        request_model.provider
        or get_config_value("web_runtime.search.provider", "none")
        or "none"
    ).strip().lower()
    return WebRuntimeSearchResult(
        status="error",
        provider=provider,
        error=WebRuntimeError(
            code="not_implemented",
            message="Web search provider is not implemented yet.",
        ),
        meta={"query": request_model.query, "limit": request_model.limit},
    )


def extract_webpage_text(url: str) -> dict:
    """
    Backward-compatible wrapper used by older call sites.
    New code should consume WebRuntimeResult from extract().
    """
    result = extract(WebRuntimeRequest(url=url, mode="extract"))
    if result.status == "ok" and result.document:
        return {
            "url": result.document.url,
            "status": "ok",
            "title": result.document.title,
            "content": result.document.content,
            "content_length": result.document.content_length,
            "content_type": result.document.content_type,
            "provider": result.provider,
        }
    return {
        "url": url,
        "status": "error",
        "error": result.error.message if result.error else "unknown error",
        "code": result.error.code if result.error else "unknown_error",
        "provider": result.provider,
    }
