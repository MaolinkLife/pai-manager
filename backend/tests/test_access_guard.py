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
def test_testclient_host_treated_as_loopback(mode, tunnel_state):
    """Starlette TestClient sets client.host to 'testclient' — keep tests usable."""
    mode("tunnel_aware")
    tunnel_state(running=False)
    assert access_guard.is_request_allowed(
        client_host="testclient",
        headers=_headers(),
    )
