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
import re
import time
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


# Headers a tunnel or a reverse proxy adds on the way in. A request that reaches
# the backend through the frontend dev server's proxy comes from 127.0.0.1, and a
# page opened straight from the address bar sends no Origin/Referer: these
# headers are what tell a shared link apart from the owner's own browser.
_FORWARDING_HEADERS = (
    "cf-connecting-ip",
    "cf-ray",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-real-ip",
    "forwarded",
)

# From outside, anyone may sign in and chat (the chat runs over the WebSocket);
# everything else belongs to the owner.
_GUEST_HTTP_ROUTES = {
    ("GET", "/api/auth/bootstrap-state"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/refresh"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/auth/me"),
    ("PATCH", "/api/auth/me/settings"),
}


def is_remote_request(*, client_host: Optional[str], headers: Mapping[str, str]) -> bool:
    """True when the request did not come from a browser on this machine."""
    if not (_is_loopback_host(client_host) or client_host == "testclient"):
        return True
    if any(_header(headers, name) for name in _FORWARDING_HEADERS):
        return True
    for name in ("origin", "referer"):
        host = _origin_host(_header(headers, name))
        if host and not _is_loopback_host(host):
            return True
    return False


def _bearer_user_role(headers: Mapping[str, str]) -> Optional[str]:
    parts = (_header(headers, "authorization") or "").split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        return None
    try:
        from modules.system import auth as auth_service  # local import to avoid cycles

        user = auth_service.get_user_from_access_token(parts[1].strip())
    except Exception:
        return None
    if not user:
        return None
    return str(getattr(user, "role", "") or "").strip().lower() or None


# One stored file; the library listing under the same prefix is not a file.
_MEDIA_FILE_PATH = re.compile(r"^/api/media/(?!library(?:/|$))([A-Za-z0-9-]+)$")


def _signed_media_request(verb: str, path: str, query: Optional[Mapping[str, str]]) -> bool:
    """An <img> tag sends no token: a media link signed by the server opens that one file."""
    if verb != "GET" or not query:
        return False
    match = _MEDIA_FILE_PATH.match(path)
    if not match:
        return False
    try:
        from modules.storage.service import media_link_is_valid  # local import to avoid cycles
    except Exception:
        return False
    return media_link_is_valid(match.group(1), query.get("exp"), query.get("sig"))


def remote_access_denial(
    *,
    method: str,
    path: str,
    client_host: Optional[str],
    headers: Mapping[str, str],
    query: Optional[Mapping[str, str]] = None,
) -> Optional[tuple[int, str]]:
    """Why a request from outside is refused (status, reason), or None when it may pass."""
    if not is_remote_request(client_host=client_host, headers=headers):
        return None
    verb = str(method or "").upper()
    normalized_path = "/" + str(path or "").strip("/")
    if verb == "OPTIONS" or (verb, normalized_path) in _GUEST_HTTP_ROUTES:
        return None
    if _signed_media_request(verb, normalized_path, query):
        return None
    role = _bearer_user_role(headers)
    if role is None:
        return 401, "Sign in as the owner to use this from outside."
    if role != "owner":
        return 403, "Only the owner can use this from outside."
    return None


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


_ADDRESS_NOT_TRUSTED = "not this machine and not the tunnel PAI started"
_DENIAL_LOG_INTERVAL_SECONDS = 300.0
_denials_logged: dict[tuple, float] = {}


def _log_denial(
    *,
    status: int,
    reason: str,
    method: str,
    path: str,
    client_host: Optional[str],
    headers: Mapping[str, str],
) -> None:
    """A refusal goes to the audit log, so the system knows who knocked.

    Once per status, area and caller within the interval: a refused page fires
    dozens of requests, the log needs one line.
    """
    caller = (
        _origin_host(_header(headers, "origin"))
        or _origin_host(_header(headers, "referer"))
        or _header(headers, "cf-connecting-ip")
        or _header(headers, "x-forwarded-for")
        or client_host
    )
    area = "/" + "/".join(str(path or "").strip("/").split("/")[:2])
    key = (status, area, caller)
    now = time.monotonic()
    last = _denials_logged.get(key)
    if last is not None and now - last < _DENIAL_LOG_INTERVAL_SECONDS:
        return
    _denials_logged[key] = now
    try:
        from modules.system.logger import AuditStatus, log_audit_entry  # local import to avoid cycles

        log_audit_entry(
            "access_guard_denied",
            "[AccessGuard] Request refused.",
            AuditStatus.WARNING,
            details={
                "status": status,
                "reason": reason,
                "method": method,
                "path": path,
                "from": caller,
                "tunnel_host": _tunnel_public_host(),
            },
        )
    except Exception:
        pass


def enforce_http(request: Request) -> None:
    if not is_request_allowed(
        client_host=_client_host(request),
        headers=request.headers,
    ):
        _log_denial(
            status=403,
            reason=_ADDRESS_NOT_TRUSTED,
            method=request.method,
            path=request.url.path,
            client_host=_client_host(request),
            headers=request.headers,
        )
        raise HTTPException(
            status_code=403,
            detail="API access denied by access guard policy.",
        )
    denial = remote_access_denial(
        method=request.method,
        path=request.url.path,
        client_host=_client_host(request),
        headers=request.headers,
        query=request.query_params,
    )
    if denial:
        _log_denial(
            status=denial[0],
            reason=denial[1],
            method=request.method,
            path=request.url.path,
            client_host=_client_host(request),
            headers=request.headers,
        )
        raise HTTPException(status_code=denial[0], detail=denial[1])


async def accept_ws(websocket: WebSocket) -> bool:
    """Returns True if the WS handshake passes the guard, else closes the socket."""
    if is_request_allowed(
        client_host=_client_host(websocket),
        headers=websocket.headers,
    ):
        return True
    _log_denial(
        status=403,
        reason=_ADDRESS_NOT_TRUSTED,
        method="WS",
        path="/api/ws",
        client_host=_client_host(websocket),
        headers=websocket.headers,
    )
    try:
        await websocket.close(code=1008, reason="API access denied by access guard policy.")
    except Exception:
        pass
    return False
