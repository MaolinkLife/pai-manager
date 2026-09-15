"""One-time passes for opening the chat WebSocket.

A browser cannot put the Authorization header on a WebSocket, and a token in
the socket's address ends up in every log that prints addresses. So the page
asks for a pass over HTTP, where the token travels in the header, and opens the
socket with the pass. A pass works once, lives a few seconds and names one user,
so a pass that lands in a log is already worthless.

Passes live in the memory of the backend process: after a restart the page
simply asks for a new one.
"""

from __future__ import annotations

import secrets
import threading
import time
from typing import Callable, Dict, Optional, Tuple

TICKET_TTL_SECONDS = 30
# The socket closes with this code when its pass is missing, used, expired or
# replaced by a token in the address; the page then asks for a new pass.
WS_CLOSE_PASS_REFUSED = 4401


class WsTicketStore:
    def __init__(self, ttl_seconds: int = TICKET_TTL_SECONDS, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._tickets: Dict[str, Tuple[str, float]] = {}

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    def issue(self, user_uuid: str) -> str:
        ticket = secrets.token_urlsafe(32)
        with self._lock:
            self._forget_expired_locked()
            self._tickets[ticket] = (user_uuid, self._clock() + self._ttl_seconds)
        return ticket

    def redeem(self, ticket: Optional[str]) -> Optional[str]:
        """The user a pass names, once; None for an unknown, used or expired pass."""
        if not ticket:
            return None
        with self._lock:
            entry = self._tickets.pop(ticket, None)
        if entry is None:
            return None
        user_uuid, expires_at = entry
        if self._clock() > expires_at:
            return None
        return user_uuid

    def _forget_expired_locked(self) -> None:
        now = self._clock()
        for ticket in [key for key, (_, expires_at) in self._tickets.items() if now > expires_at]:
            del self._tickets[ticket]


store = WsTicketStore()
