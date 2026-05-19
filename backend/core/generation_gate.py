from __future__ import annotations

import asyncio
import heapq
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


PRIORITY_MAIN_CHAT = 10
PRIORITY_TELEGRAM_INCOMING = 20
PRIORITY_TELEGRAM_NOTIFICATION = 30
PRIORITY_TELEGRAM_INITIATIVE = 50
PRIORITY_TELEGRAM_AUTONOMOUS = 60


@dataclass(slots=True)
class GenerationTicket:
    ticket_id: int
    run_id: str
    channel: str
    kind: str
    priority: int
    queued_at: float = field(default_factory=time.monotonic)
    queued_at_iso: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[float] = None
    started_at_iso: Optional[str] = None
    initial_position: int = 1
    was_blocked: bool = False
    _cancelled: bool = False


class GenerationGate:
    """Process-local fair gate for central generation pipeline work.

    The backend currently runs main chat and Telegram on different asyncio loops.
    This gate uses a threading condition so both loops share the same active slot.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._queue: list[tuple[int, int, GenerationTicket]] = []
        self._active: Optional[GenerationTicket] = None
        self._next_ticket_id = 0

    def enqueue(
        self,
        *,
        run_id: str,
        channel: str,
        kind: str,
        priority: int,
    ) -> GenerationTicket:
        with self._condition:
            self._next_ticket_id += 1
            ticket = GenerationTicket(
                ticket_id=self._next_ticket_id,
                run_id=str(run_id or f"generation:{self._next_ticket_id}"),
                channel=str(channel or "unknown"),
                kind=str(kind or "generation"),
                priority=int(priority),
            )
            heapq.heappush(self._queue, (ticket.priority, ticket.ticket_id, ticket))
            ticket.initial_position = self._position_locked(ticket.ticket_id)
            ticket.was_blocked = self._active is not None or ticket.initial_position > 1
            self._condition.notify_all()
            return ticket

    async def wait(self, ticket: GenerationTicket) -> GenerationTicket:
        cancel_event = threading.Event()
        try:
            await asyncio.to_thread(self._wait_sync, ticket, cancel_event)
            return ticket
        except asyncio.CancelledError:
            cancel_event.set()
            self.cancel(ticket)
            raise

    def release(self, ticket: GenerationTicket) -> None:
        with self._condition:
            if self._active is not None and self._active.ticket_id == ticket.ticket_id:
                self._active = None
                self._condition.notify_all()

    def cancel(self, ticket: GenerationTicket) -> None:
        with self._condition:
            ticket._cancelled = True
            if self._active is not None and self._active.ticket_id == ticket.ticket_id:
                self._active = None
            self._queue = [
                item for item in self._queue if item[2].ticket_id != ticket.ticket_id
            ]
            heapq.heapify(self._queue)
            self._condition.notify_all()

    def is_busy(self) -> bool:
        with self._condition:
            return self._active is not None

    def queue_size(self) -> int:
        with self._condition:
            return len(self._queue)

    def position(self, ticket: GenerationTicket) -> int:
        with self._condition:
            return self._position_locked(ticket.ticket_id)

    def active_snapshot(self) -> Optional[dict[str, object]]:
        with self._condition:
            if self._active is None:
                return None
            return {
                "run_id": self._active.run_id,
                "channel": self._active.channel,
                "kind": self._active.kind,
                "started_at": self._active.started_at_iso,
            }

    def _wait_sync(self, ticket: GenerationTicket, cancel_event: threading.Event) -> None:
        with self._condition:
            while True:
                if cancel_event.is_set() or ticket._cancelled:
                    self.cancel(ticket)
                    return
                self._discard_cancelled_locked()
                next_ticket = self._queue[0][2] if self._queue else None
                if self._active is None and next_ticket is not None and next_ticket.ticket_id == ticket.ticket_id:
                    heapq.heappop(self._queue)
                    ticket.started_at = time.monotonic()
                    ticket.started_at_iso = datetime.now(timezone.utc).isoformat()
                    self._active = ticket
                    self._condition.notify_all()
                    return
                self._condition.wait(timeout=0.2)

    def _position_locked(self, ticket_id: int) -> int:
        ordered = sorted(self._queue)
        for idx, (_, _, ticket) in enumerate(ordered, start=1):
            if ticket.ticket_id == ticket_id:
                return idx
        return 0

    def _discard_cancelled_locked(self) -> None:
        if not any(item[2]._cancelled for item in self._queue):
            return
        self._queue = [item for item in self._queue if not item[2]._cancelled]
        heapq.heapify(self._queue)


generation_gate = GenerationGate()
