from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


WebRuntimeStatus = Literal["ok", "error"]
WebRuntimeMode = Literal["extract", "link"]


class WebRuntimeRequest(BaseModel):
    url: str
    mode: WebRuntimeMode = "extract"
    provider: Optional[str] = None
    timeout: Optional[float] = None
    max_chars: Optional[int] = None
    allow_private_urls: Optional[bool] = None


class WebPageDocument(BaseModel):
    url: str
    title: str = ""
    content: str = ""
    content_length: int = 0
    content_type: str = ""


class WebRuntimeError(BaseModel):
    code: str
    message: str


class WebRuntimeResult(BaseModel):
    status: WebRuntimeStatus
    provider: str
    mode: WebRuntimeMode = "extract"
    document: Optional[WebPageDocument] = None
    error: Optional[WebRuntimeError] = None
    meta: dict = Field(default_factory=dict)


class WebRuntimeStatusResponse(BaseModel):
    enabled: bool
    extractor_provider: str
    available_extractors: list[str] = Field(default_factory=list)
    search_enabled: bool = False
    browser_enabled: bool = False


class WebRuntimeSearchRequest(BaseModel):
    query: str
    provider: Optional[str] = None
    limit: int = 5


class WebRuntimeSearchItem(BaseModel):
    title: str
    url: str
    snippet: str = ""


class WebRuntimeSearchResult(BaseModel):
    status: WebRuntimeStatus
    provider: str
    items: list[WebRuntimeSearchItem] = Field(default_factory=list)
    error: Optional[WebRuntimeError] = None
    meta: dict = Field(default_factory=dict)
