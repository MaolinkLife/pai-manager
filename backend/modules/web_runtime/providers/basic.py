from __future__ import annotations

import ipaddress
import re
import socket
from html import unescape
from urllib.parse import urlparse

import requests

from modules.web_runtime.schemas import WebPageDocument, WebRuntimeError, WebRuntimeResult


class BasicWebExtractor:
    name = "basic"

    def extract(
        self,
        url: str,
        *,
        timeout: float,
        max_chars: int,
        allow_private_urls: bool,
        max_bytes: int,
    ) -> WebRuntimeResult:
        normalized_url = str(url or "").strip()
        validation_error = self._validate_url(normalized_url, allow_private_urls)
        if validation_error:
            return WebRuntimeResult(
                status="error",
                provider=self.name,
                error=validation_error,
            )

        try:
            response = requests.get(
                normalized_url,
                timeout=timeout,
                headers={"User-Agent": "PAI-Manager/1.0"},
                stream=True,
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            raw = self._read_limited(response, max_bytes=max_bytes)
            encoding = response.encoding or response.apparent_encoding or "utf-8"
            html = raw.decode(encoding, errors="replace")
            title = self._extract_title(html, fallback=normalized_url)
            text = self._extract_text(html, content_type)
            full_length = len(text)
            text = text[:max_chars].strip()
            return WebRuntimeResult(
                status="ok",
                provider=self.name,
                document=WebPageDocument(
                    url=normalized_url,
                    title=title[:240],
                    content=text,
                    content_length=full_length,
                    content_type=content_type,
                ),
                meta={
                    "truncated": full_length > len(text),
                    "max_chars": max_chars,
                    "max_bytes": max_bytes,
                },
            )
        except Exception as exc:
            return WebRuntimeResult(
                status="error",
                provider=self.name,
                error=WebRuntimeError(code="fetch_failed", message=str(exc)[:500]),
            )

    def _validate_url(self, url: str, allow_private_urls: bool) -> WebRuntimeError | None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return WebRuntimeError(code="invalid_url", message="Only http/https URLs are supported.")
        if allow_private_urls:
            return None
        host = parsed.hostname
        if not host:
            return WebRuntimeError(code="invalid_url", message="URL host is missing.")
        try:
            addresses = socket.getaddrinfo(host, None)
            for address in addresses:
                ip = ipaddress.ip_address(address[4][0])
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    return WebRuntimeError(
                        code="private_url_blocked",
                        message="Private, loopback and reserved addresses are blocked.",
                    )
        except Exception as exc:
            return WebRuntimeError(code="host_resolution_failed", message=str(exc)[:300])
        return None

    def _read_limited(self, response: requests.Response, *, max_bytes: int) -> bytes:
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            remaining = max_bytes - total
            if remaining <= 0:
                break
            chunks.append(chunk[:remaining])
            total += min(len(chunk), remaining)
        return b"".join(chunks)

    def _extract_title(self, text: str, *, fallback: str) -> str:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
        if not title_match:
            return fallback
        return unescape(re.sub(r"\s+", " ", title_match.group(1)).strip()) or fallback

    def _extract_text(self, text: str, content_type: str) -> str:
        if "html" in content_type.lower() or "<html" in text[:500].lower():
            text = re.sub(r"(?is)<(script|style|noscript|svg|canvas).*?>.*?</\1>", " ", text)
            text = re.sub(r"(?is)<br\s*/?>", "\n", text)
            text = re.sub(r"(?is)</(p|div|li|section|article|header|footer|h[1-6])>", "\n", text)
            text = re.sub(r"(?is)<[^>]+>", " ", text)
        text = unescape(text)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n", text)
        return text.strip()
