"""The router model gets the routing tool only when the model index says it can use tools.

What a model can do comes from the model index; the
Core tab's own capability ticks are gone.
"""

import asyncio

from core import decision_layer as dl_module
from core.decision_layer import DecisionLayer
from modules.model_index import service as model_index


def _route(monkeypatch, capabilities):
    settings = {
        "decision_layer.active_provider": "ollama",
        "decision_layer.providers.ollama": {"model": "router:8b"},
    }
    monkeypatch.setattr(dl_module.config_service, "get_config_value", lambda path, default=None: settings.get(path, default))
    monkeypatch.setattr(dl_module, "should_release_resources", lambda name: False)
    monkeypatch.setattr(dl_module, "log_audit_entry", lambda *args, **kwargs: None)

    asked = []
    monkeypatch.setattr(
        model_index,
        "capabilities_of",
        lambda provider, name: asked.append((provider, name)) or capabilities,
    )
    calls = []

    def chat_with_tools(messages, options, model, tools=None, tool_choice=None):
        calls.append({"model": model, "tools": tools, "tool_choice": tool_choice})
        return {"message": {"content": ""}}

    monkeypatch.setattr(dl_module.ollama_client, "chat_with_tools", chat_with_tools)

    layer = DecisionLayer.__new__(DecisionLayer)
    asyncio.run(layer._make_llm_decisions({}, {"content": "привет"}))
    return asked, calls


def test_a_model_with_tools_gets_the_routing_tool(monkeypatch):
    asked, calls = _route(monkeypatch, ["completion", "tools"])

    assert asked == [("ollama", "router:8b")]
    assert calls[0]["model"] == "router:8b"
    assert calls[0]["tools"] and calls[0]["tools"][0]["function"]["name"] == "decide_route"
    assert calls[0]["tool_choice"] == {"type": "function", "function": {"name": "decide_route"}}


def test_a_model_without_tools_is_asked_without_the_tool(monkeypatch):
    _asked, calls = _route(monkeypatch, ["completion", "thinking"])

    assert calls[0]["tools"] is None
    assert calls[0]["tool_choice"] is None


def test_a_model_the_index_does_not_know_is_asked_without_the_tool(monkeypatch):
    _asked, calls = _route(monkeypatch, None)

    assert calls[0]["tools"] is None
