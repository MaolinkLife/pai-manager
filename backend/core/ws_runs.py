"""The chat runs of one WebSocket connection.

Every message gets its own run. A run is not tied to the socket that started it:
when that socket drops, the run goes on, finishes and is saved, and the events
it still sends go to the same user's newest live socket. Only the stop button,
or a restart without thinking, ends a run early.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ChatRun:
    run_id: str
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: Optional[asyncio.Task] = None
    # True once the run holds the model; before that the message is still waiting.
    started: bool = False
    # What a restart without thinking needs: the prepared prompt and context.
    prepared: Optional[Dict[str, Any]] = None
    # The turn queue row keeping this run's message (modules.generative.turn_queue).
    turn_id: Optional[str] = None


class ConnectionRuns:
    """The runs a connection started, in the order the messages came."""

    def __init__(self) -> None:
        self._runs: Dict[str, ChatRun] = {}

    def add(self, run_id: str) -> ChatRun:
        run = ChatRun(run_id=run_id)
        self._runs[run_id] = run
        return run

    def get(self, run_id: Optional[str]) -> Optional[ChatRun]:
        return self._runs.get(run_id) if run_id else None

    def running(self, run_id: Optional[str] = None) -> Optional[ChatRun]:
        """The run writing a reply now; a message still waiting for the model is not one."""
        for run in self._runs.values():
            if not run.started or run.task is None or run.task.done():
                continue
            if run_id and run.run_id != run_id:
                continue
            return run
        return None

    def finish(self, run_id: str, task: Optional[asyncio.Task]) -> None:
        """Forget a run once its last task is done; a restarted run keeps its entry."""
        run = self._runs.get(run_id)
        if run is not None and run.task is task:
            del self._runs[run_id]


class RunSocket:
    """The socket a chat run talks to.

    It is the socket that started the run until that one fails; then it is the
    same user's newest live socket. Only a user known by the session token is
    reached on another socket: an anonymous guest's run speaks to its own socket
    alone, and nothing ever goes to another user's socket. When no live socket is
    left, sending raises RuntimeError and the run goes on without an audience.
    """

    def __init__(self, websocket: Any, user_uuid: Optional[str], connections: Any) -> None:
        self._socket = websocket
        self._user_uuid = user_uuid or None
        self._connections = connections

    async def send_json(self, payload: Any) -> None:
        await self._send("send_json", payload)

    async def send_text(self, text: str) -> None:
        await self._send("send_text", text)

    async def _send(self, method: str, data: Any) -> None:
        if await self._deliver(self._socket, method, data):
            return
        for socket in self._connections.sockets_for_user(self._user_uuid):
            if socket is self._socket:
                continue
            if await self._deliver(socket, method, data):
                self._socket = socket
                return
        raise RuntimeError("No live socket for this chat run.")

    @staticmethod
    async def _deliver(socket: Any, method: str, data: Any) -> bool:
        try:
            await getattr(socket, method)(data)
            return True
        except Exception:
            # A dead socket fails differently per server; none of it may stop the run.
            return False
