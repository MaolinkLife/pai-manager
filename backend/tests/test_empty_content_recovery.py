import asyncio
from types import SimpleNamespace

from modules.generative.conversation import _build_empty_content_recovery_messages
from modules.telegram.service import TelegramBridgeService


def test_empty_content_recovery_messages_include_previous_thinking_as_tool():
    messages = _build_empty_content_recovery_messages(
        [{"role": "system", "content": "persona"}, {"role": "user", "content": "hello"}],
        recovery_instruction="Return final answer.",
        previous_reasoning="Thinking Process: planned answer",
    )

    assert messages[-2]["role"] == "tool"
    assert messages[-2]["name"] == "thinking"
    assert "Thinking Process: planned answer" in messages[-2]["content"]
    assert messages[-1] == {"role": "user", "content": "Return final answer."}


def test_telegram_empty_content_recovery_sends_thinking_tool_and_disables_think(monkeypatch):
    service = TelegramBridgeService()
    captured = {}

    class DummyGenerateRequest:
        def __init__(self, *, messages, options, metadata):
            self.messages = messages
            self.options = options
            self.metadata = metadata

    class DummyManager:
        pass

    async def _fake_run_generation_with_typing(**kwargs):
        request = kwargs["request"]
        captured["messages"] = request.messages
        captured["options"] = request.options
        captured["metadata"] = request.metadata
        return SimpleNamespace(
            provider="test",
            content="Готовый ответ.",
            reasoning="",
        )

    monkeypatch.setattr(service, "_run_generation_with_typing", _fake_run_generation_with_typing)

    async def _run():
        return await service._recover_empty_visible_reply_with_retries(
            formatted_history=[{"role": "system", "content": "persona"}],
            generation_options={"num_predict": 2048},
            generation_manager=DummyManager(),
            GenerateRequest=DummyGenerateRequest,
            conversation_utils=SimpleNamespace(split_reasoning=lambda raw: (raw, "")),
            base_result=SimpleNamespace(reasoning="Thinking Process: telegram draft"),
            typing_chat_id=123,
            typing_chat_kind="private",
        )

    reply = asyncio.run(_run())

    assert reply is not None
    assert reply.text == "Готовый ответ."
    assert captured["options"]["__think"] is False
    assert captured["metadata"]["mode"] == "telegram_bridge_empty_content_recovery"
    assert captured["messages"][-2]["role"] == "tool"
    assert captured["messages"][-2]["name"] == "thinking"
    assert "Thinking Process: telegram draft" in captured["messages"][-2]["content"]


def test_telegram_generation_options_disable_ollama_thinking(monkeypatch):
    service = TelegramBridgeService()

    monkeypatch.setattr(
        "modules.telegram.service.config_service.get_config_value",
        lambda key, default=None: {
            "temperature": 0.95,
            "num_predict": 4096,
            "normalize_messages": True,
            "name": "Default",
        }
        if key == "generate_settings"
        else default,
    )

    options = service._build_generation_options()

    assert options["num_predict"] == 4096
    assert options["normalize_messages"] is True
    assert options["__think"] is False
    assert "name" not in options
