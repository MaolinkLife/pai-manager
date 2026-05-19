import asyncio

import pytest

from modules.generative.types import GenerateRequest, GenerateResult
from modules.telegram.service import TelegramBridgeService


pytestmark = pytest.mark.regression


def test_telegram_generation_uses_sync_generate_instead_of_stream():
    service = TelegramBridgeService()
    request = GenerateRequest(
        messages=[{"role": "user", "content": "hello"}],
        options={"streaming": True},
        metadata={"mode": "telegram_bridge"},
    )

    class DummyGenerationManager:
        generate_called = False
        stream_called = False

        def generate(self, received_request):
            self.generate_called = True
            assert received_request is request
            return GenerateResult(provider="test", content="sync reply")

        async def stream(self, received_request):
            self.stream_called = True
            raise AssertionError("Telegram bridge must not use streaming generation")
            yield

    manager = DummyGenerationManager()

    result = asyncio.run(
        service._run_generation_with_typing(
            generation_manager=manager,
            request=request,
            chat_id=123,
            chat_kind="channel",
        )
    )

    assert manager.generate_called is True
    assert manager.stream_called is False
    assert result.content == "sync reply"
