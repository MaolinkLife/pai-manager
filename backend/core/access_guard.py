"""HTTP/WS access guard.

Three modes, configured via DB key ``system.api_access_mode``:

* ``open``           — legacy permissive mode (no host/origin checks).
* ``strict_local``   — only loopback clients with loopback ``Origin``/``Referer``.
* ``tunnel_aware``   — default; loopback as in strict mode, plus the currently
  active tunnel ``public_url`` if ``modules.system.tunnel`` reports it running.

The guard is intentionally narrow: it rejects unauthenticated cross-origin calls
to the backend, so the existing ``CORS *`` configuration no longer leaves the
API wide open to any web page the user happens to visit. Tunnel traffic keeps
working because we honour ``tunnel.runtime_snapshot()`` per request.
"""

from __future__ import annotations

import ipaddress
from typing import Mapping, Optional
from urllib.parse import urlparse

from fastapi import HTTPException, Request, WebSocket


_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_DEFAULT_MODE = "tunnel_aware"
_VALID_MODES = {"open", "strict_local", "tunnel_aware"}


def get_mode() -> str:
    """Resolve current mode from DB-first config. Falls back to default on errors."""
    try:
        from modules.system import config as config_service  # local import to avoid cycles

        raw = config_service.get_config_value("system.api_access_mode", default=_DEFAULT_MODE)
        mode = str(raw or _DEFAULT_MODE).strip().lower()
        return mode if mode in _VALID_MODES else _DEFAULT_MODE
    except Exception:
        return _DEFAULT_MODE


def _tunnel_public_host() -> Optional[str]:
    try:
        from modules.system import tunnel as tunnel_service

        snapshot = tunnel_service.runtime_snapshot()
    except Exception:
        return None
    if not snapshot.get("running"):
        return None
    parsed = urlparse(str(snapshot.get("public_url") or ""))
    host = parsed.hostname
    return host.lower() if host else None


def _is_loopback_host(host: Optional[str]) -> bool:
    if not host:
        return False
    normalized = host.strip().lower().strip("[]")
    if normalized in _LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _origin_host(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https", "ws", "wss"}:
        return None
    return parsed.hostname.lower() if parsed.hostname else None


def _header(headers: Mapping[str, str], name: str) -> Optional[str]:
    try:
        value = headers.get(name)
    except Exception:
        return None
    if value is None:
        return None
    value = value.strip()
    return value or None


def is_request_allowed(
    *,
    client_host: Optional[str],
    headers: Mapping[str, str],
    mode: Optional[str] = None,
) -> bool:
    effective = mode if mode in _VALID_MODES else get_mode()
    if effective == "open":
        return True

    origin_host = _origin_host(_header(headers, "origin"))
    referer_host = _origin_host(_header(headers, "referer"))

    # The header_host is what the caller *claimed* — must match either loopback
    # or (in tunnel_aware mode) the public tunnel host.
    def _host_allowed(host: Optional[str], *, allow_tunnel: bool) -> bool:
        if host is None:
            return True  # header absent → don't reject on this alone
        if _is_loopback_host(host):
            return True
        if allow_tunnel:
            tunnel_host = _tunnel_public_host()
            if tunnel_host and host == tunnel_host:
                return True
        return False

    allow_tunnel = effective == "tunnel_aware"

    # When request arrives through a tunnel, client_host is the tunnel proxy's
    # IP — not loopback. We accept it only if Origin/Referer prove the caller
    # is the tunnel's public URL.
    client_loopback = _is_loopback_host(client_host) or client_host == "testclient"

    if not client_loopback:
        # Non-loopback client is only allowed via tunnel.
        if not allow_tunnel:
            return False
        if not (_tunnel_public_host()):
            return False
        # Must positively assert tunnel origin in at least one header.
        if origin_host is None and referer_host is None:
            return False

    if not _host_allowed(origin_host, allow_tunnel=allow_tunnel):
        return False
    if not _host_allowed(referer_host, allow_tunnel=allow_tunnel):
        return False
    return True


def _client_host(scope) -> Optional[str]:
    client = getattr(scope, "client", None)
    return getattr(client, "host", None) if client else None


def enforce_http(request: Request) -> None:
    if not is_request_allowed(
        client_host=_client_host(request),
        headers=request.headers,
    ):
        raise HTTPException(
            status_code=403,
            detail="API access denied by access guard policy.",
        )


async def accept_ws(websocket: WebSocket) -> bool:
    """Returns True if the WS handshake passes the guard, else closes the socket."""
    if is_request_allowed(
        client_host=_client_host(websocket),
        headers=websocket.headers,
    ):
        return True
    try:
        await websocket.close(code=1008, reason="API access denied by access guard policy.")
    except Exception:
        pass
    return False
