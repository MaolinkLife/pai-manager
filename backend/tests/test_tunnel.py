"""The tunnel PAI starts itself, and the address the access guard trusts.

The case: a phone opens PAI through a cloudflared quick
tunnel. The guard trusts only the address PAI read from its own tunnel, so
that address must be the tunnel's and nothing else: cloudflared prints its
terms-of-use link first, and that link once ended up as the stored address.
The tunnel opens PAI's own web interface, whose port comes from
config/port-config.json.
"""

import json
from types import SimpleNamespace

import pytest

from modules.system import tunnel

pytestmark = pytest.mark.regression

# Lines as cloudflared prints them for a quick tunnel.
CLOUDFLARED_TERMS_LINE = (
    "2026-09-13T10:00:00Z INF Thank you for trying Cloudflare Tunnel. Doing so, without a Cloudflare account, "
    "is a quick way to experiment and try it out. However, be aware that these account-less Tunnels have no "
    "uptime guarantee, are subject to the Cloudflare Online Services Terms of Use "
    "(https://www.cloudflare.com/website-terms/), and Cloudflare reserves the right to investigate your use of "
    "Tunnels for violations of such terms. If you intend to use Tunnels in production you should use a "
    "pre-created named tunnel by following: https://developers.cloudflare.com/cloudflare-one/connections/"
)
CLOUDFLARED_URL_LINE = "2026-09-13T10:00:03Z INF |  https://quiet-river-sample.trycloudflare.com                  |"


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.setattr(tunnel, "log_audit_entry", lambda *a, **k: None)
    saved = dict(tunnel._STATE)
    yield
    tunnel._STATE.clear()
    tunnel._STATE.update(saved)
    tunnel._PROCESS = None
    tunnel._READER_THREAD = None
    tunnel._ACTIVE_USER_UUID = None


@pytest.fixture
def port_config(tmp_path, monkeypatch):
    def write(content):
        (tmp_path / "config").mkdir(exist_ok=True)
        (tmp_path / "config" / "port-config.json").write_text(content, encoding="utf-8")

    monkeypatch.setattr(tunnel, "PROJECT_DIR", str(tmp_path))
    return write


def test_the_terms_of_use_link_is_not_the_tunnel_address():
    assert tunnel._extract_public_url(CLOUDFLARED_TERMS_LINE) is None


@pytest.mark.parametrize(
    "line, url",
    [
        (CLOUDFLARED_URL_LINE, "https://quiet-river-sample.trycloudflare.com"),
        ("your url is: https://calm-fox.loca.lt", "https://calm-fox.loca.lt"),
        ("Forwarding https://a1b2.ngrok-free.app -> http://localhost:3880", "https://a1b2.ngrok-free.app"),
    ],
)
def test_a_tunnel_address_is_read(line, url):
    assert tunnel._extract_public_url(line) == url


def test_the_web_interface_port_comes_from_port_config(port_config):
    port_config(json.dumps({"frontend": 4321, "backend": 9000}))

    cfg = tunnel._normalize_tunneling_cfg({"local_url": "http://127.0.0.1:4200", "local_port": 4200})

    assert (cfg["local_port"], cfg["local_url"]) == (4321, "http://localhost:4321")


@pytest.mark.parametrize("content", ["not json", json.dumps({"frontend": "abc"}), json.dumps({"frontend": 0})])
def test_a_broken_port_config_falls_back_to_the_default_port(port_config, content):
    port_config(content)

    assert tunnel._frontend_port() == 3880


def test_cloudflared_opens_the_web_interface_with_its_own_host_name(port_config):
    port_config(json.dumps({"frontend": 3880}))

    command = tunnel._build_command(tunnel._normalize_tunneling_cfg({"provider": "cloudflared"}))

    assert command == [
        "cloudflared", "tunnel", "--url", "http://localhost:3880", "--http-host-header", "localhost:3880",
    ]


def test_a_stored_garbage_address_is_dropped():
    cfg = tunnel._normalize_tunneling_cfg({"public_url": "https://www.cloudflare.com/website-terms/),"})

    assert cfg["public_url"] == ""


def test_a_new_tunnel_does_not_inherit_the_stored_address(monkeypatch):
    class FakeProcess:
        pid = 4242
        stdout = None

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(
        tunnel,
        "_load_user_tunneling_cfg",
        lambda user_uuid: tunnel._normalize_tunneling_cfg({"public_url": "https://old-run.trycloudflare.com"}),
    )
    monkeypatch.setattr(tunnel.subprocess, "Popen", lambda *a, **k: FakeProcess())
    monkeypatch.setattr(tunnel.threading, "Thread", lambda *a, **k: SimpleNamespace(start=lambda: None))

    tunnel.start_tunnel(user_uuid=None)

    assert tunnel.runtime_snapshot() == {"running": True, "public_url": ""}


def test_the_address_is_forgotten_when_the_tunnel_stops(monkeypatch):
    tunnel._STATE.update({"running": True, "public_url": "https://quiet-river-sample.trycloudflare.com"})

    tunnel.stop_tunnel(user_uuid=None)

    assert tunnel.runtime_snapshot() == {"running": False, "public_url": ""}
