"""Блок C — voice call session: flag semantics and orchestration."""

import asyncio

import pytest

from modules.voice import call as call_module
from modules.voice.call_state import call_state, is_call_active


@pytest.fixture(autouse=True)
def _reset_call_state():
    call_state.deactivate()
    yield
    call_state.deactivate()


def test_flag_roundtrip():
    assert not is_call_active()
    call_state.activate(vad_started_by_call=True)
    assert is_call_active()
    assert call_state.snapshot()["active"] is True
    assert call_state.deactivate() is True
    assert not is_call_active()


def test_deactivate_reports_vad_ownership():
    call_state.activate(vad_started_by_call=False)
    assert call_state.deactivate() is False


def test_start_call_spawns_vad_when_idle(monkeypatch):
    started_calls = []

    async def fake_start(force=False):
        started_calls.append(force)
        return True, "ok"

    sent = []

    async def fake_broadcast(active):
        sent.append(active)

    monkeypatch.setattr(call_module, "is_vad_running", lambda: False)
    monkeypatch.setattr(call_module, "start_vad_background", fake_start)
    monkeypatch.setattr(call_module, "_broadcast_call_state", fake_broadcast)

    result = asyncio.run(call_module.start_call())
    assert result["active"] is True
    assert started_calls == [True]  # force=True past the config gates
    assert sent == [True]
    assert is_call_active()


def test_start_call_failure_rolls_back_flag(monkeypatch):
    async def fake_start(force=False):
        return False, "no input device"

    monkeypatch.setattr(call_module, "is_vad_running", lambda: False)
    monkeypatch.setattr(call_module, "start_vad_background", fake_start)

    result = asyncio.run(call_module.start_call())
    assert result["status"] == "error"
    assert not is_call_active()


def test_stop_call_stops_vad_only_when_call_started_it(monkeypatch):
    stopped = []

    async def fake_stop(wait=True):
        stopped.append(wait)
        return True, "ok"

    async def fake_broadcast(active):
        pass

    monkeypatch.setattr(call_module, "stop_vad", fake_stop)
    monkeypatch.setattr(call_module, "force_cut_voice", lambda: None)
    monkeypatch.setattr(call_module, "_broadcast_call_state", fake_broadcast)

    # Case 1: call owns the VAD loop → stop it on hang-up.
    call_state.activate(vad_started_by_call=True)
    result = asyncio.run(call_module.stop_call())
    assert result["active"] is False
    assert stopped == [True]

    # Case 2: background voice mode was already running → leave it alone.
    stopped.clear()
    call_state.activate(vad_started_by_call=False)
    asyncio.run(call_module.stop_call())
    assert stopped == []


def test_trigger_bypass_during_call(monkeypatch):
    from modules.voice.vad_listener import vad_listener

    monkeypatch.setattr(
        "modules.system.config.get_config_value",
        lambda path, default=None: default,
    )
    assert not is_call_active()
    call_state.activate(vad_started_by_call=True)
    assert vad_listener._should_bypass_triggers() is True
