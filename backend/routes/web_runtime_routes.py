from fastapi import APIRouter, HTTPException, status

from modules.web_runtime import service as web_runtime_service
from modules.web_runtime.schemas import (
    WebRuntimeRequest,
    WebRuntimeResult,
    WebRuntimeSearchRequest,
    WebRuntimeSearchResult,
    WebRuntimeStatusResponse,
)

router = APIRouter(prefix="/api/web-runtime", tags=["Web Runtime"])


@router.get("/status", response_model=WebRuntimeStatusResponse)
def get_status() -> WebRuntimeStatusResponse:
    return web_runtime_service.get_runtime_status()


@router.get("/providers")
def get_providers() -> dict:
    status_payload = web_runtime_service.get_runtime_status()
    return {
        "extractors": status_payload.available_extractors,
        "active_extractor": status_payload.extractor_provider,
        "search_enabled": status_payload.search_enabled,
        "browser_enabled": status_payload.browser_enabled,
    }


@router.post("/extract", response_model=WebRuntimeResult)
def extract_webpage(request: WebRuntimeRequest) -> WebRuntimeResult:
    result = web_runtime_service.extract(request)
    if result.status == "error":
        detail = result.model_dump() if hasattr(result, "model_dump") else result.dict()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )
    return result


@router.post("/search", response_model=WebRuntimeSearchResult)
def search_web(request: WebRuntimeSearchRequest) -> WebRuntimeSearchResult:
    result = web_runtime_service.search(request)
    if result.status == "error":
        detail = result.model_dump() if hasattr(result, "model_dump") else result.dict()
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=detail,
        )
    return result
