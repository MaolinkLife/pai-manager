from __future__ import annotations

from modules.web_runtime.providers.basic import BasicWebExtractor
from modules.web_runtime.schemas import WebRuntimeRequest
from modules.web_runtime.service import build_chat_context_block, extract


class _FakeResponse:
    encoding = "utf-8"
    apparent_encoding = "utf-8"
    headers = {"content-type": "text/html; charset=utf-8"}

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int = 8192):
        yield b"<html><head><title>Hello</title><script>bad()</script></head>"
        yield b"<body><h1>Title</h1><p>Visible text</p></body></html>"


def test_web_runtime_link_mode_does_not_fetch():
    result = extract(WebRuntimeRequest(url="https://example.com", mode="link"))

    assert result.status == "ok"
    assert result.mode == "link"
    assert result.document is not None
    assert result.document.url == "https://example.com"
    assert result.document.content == ""


def test_basic_extractor_blocks_private_urls_by_default():
    result = BasicWebExtractor().extract(
        "http://127.0.0.1:9000",
        timeout=1,
        max_chars=1000,
        allow_private_urls=False,
        max_bytes=65536,
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "private_url_blocked"


def test_basic_extractor_strips_html_and_scripts(monkeypatch):
    def _fake_get(*args, **kwargs):
        return _FakeResponse()

    monkeypatch.setattr("modules.web_runtime.providers.basic.requests.get", _fake_get)

    result = BasicWebExtractor().extract(
        "https://example.com/page",
        timeout=1,
        max_chars=1000,
        allow_private_urls=True,
        max_bytes=65536,
    )

    assert result.status == "ok"
    assert result.document is not None
    assert result.document.title == "Hello"
    assert "Visible text" in result.document.content
    assert "bad()" not in result.document.content


def test_build_chat_context_block_combines_extract_and_link(monkeypatch):
    def _fake_get(*args, **kwargs):
        return _FakeResponse()

    monkeypatch.setattr("modules.web_runtime.providers.basic.requests.get", _fake_get)

    block = build_chat_context_block(
        [
            {"type": "webpage", "url": "https://example.com/extract", "mode": "extract"},
            {"type": "webpage", "url": "https://example.com/link", "mode": "link"},
        ]
    )

    assert "Attached webpage extracted content:" in block
    assert "Provider: basic" in block
    assert "Visible text" in block
    assert "Attached webpage URLs for context:" in block
    assert "https://example.com/link" in block
