"""Holds a reference to the main uvicorn asyncio loop.

Background daemon threads (initiative loop, reminders worker) need to push
WebSocket broadcasts through ``core.websocket_manager.manager`` — but those
sockets belong to the uvicorn event loop, so coroutines must be scheduled
with ``run_coroutine_threadsafe`` onto THAT loop, never a thread-local one.
``register_main_loop()`` is called from the FastAPI startup hook.
"""

from __future__ import annotations

import asyncio
from typing import Optional

_main_loop: Optional[asyncio.AbstractEventLoop] = None


def register_main_loop() -> None:
    global _main_loop
    try:
        _main_loop = asyncio.get_running_loop()
    except RuntimeError:
        _main_loop = None


def get_main_loop() -> Optional[asyncio.AbstractEventLoop]:
    if _main_loop is not None and _main_loop.is_closed():
        return None
    return _main_loop
