"""Regression tests for core.access_guard.

Cover the three modes and the tunnel-aware corner cases that motivated the
rewrite away from the AI_WAIFU_Y "local-only" middleware.
"""

from __future__ import annotations

import pytest

from core import access_guard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _headers(origin: str | None = None, referer: str | None = None) -> dict:
    out: dict[str, str] = {}
    if origin is not None:
        out["origin"] = origin
    if referer is not None:
        out["referer"] = referer
    return out


@pytest.fixture
def mode(monkeypatch):
    """Force a specific access mode regardless of DB state."""
    state = {"value": "tunnel_aware"}

    def _setter(new_value: str) -> None:
        state["value"] = new_value

    monkeypatch.setattr(access_guard, "get_mode", lambda: state["value"])
    return _setter


@pytest.fixture
def tunnel_state(monkeypatch):
    """Stub tunnel.runtime_snapshot for predictable host resolution."""
    state = {"running": False, "public_url": ""}

    def _setter(*, running: bool, public_url: str = "") -> None:
        state["running"] = running
        state["public_url"] = public_url

    def _fake_snapshot():
        return dict(state)

    # Patch the symbol the access_guard module actually calls.
    import modules.system.tunnel as tunnel_module

    monkeypatch.setattr(tunnel_module, "runtime_snapshot", _fake_snapshot)
    return _setter


# ---------------------------------------------------------------------------
# Test cases from the migration plan
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_tunnel_off_loopback_allowed(mode, tunnel_state):
    mode("tunnel_aware")
    tunnel_state(running=False)
    assert access_guard.is_request_allowed(
        client_host="127.0.0.1",
        headers=_headers(origin="http://127.0.0.1:3880"),
    )


@pytest.mark.regression
def test_tunnel_off_external_origin_blocked(mode, tunnel_state):
    mode("tunnel_aware")
    tunnel_state(running=False)
    assert not access_guard.is_request_allowed(
        client_host="127.0.0.1",
        headers=_headers(origin="http://evil.com"),
    )


@pytest.mark.regression
def test_tunnel_on_origin_matches_public_url(mode, tunnel_state):
    mode("tunnel_aware")
    tunnel_state(running=True, public_url="https://abc.trycloudflare.com")
    # Through tunnel the client_host is the cloudflare proxy IP, not loopback.
    assert access_guard.is_request_allowed(
        client_host="172.67.1.1",
        headers=_headers(origin="https://abc.trycloudflare.com"),
    )


@pytest.mark.regression
def test_tunnel_on_external_origin_still_blocked(mode, tunnel_state):
    mode("tunnel_aware")
    tunnel_state(running=True, public_url="https://abc.trycloudflare.com")
    assert not access_guard.is_request_allowed(
        client_host="172.67.1.1",
        headers=_headers(origin="http://evil.com"),
    )


@pytest.mark.regression
def test_strict_local_blocks_tunnel_traffic_even_when_running(mode, tunnel_state):
    mode("strict_local")
    tunnel_state(running=True, public_url="https://abc.trycloudflare.com")
    assert not access_guard.is_request_allowed(
        client_host="172.67.1.1",
        headers=_headers(origin="https://abc.trycloudflare.com"),
    )


@pytest.mark.regression
def test_strict_local_allows_loopback(mode, tunnel_state):
    mode("strict_local")
    tunnel_state(running=True, public_url="https://abc.trycloudflare.com")
    assert access_guard.is_request_allowed(
        client_host="127.0.0.1",
        headers=_headers(origin="http://localhost:3880"),
    )


@pytest.mark.regression
def test_open_mode_lets_everything_through(mode, tunnel_state):
    mode("open")
    tunnel_state(running=False)
    assert access_guard.is_request_allowed(
        client_host="203.0.113.7",
        headers=_headers(origin="http://evil.com"),
    )


# ---------------------------------------------------------------------------
# Boundary cases
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_loopback_without_origin_header_allowed(mode, tunnel_state):
    """Native curl / health probes without Origin must still be allowed locally."""
    mode("tunnel_aware")
    tunnel_state(running=False)
    assert access_guard.is_request_allowed(
        client_host="127.0.0.1",
        headers=_headers(),
    )


@pytest.mark.regression
def test_tunnel_on_but_no_origin_header_blocked(mode, tunnel_state):
    """
    Through the tunnel we can no longer trust the loopback client.host check,
    so absent Origin/Referer means we cannot prove the caller is the tunnel.
    """
    mode("tunnel_aware")
    tunnel_state(running=True, public_url="https://abc.trycloudflare.com")
    assert not access_guard.is_request_allowed(
        client_host="172.67.1.1",
        headers=_headers(),
    )


@pytest.mark.regression
def test_referer_used_when_origin_missing(mode, tunnel_state):
    mode("tunnel_aware")
    tunnel_state(running=True, public_url="https://abc.trycloudflare.com")
    assert access_guard.is_request_allowed(
        client_host="172.67.1.1",
        headers=_headers(referer="https://abc.trycloudflare.com/chat"),
    )


@pytest.mark.regression
def test_invalid_mode_falls_back_to_tunnel_aware(monkeypatch):
    """An unknown DB value must not silently open the gate."""
    monkeypatch.setattr(
        access_guard,
        "get_mode",
        lambda: "something-misspelled",
    )
    # Resolved internally by is_request_allowed via get_mode → fall back to default.
    # In tunnel_aware mode an external origin without tunnel must be blocked.
    import modules.system.tunnel as tunnel_module

    monkeypatch.setattr(
        tunnel_module,
        "runtime_snapshot",
        lambda: {"running": False, "public_url": ""},
    )
    assert not access_guard.is_request_allowed(
        client_host="203.0.113.7",
        headers=_headers(origin="http://evil.com"),
    )


@pytest.mark.regression
def test_testclient_host_treated_as_loopback_before_the_owner_rule(mode, tunnel_state):
    """Kept apart from the owner rule below: this is only about the address check."""
    mode("tunnel_aware")
    tunnel_state(running=False)
    assert access_guard.is_request_allowed(client_host="testclient", headers=_headers())


# ---------------------------------------------------------------------------
# From outside: anyone signs in and chats, everything else is the owner's
# ---------------------------------------------------------------------------


@pytest.fixture
def tokens(monkeypatch):
    """Access tokens that resolve to a role; anything else is not a valid token."""
    from types import SimpleNamespace

    import modules.system.auth as auth_module

    roles = {"owner-token": "owner", "user-token": "user"}

    def get_user_from_access_token(token):
        if token not in roles:
            raise ValueError("Invalid access token")
        return SimpleNamespace(uuid=f"{roles[token]}-uuid", role=roles[token])

    monkeypatch.setattr(auth_module, "get_user_from_access_token", get_user_from_access_token)


@pytest.mark.regression
@pytest.mark.parametrize(
    "client_host, headers",
    [
        ("172.67.1.1", {}),
        # Through the frontend dev server's proxy: loopback address, but the tunnel's headers.
        ("127.0.0.1", {"cf-connecting-ip": "203.0.113.7"}),
        ("127.0.0.1", {"x-forwarded-for": "203.0.113.7"}),
        ("127.0.0.1", {"origin": "https://abc.trycloudflare.com"}),
        ("127.0.0.1", {"referer": "https://abc.trycloudflare.com/chat"}),
    ],
)
def test_a_request_through_a_tunnel_is_remote(client_host, headers):
    assert access_guard.is_remote_request(client_host=client_host, headers=headers)


@pytest.mark.regression
@pytest.mark.parametrize(
    "headers",
    [{}, {"origin": "http://localhost:3880"}, {"referer": "http://127.0.0.1:3880/chat"}],
)
def test_the_owners_own_browser_is_local(headers):
    assert not access_guard.is_remote_request(client_host="127.0.0.1", headers=headers)


@pytest.mark.regression
@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", "/api/auth/bootstrap-state"),
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/register"),
        ("POST", "/api/auth/refresh"),
        ("GET", "/api/auth/me/"),
        ("OPTIONS", "/api/logger/"),
    ],
)
def test_from_outside_anyone_may_sign_in(method, path, tokens):
    assert access_guard.remote_access_denial(
        method=method, path=path, client_host="127.0.0.1", headers={"cf-connecting-ip": "203.0.113.7"}
    ) is None


@pytest.mark.regression
@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", "/api/logger/"),
        ("GET", "/api/debug_vault/"),
        ("GET", "/api/storage/library"),
        ("DELETE", "/api/storage/library/some-id"),
        ("GET", "/api/lorebook/"),
        ("POST", "/api/update/run"),
        ("GET", "/api/moral/state"),
        ("GET", "/api/config/"),
        ("GET", "/api/media/some-id"),
    ],
)
def test_from_outside_system_routes_are_the_owners(method, path, tokens):
    outside = {"cf-connecting-ip": "203.0.113.7"}

    anonymous = access_guard.remote_access_denial(method=method, path=path, client_host="127.0.0.1", headers=outside)
    broken = access_guard.remote_access_denial(
        method=method, path=path, client_host="127.0.0.1", headers={**outside, "authorization": "Bearer forged"}
    )
    user = access_guard.remote_access_denial(
        method=method, path=path, client_host="127.0.0.1", headers={**outside, "authorization": "Bearer user-token"}
    )
    owner = access_guard.remote_access_denial(
        method=method, path=path, client_host="127.0.0.1", headers={**outside, "authorization": "Bearer owner-token"}
    )

    assert anonymous is not None and anonymous[0] == 401
    assert broken is not None and broken[0] == 401
    assert user is not None and user[0] == 403
    assert owner is None


@pytest.mark.regression
def test_from_outside_a_signed_media_link_opens_that_one_file(tokens):
    from modules.storage.service import signed_media_url

    outside = {"cf-connecting-ip": "203.0.113.7"}
    url = signed_media_url("f4cb4620-be68-4fd8-84ef-21fb983d871c")
    path, query_string = url.split("?", 1)
    query = dict(part.split("=", 1) for part in query_string.split("&"))

    def denial(path_, query_):
        return access_guard.remote_access_denial(
            method="GET", path=path_, client_host="127.0.0.1", headers=outside, query=query_
        )

    assert denial(path, query) is None
    assert denial("/api/media/another-file", query) is not None
    assert denial(path, {**query, "sig": "0" * 64}) is not None
    assert denial("/api/media/library", query) is not None
    assert denial(path, None) is not None


@pytest.mark.regression
def test_an_expired_media_link_does_not_open():
    from modules.storage.service import media_link_is_valid, signed_media_url

    url = signed_media_url("file-1", now=1_000)
    query = dict(part.split("=", 1) for part in url.split("?", 1)[1].split("&"))

    assert media_link_is_valid("file-1", query["exp"], query["sig"], now=1_000)
    assert not media_link_is_valid("file-1", query["exp"], query["sig"], now=1_000 + 8 * 24 * 3600)


@pytest.mark.regression
def test_a_refusal_is_logged_once_per_caller_and_area(monkeypatch):
    from types import SimpleNamespace

    import modules.system.logger as logger_module

    events = []
    monkeypatch.setattr(logger_module, "log_audit_entry", lambda event, msg, status, details=None, **k: events.append(details))
    monkeypatch.setattr(access_guard, "_denials_logged", {})

    def request(path, ip="203.0.113.7"):
        return SimpleNamespace(
            client=SimpleNamespace(host="127.0.0.1"),
            headers={"cf-connecting-ip": ip},
            method="GET",
            url=SimpleNamespace(path=path),
            query_params={},
        )

    for path in ("/api/logger/", "/api/logger/page", "/api/debug_vault/"):
        with pytest.raises(access_guard.HTTPException):
            access_guard.enforce_http(request(path))

    assert [(event["status"], event["path"], event["from"]) for event in events] == [
        (401, "/api/logger/", "203.0.113.7"),
        (401, "/api/debug_vault/", "203.0.113.7"),
    ]


@pytest.mark.regression
def test_locally_the_owner_rule_does_not_apply(tokens):
    assert access_guard.remote_access_denial(
        method="GET", path="/api/logger/", client_host="127.0.0.1", headers={"origin": "http://localhost:3880"}
    ) is None


@pytest.mark.regression
def test_testclient_host_treated_as_loopback(mode, tunnel_state):
    """Starlette TestClient sets client.host to 'testclient' — keep tests usable."""
    mode("tunnel_aware")
    tunnel_state(running=False)
    assert access_guard.is_request_allowed(
        client_host="testclient",
        headers=_headers(),
    )
