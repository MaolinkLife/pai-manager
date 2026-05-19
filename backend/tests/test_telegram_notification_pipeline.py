import asyncio
from types import SimpleNamespace

from modules.telegram.service import TelegramBridgeService
from modules.telegram.types import TelegramMessageEnvelope, TelegramNotification


def test_placeholder_image_caption_is_suppressed():
    assert TelegramBridgeService._clean_image_caption("Lim: вот что у меня получилось.") == ""
    assert TelegramBridgeService._clean_image_caption("Generated image ✨") == ""
    assert TelegramBridgeService._clean_image_caption("Смотри, это я вечером.") == "Смотри, это я вечером."


def test_requires_visible_reply_for_incoming_message_event():
    service = TelegramBridgeService()

    assert service._requires_visible_reply({"runtime_meta": {"event": "incoming_message"}}) is True
    assert service._requires_visible_reply({"runtime_meta": {}}) is False


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


def test_deleted_event_without_chat_id_still_requests_history_cleanup(monkeypatch):
    service = TelegramBridgeService()
    captured = {}

    class DummyDatabase:
        def delete_telegram_history_by_message_id(self, **kwargs):
            captured.update(kwargs)
            return 2

    class DummyDeletedEvent:
        deleted_ids = [10, 11]
        chat_id = None

    monkeypatch.setattr(service, "_database_service", lambda: DummyDatabase())
    monkeypatch.setattr(
        "modules.telegram.service.get_active_character_name",
        lambda default=None: "Lim",
    )

    asyncio.run(service._on_telegram_deleted_event(DummyDeletedEvent()))

    assert captured["character_name"] == "Lim"
    assert captured["chat_id"] is None
    assert captured["telegram_message_ids"] == [10, 11]


def test_load_chat_history_deduplicates_by_telegram_message_id(monkeypatch):
    service = TelegramBridgeService()

    rows = [
        {
            "id": "local-1",
            "role": "user",
            "content": "Привет Лим",
            "runtime_meta": {
                "event": "incoming_message",
                "transport": {"name": "telegram", "chat_id": 123, "message_id": 77},
            },
        },
        {
            "id": "local-2",
            "role": "user",
            "content": "Привет Лим",
            "runtime_meta": {
                "event": "incoming_message",
                "transport": {"name": "telegram", "chat_id": 123, "message_id": 77},
            },
        },
    ]

    class DummyDatabase:
        def get_history(self, character_name, limit):
            return list(reversed(rows))

    monkeypatch.setattr(service, "_database_service", lambda: DummyDatabase())
    monkeypatch.setattr(
        "modules.telegram.service.get_active_character_name",
        lambda default=None: "Lim",
    )

    history = service._load_chat_history(chat_id=123, max_messages=24)

    assert len(history) == 1
    assert history[0]["content"] == "Привет Лим"


def test_live_history_sync_removes_messages_missing_from_telegram(monkeypatch):
    service = TelegramBridgeService()
    captured = {}

    class DummyMessage:
        def __init__(self, message_id):
            self.id = message_id

    class DummyClient:
        async def get_messages(self, chat_id, ids):
            assert chat_id == 123
            assert ids == [77, 78]
            return [DummyMessage(78)]

    class DummyDatabase:
        def delete_telegram_history_by_message_id(self, **kwargs):
            captured.update(kwargs)
            return 1

    rows = [
        {
            "id": "local-1",
            "role": "user",
            "runtime_meta": {
                "event": "incoming_message",
                "transport": {"name": "telegram", "chat_id": 123, "message_id": 77},
            },
        },
        {
            "id": "local-2",
            "role": "assistant",
            "runtime_meta": {
                "event": "outgoing_message",
                "transport": {"name": "telegram", "chat_id": 123, "message_id": 78},
            },
        },
    ]

    service._client = DummyClient()
    monkeypatch.setattr(service, "_load_recent_telegram_rows", lambda **kwargs: rows)
    monkeypatch.setattr(service, "_database_service", lambda: DummyDatabase())
    monkeypatch.setattr(
        "modules.telegram.service.get_active_character_name",
        lambda default=None: "Lim",
    )

    deleted = asyncio.run(
        service._sync_recent_chat_history_with_telegram(chat_id=123, max_messages=24)
    )

    assert deleted == 1
    assert captured["character_name"] == "Lim"
    assert captured["chat_id"] == 123
    assert captured["telegram_message_ids"] == [77]


def test_extract_sent_message_ids_handles_single_and_album_messages():
    single = SimpleNamespace(id=101)
    album = [SimpleNamespace(id=102), SimpleNamespace(id="103"), SimpleNamespace(id=None)]

    assert TelegramBridgeService._extract_sent_message_ids(single) == [101]
    assert TelegramBridgeService._extract_sent_message_ids(album) == [102, 103]
    assert TelegramBridgeService._extract_sent_message_ids(None) == []


def test_send_chunks_returns_int_compatible_result_with_message_ids(monkeypatch):
    service = TelegramBridgeService()

    class DummyClient:
        async def send_message(self, **kwargs):
            return SimpleNamespace(id=555)

    async def _noop(*args, **kwargs):
        return None

    async def _private_chat(*args, **kwargs):
        return "private"

    service._client = DummyClient()
    service._rate_limiter = SimpleNamespace(wait_for_slot=_noop)
    monkeypatch.setattr(service, "_resolve_chat_kind_for_chat_id", _private_chat)
    monkeypatch.setattr(service, "_can_write_to_chat", lambda *args, **kwargs: (True, "allowed"))
    monkeypatch.setattr(service, "_log_outbound_target", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_typing_delay", _noop)

    result = asyncio.run(
        service._send_chunks(123, ["hello"], reply_to_message_id=77)
    )

    assert result == 1
    assert int(result) == 1
    assert result.message_ids == [555]
