from __future__ import annotations

from modules.ollama import client as ollama_client


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, reason: str = "OK") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.reason = reason

    def json(self) -> dict:
        return dict(self._payload)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_chat_with_tools_forces_plain_after_tool_round(monkeypatch):
    captured_payloads: list[dict] = []

    def _fake_post(url: str, *, payload: dict, timeout: int, retries: int = 2, retry_backoff_sec: float = 0.6):
        captured_payloads.append(dict(payload))
        return _FakeResponse(
            200,
            {"message": {"role": "assistant", "content": "ok"}},
        )

    monkeypatch.setattr(ollama_client, "_post_json_with_retries", _fake_post)

    result = ollama_client.chat_with_tools(
        messages=[
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "open_chat_by_id", "arguments": "{}"}}],
            },
            {"role": "tool", "name": "open_chat_by_id", "content": "[OK]"},
        ],
        options={"temperature": 0.7},
        model="test-model",
        tools=[{"type": "function", "function": {"name": "send_telegram_message"}}],
        tool_choice="auto",
    )

    assert result["message"]["content"] == "ok"
    assert len(captured_payloads) == 1
    assert "tools" not in captured_payloads[0]
    assert "tool_choice" not in captured_payloads[0]


def test_chat_with_tools_degrades_once_after_400(monkeypatch):
    captured_payloads: list[dict] = []

    def _fake_post(url: str, *, payload: dict, timeout: int, retries: int = 2, retry_backoff_sec: float = 0.6):
        captured_payloads.append(dict(payload))
        if len(captured_payloads) == 1:
            return _FakeResponse(400, {"error": "bad tool schema"}, reason="Bad Request")
        return _FakeResponse(
            200,
            {"message": {"role": "assistant", "content": "degraded ok"}},
        )

    monkeypatch.setattr(ollama_client, "_post_json_with_retries", _fake_post)

    result = ollama_client.chat_with_tools(
        messages=[{"role": "user", "content": "hi"}],
        options={"temperature": 0.7},
        model="test-model",
        tools=[{"type": "function", "function": {"name": "send_telegram_message"}}],
        tool_choice="auto",
    )

    assert result["message"]["content"] == "degraded ok"
    assert len(captured_payloads) == 2
    assert "tools" in captured_payloads[0]
    assert captured_payloads[0]["tool_choice"] == "auto"
    assert "tools" not in captured_payloads[1]
    assert "tool_choice" not in captured_payloads[1]
