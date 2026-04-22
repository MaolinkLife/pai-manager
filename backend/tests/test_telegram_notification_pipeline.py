import asyncio

from modules.telegram.service import TelegramBridgeService
from modules.telegram.types import TelegramMessageEnvelope, TelegramNotification


def test_build_notification_from_envelope_routes_public_and_dialog():
    service = TelegramBridgeService()
    service._is_public_reflection_source = lambda envelope: True

    public_envelope = TelegramMessageEnvelope(
        chat_id=100,
        message_id=10,
        chat_kind="channel",
        text="news",
    )
    dialog_envelope = TelegramMessageEnvelope(
        chat_id=200,
        message_id=20,
        chat_kind="private",
        text="hello",
    )

    public_note = service._build_notification_from_envelope(public_envelope)
    dialog_note = service._build_notification_from_envelope(dialog_envelope)

    assert public_note is not None
    assert public_note.kind == "public_post"
    assert dialog_note is not None
    assert dialog_note.kind == "dialog_message"


def test_enqueue_notification_drops_oldest_on_overflow():
    service = TelegramBridgeService()

    async def _run():
        service._notification_queue = asyncio.Queue(maxsize=1)
        first = TelegramNotification(
            kind="dialog_message",
            source_chat_id=1,
            source_message_id=1,
            source_chat_kind="private",
            text="first",
        )
        second = TelegramNotification(
            kind="dialog_message",
            source_chat_id=1,
            source_message_id=2,
            source_chat_kind="private",
            text="second",
        )
        await service._enqueue_notification(first)
        await service._enqueue_notification(second)
        kept = await service._notification_queue.get()
        return kept

    kept = asyncio.run(_run())
    assert kept.source_message_id == 2


def test_process_notification_routes_to_public_reflection():
    service = TelegramBridgeService()
    called = {"public": False, "dialog": False}

    async def _public(notification):
        called["public"] = True

    async def _dialog(envelope):
        called["dialog"] = True

    service._process_public_reflection_notification = _public
    service._process_dialog_message = _dialog

    async def _run():
        await service._process_notification(
            TelegramNotification(
                kind="public_post",
                source_chat_id=1,
                source_message_id=1,
                source_chat_kind="channel",
                text="post",
            )
        )

    asyncio.run(_run())
    assert called["public"] is True
    assert called["dialog"] is False


def test_dialog_runtime_context_is_injected_into_content():
    service = TelegramBridgeService()
    payload = service._inject_runtime_context_into_dialog_content(
        "hello",
        {
            "local_time": "2026-04-19T09:00:00+03:00",
            "day_phase": "morning",
            "is_quiet_hours": False,
            "last_user_message_at": None,
            "last_outbound_at": None,
            "hours_since_last_user_message": None,
            "hours_since_last_outbound": None,
            "unanswered_initiatives_in_row": 1,
            "last_user_message_excerpt": "",
            "last_unanswered_outbound_excerpt": "ping",
            "has_open_conversational_loop": True,
        },
    )

    assert "[TELEGRAM_RUNTIME]" in payload
    assert "Day phase: morning" in payload
    assert "[USER_MESSAGE]" in payload
    assert payload.endswith("hello")


def test_process_notification_handles_system_without_dialog():
    service = TelegramBridgeService()
    called = {"dialog": False}

    async def _dialog(envelope):
        called["dialog"] = True

    service._process_dialog_message = _dialog

    async def _run():
        await service._process_notification(
            TelegramNotification(
                kind="system",
                source_chat_id=1,
                source_message_id=0,
                source_chat_kind="private",
                text="",
            )
        )

    asyncio.run(_run())
    assert called["dialog"] is False


def test_orchestration_semantic_tool_result_stays_tool_message():
    service = TelegramBridgeService()

    message = service._build_model_context_message_for_tool_result(
        tool_name="ask_memory",
        tool_output="[OK]: memory lookup completed.\nKey facts:\n- tea",
    )

    assert message is not None
    assert message["role"] == "tool"
    assert message["name"] == "memory.lookup"


def test_orchestration_chat_lookup_becomes_runtime_context_message():
    service = TelegramBridgeService()

    message = service._build_model_context_message_for_tool_result(
        tool_name="open_chat_by_id",
        tool_output='[OK]: chat opened chat_id=123 title="test"',
    )

    assert message is not None
    assert message["role"] == "system"
    assert "RUNTIME_CONTEXT:runtime.chatContext" in message["content"]


def test_orchestration_send_action_does_not_enter_model_context():
    service = TelegramBridgeService()

    message = service._build_model_context_message_for_tool_result(
        tool_name="send_telegram_message",
        tool_output="[OK]: sent telegram message to chat_id=123.",
    )

    assert message is None


def test_autonomous_inbox_plain_text_reply_is_suppressed(monkeypatch):
    service = TelegramBridgeService()

    async def _fake_generate_reply(user_message):
        from modules.telegram.types import TelegramReply
        return TelegramReply(
            text="Вижу одно непрочитанное, открываю сообщение.",
            reasoning="",
            provider="test",
            raw="planner text",
            images=[],
        )

    monkeypatch.setattr(service, "_generate_reply", _fake_generate_reply)
    monkeypatch.setattr(service, "_attach_actor_for_chat", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_load_chat_history", lambda *args, **kwargs: [])

    ok = asyncio.run(
        service._run_autonomous_inbox_cycle(
            {"chat_id": 123, "chat_kind": "private", "title": "owner", "unread_count": 1},
            candidates=[{"chat_id": 123, "chat_kind": "private", "title": "owner", "unread_count": 1}],
        )
    )

    assert ok is False
