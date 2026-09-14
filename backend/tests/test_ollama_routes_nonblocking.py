import asyncio
import time

import pytest

from routes import ollama_routes


pytestmark = pytest.mark.regression

SLOW_CLIENT_SEC = 0.3


def _slow(result):
    def call(*args, **kwargs):
        time.sleep(SLOW_CLIENT_SEC)
        return result

    return call


async def _order_of(route_call):
    """Run a route next to a short coroutine; a blocking route would finish first."""
    order = []

    async def route():
        await route_call()
        order.append("route")

    async def other_request():
        await asyncio.sleep(0.01)
        order.append("other")

    await asyncio.gather(route(), other_request())
    return order


@pytest.mark.parametrize(
    "client_name, route_call",
    [
        ("list_models", lambda: ollama_routes.get_available_models()),
        ("list_runtime_models", lambda: ollama_routes.get_runtime_models()),
        ("release_model", lambda: ollama_routes.unload_runtime_model({"model": "qwen"})),
        ("delete_model", lambda: ollama_routes.delete_model({"model": "qwen"})),
    ],
)
def test_ollama_routes_leave_the_event_loop_free(monkeypatch, client_name, route_call):
    monkeypatch.setattr(ollama_routes.ollama_client, client_name, _slow({"status": "ok", "models": []}))

    assert asyncio.run(_order_of(route_call)) == ["other", "route"]
