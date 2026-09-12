import time as real_time
from types import SimpleNamespace

import pytest
import requests

from modules.ollama import client as ollama_client


pytestmark = pytest.mark.regression


class _FakeTime:
    """Real `time`, except for a monotonic clock the test moves by hand."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def __getattr__(self, name):
        return getattr(real_time, name)


@pytest.fixture
def clock(monkeypatch):
    fake = _FakeTime()
    monkeypatch.setattr(ollama_client, "time", fake)
    monkeypatch.setattr(ollama_client, "_unavailable_until", 0.0)
    return fake


@pytest.fixture
def ollama(monkeypatch):
    state = SimpleNamespace(up=False, probes=0)

    def fake_get(url, timeout=None):
        state.probes += 1
        if not state.up:
            raise requests.ConnectionError("connection refused")
        return SimpleNamespace(status_code=200, json=lambda: {"models": [{"name": "qwen"}]}, raise_for_status=lambda: None)

    monkeypatch.setattr(ollama_client.requests, "get", fake_get)
    return state


def test_unreachable_ollama_is_not_probed_again_within_the_ttl(clock, ollama):
    assert ollama_client.is_available() is False
    clock.now += ollama_client.OLLAMA_UNAVAILABLE_TTL_SEC - 1

    assert ollama_client.is_available() is False
    assert ollama.probes == 1


def test_ollama_is_probed_again_once_the_ttl_has_passed(clock, ollama):
    ollama_client.is_available()
    ollama.up = True
    clock.now += ollama_client.OLLAMA_UNAVAILABLE_TTL_SEC + 1

    assert ollama_client.is_available() is True
    assert ollama.probes == 2


def test_a_reachable_ollama_is_probed_every_time(clock, ollama):
    ollama.up = True

    assert ollama_client.is_available() is True
    assert ollama_client.is_available() is True
    assert ollama.probes == 2


def test_listing_models_answers_at_once_while_ollama_is_known_down(clock, ollama):
    ollama_client.is_available()

    result = ollama_client.list_models()

    assert result["status"] == "error"
    assert ollama.probes == 1


def test_api_address_avoids_localhost():
    assert ollama_client.OLLAMA_API_URL.startswith("http://127.0.0.1:")
