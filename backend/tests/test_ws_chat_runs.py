"""Chat runs over the WebSocket: a message is never refused and a reply never dies with its socket.

Every message gets its own run. Runs of one connection wait for the model in
order; the stop button stops only the reply being written. When the socket
drops, the run goes on and is saved, and what it still has to say goes to the
same user's new socket — never to another user's, and not at all for an
anonymous guest.

The pipeline around the model is replaced: a scripted reply waits for the test
to release it, so every step is deterministic. Sockets of known users open with
a one-time pass, as the page does.
"""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import ws_tickets
from core.generation_gate import GenerationGate
from core.interaction import InteractionPolicy
from core.websocket_manager import ConnectionManager
from core.ws_tickets import WsTicketStore
from routes import ws_routes

pytestmark = pytest.mark.regression

GUEST = "/api/ws"


class Script:
    """What the scripted model did, and the switches that let each reply finish."""

    def __init__(self):
        self.lock = threading.Lock()
        self.started: list[str] = []
        self.finished: list[str] = []
        self.stopped: list[str] = []
        self.skip_restarts: list[str] = []
        self._release: dict[str, threading.Event] = {}
        self._all_released = False

    def gate(self, run_id: str) -> threading.Event:
        with self.lock:
            event = self._release.setdefault(run_id, threading.Event())
            if self._all_released:
                event.set()
            return event

    def release_all(self) -> None:
        with self.lock:
            self._all_released = True
            for event in self._release.values():
                event.set()

    def note(self, bucket: list[str], run_id: str) -> None:
        with self.lock:
            bucket.append(run_id)


class Reader:
    """Collects everything a test socket receives, without blocking the test."""

    def __init__(self, session):
        self.events: list[dict] = []
        threading.Thread(target=self._read, args=(session,), daemon=True).start()

    def _read(self, session) -> None:
        try:
            while True:
                self.events.append(session.receive_json())
        except Exception:
            return

    def has(self, run_id: str, event_type: str) -> bool:
        return any(e.get("run_id") == run_id and e.get("type") == event_type for e in list(self.events))

    def errors(self) -> list[dict]:
        return [e for e in list(self.events) if e.get("type") == "error"]


def wait_until(check, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return check()


def send(session, run_id: str, content: str = "hi") -> None:
    session.send_json(
        {
            "action": "send_message",
            "payload": {"id": f"temp-{run_id}", "role": "user", "content": content, "run_id": run_id},
        }
    )


@pytest.fixture
def chat(monkeypatch):
    script = Script()
    gate = GenerationGate()
    tickets = WsTicketStore()
    saved_meta: list[str] = []

    monkeypatch.setattr(ws_routes, "manager", ConnectionManager())
    monkeypatch.setattr(ws_routes, "generation_gate", gate)
    monkeypatch.setattr(ws_tickets, "store", tickets)

    async def accept(websocket):
        return True

    monkeypatch.setattr(ws_routes.access_guard, "accept_ws", accept)

    def policy(user_uuid):
        role = "owner" if user_uuid == "owner-uuid" else ("user" if user_uuid else "anonymous")
        return InteractionPolicy(
            actor_role=role,
            can_affect_moral=role == "owner",
            can_affect_global_memory=role == "owner",
        )

    monkeypatch.setattr(ws_routes, "resolve_interaction_policy", policy)
    monkeypatch.setattr(ws_routes, "can_accept_ingress", lambda channel: (True, ""))
    monkeypatch.setattr(ws_routes, "_apply_chat_context_flags", lambda payload: payload)
    monkeypatch.setattr(ws_routes, "activate_user_context", lambda user_uuid: None)
    monkeypatch.setattr(ws_routes, "reset_user_context", lambda token: None)
    monkeypatch.setattr(ws_routes, "log_audit_entry", lambda *args, **kwargs: None)
    monkeypatch.setattr(ws_routes.tool_event_bus, "emit_tool_event", lambda **kwargs: None)
    monkeypatch.setattr(
        ws_routes.database_service,
        "update_history_runtime_meta",
        lambda message_id, meta, merge=False: saved_meta.append(message_id),
    )

    async def process_message(payload, websocket, trace_hook=None):
        return {
            "decisions": {},
            "memory_context": {},
            "system_prompt": "base",
            "user_message": {"id": payload.get("id"), "content": payload.get("content")},
        }

    monkeypatch.setattr(ws_routes.decision_layer, "process_message", process_message)

    from core import instructor as instructor_module

    async def format_for_api(self, *args, **kwargs):
        return []

    monkeypatch.setattr(instructor_module.Instructor, "format_for_api", format_for_api)

    async def generate_stream(processing_result, formatted_history, *, emit_fn, run_id, should_stop, **kwargs):
        script.note(script.started, run_id)
        if kwargs.get("skip_thinking_attempted"):
            script.note(script.skip_restarts, run_id)
        release = script.gate(run_id)
        try:
            await emit_fn({"type": "message_chunk", "run_id": run_id, "content": "part"})
            while not release.is_set():
                if should_stop():
                    script.note(script.stopped, run_id)
                    return
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            script.note(script.stopped, run_id)
            raise
        await emit_fn({"type": "message_end", "id": f"reply-{run_id}", "run_id": run_id})
        script.note(script.finished, run_id)

    monkeypatch.setattr(ws_routes.conversation, "generate_stream", generate_stream)

    app = FastAPI()
    app.include_router(ws_routes.ws_router)
    with TestClient(app) as client:
        try:
            yield SimpleNamespace(
                client=client,
                script=script,
                saved_meta=saved_meta,
                url=lambda user_uuid: f"/api/ws?ticket={tickets.issue(user_uuid)}",
            )
        finally:
            script.release_all()
            wait_until(lambda: not gate.is_busy() and gate.queue_size() == 0)


def test_a_reply_is_finished_and_saved_after_the_socket_drops(chat):
    with chat.client.websocket_connect(chat.url("owner-uuid")) as socket:
        send(socket, "m1")
        assert wait_until(lambda: "m1" in chat.script.started)

    chat.script.gate("m1").set()

    assert wait_until(lambda: "m1" in chat.script.finished)
    assert wait_until(lambda: "reply-m1" in chat.saved_meta)


def test_the_rest_of_a_reply_reaches_only_the_same_users_new_socket(chat):
    with chat.client.websocket_connect(chat.url("other-uuid")) as stranger, chat.client.websocket_connect(GUEST) as guest:
        stranger_reader, guest_reader = Reader(stranger), Reader(guest)
        with chat.client.websocket_connect(chat.url("owner-uuid")) as first:
            send(first, "m1")
            assert wait_until(lambda: "m1" in chat.script.started)

        with chat.client.websocket_connect(chat.url("owner-uuid")) as second:
            reader = Reader(second)
            chat.script.gate("m1").set()
            assert wait_until(lambda: reader.has("m1", "message_end"))

        time.sleep(0.3)
        assert stranger_reader.events == []
        assert guest_reader.events == []


def test_an_anonymous_guests_reply_is_not_forwarded_to_another_socket(chat):
    with chat.client.websocket_connect(GUEST) as first:
        send(first, "g1")
        assert wait_until(lambda: "g1" in chat.script.started)

    with chat.client.websocket_connect(GUEST) as second:
        reader = Reader(second)
        chat.script.gate("g1").set()
        assert wait_until(lambda: "g1" in chat.script.finished)
        time.sleep(0.3)
        assert reader.events == []


def test_a_second_message_waits_for_the_first_instead_of_failing(chat):
    with chat.client.websocket_connect(chat.url("owner-uuid")) as socket:
        reader = Reader(socket)
        send(socket, "m1")
        assert wait_until(lambda: "m1" in chat.script.started)

        send(socket, "m2")
        time.sleep(0.3)
        assert "m2" not in chat.script.started
        assert reader.errors() == []

        chat.script.gate("m1").set()
        assert wait_until(lambda: "m2" in chat.script.started)
        chat.script.gate("m2").set()
        assert wait_until(lambda: reader.has("m2", "message_end"))

    assert chat.script.finished == ["m1", "m2"]


def test_stop_stops_only_the_reply_being_written(chat):
    with chat.client.websocket_connect(chat.url("owner-uuid")) as socket:
        send(socket, "m1")
        assert wait_until(lambda: "m1" in chat.script.started)
        send(socket, "m2")

        socket.send_json({"action": "stop_generation", "payload": {"run_id": "m1"}})

        assert wait_until(lambda: "m1" in chat.script.stopped)
        assert wait_until(lambda: "m2" in chat.script.started)
        chat.script.gate("m2").set()
        assert wait_until(lambda: "m2" in chat.script.finished)

    assert "m1" not in chat.script.finished


def test_stop_does_not_drop_a_message_that_is_still_waiting(chat):
    with chat.client.websocket_connect(chat.url("owner-uuid")) as socket:
        send(socket, "m1")
        assert wait_until(lambda: "m1" in chat.script.started)
        send(socket, "m2")
        time.sleep(0.2)

        socket.send_json({"action": "stop_generation", "payload": {"run_id": "m2"}})
        time.sleep(0.2)
        chat.script.gate("m1").set()

        assert wait_until(lambda: "m2" in chat.script.started)
        chat.script.gate("m2").set()
        assert wait_until(lambda: "m2" in chat.script.finished)

    assert "m1" in chat.script.finished
    assert "m2" not in chat.script.stopped


def test_skipping_the_thinking_restarts_the_reply_before_the_next_message(chat):
    with chat.client.websocket_connect(chat.url("owner-uuid")) as socket:
        send(socket, "m1")
        assert wait_until(lambda: "m1" in chat.script.started)
        send(socket, "m2")
        time.sleep(0.2)

        socket.send_json({"action": "skip_thinking", "payload": {"run_id": "m1"}})

        assert wait_until(lambda: "m1" in chat.script.skip_restarts)
        assert "m2" not in chat.script.started
        chat.script.gate("m1").set()
        assert wait_until(lambda: "m1" in chat.script.finished)
        assert wait_until(lambda: "m2" in chat.script.started)
        chat.script.gate("m2").set()
        assert wait_until(lambda: "m2" in chat.script.finished)

    assert chat.script.finished == ["m1", "m2"]
