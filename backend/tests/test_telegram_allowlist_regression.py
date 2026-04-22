from modules.telegram.service import TelegramBridgeService
from modules.telegram.types import TelegramMessageEnvelope, TelegramReply
import asyncio


def test_parse_allowed_chat_ids_ignores_non_positive_and_invalid_values():
    parsed = TelegramBridgeService._parse_allowed_chat_ids([0, -1, "", "abc", None, 42, "77"])
    assert parsed == {42, 77}


def test_allow_chat_does_not_block_when_allowlist_contains_only_invalid_values(monkeypatch):
    service = TelegramBridgeService()
    monkeypatch.setattr(
        service,
        "_telegram_cfg",
        lambda: {
            "routing": {
                "allow_private": True,
                "allow_groups": True,
                "allow_channels": True,
                "allowed_chat_ids": [0, "", "bad"],
            },
            "channels": {"read_enabled": True},
        },
    )

    assert service._allow_chat(123456, "private") is True


def test_allow_chat_blocks_when_positive_allowlist_is_set(monkeypatch):
    service = TelegramBridgeService()
    monkeypatch.setattr(
        service,
        "_telegram_cfg",
        lambda: {
            "routing": {
                "allow_private": True,
                "allow_groups": True,
                "allow_channels": True,
                "allowed_chat_ids": [111, 222],
            },
            "channels": {"read_enabled": True},
        },
    )

    assert service._allow_chat(111, "private") is True
    assert service._allow_chat(333, "private") is False


def test_can_write_private_requires_explicit_allowlist(monkeypatch):
    service = TelegramBridgeService()
    monkeypatch.setattr(
        service,
        "_telegram_cfg",
        lambda: {
            "write_policy": {
                "allow_write_private": True,
                "allow_write_groups": False,
                "allow_write_channels": False,
                "allowed_private_chat_ids": [1],
                "denied_chat_ids": [],
            },
            "reflection": {"enabled": True, "target_chat_id": 999},
        },
    )

    can_write_private, reason_private = service._can_write_to_chat(
        TelegramMessageEnvelope(chat_id=1, message_id=1, chat_kind="private", text="hi")
    )
    can_write_private_other, reason_private_other = service._can_write_to_chat(
        TelegramMessageEnvelope(chat_id=2, message_id=1, chat_kind="private", text="hi")
    )
    can_write_reflection_target, reason_reflection_target = service._can_write_to_chat(
        TelegramMessageEnvelope(chat_id=999, message_id=1, chat_kind="private", text="hi")
    )
    can_write_group, reason_group = service._can_write_to_chat(
        TelegramMessageEnvelope(chat_id=2, message_id=1, chat_kind="group", text="hi")
    )
    can_write_channel, reason_channel = service._can_write_to_chat(
        TelegramMessageEnvelope(chat_id=3, message_id=1, chat_kind="channel", text="hi")
    )

    assert can_write_private is True
    assert reason_private == "ok"
    assert can_write_private_other is False
    assert reason_private_other == "private_chat_not_allowlisted"
    assert can_write_reflection_target is True
    assert reason_reflection_target == "ok"
    assert can_write_group is False
    assert reason_group == "write_groups_disabled"
    assert can_write_channel is False
    assert reason_channel == "write_channels_disabled"


def test_can_write_reflection_delivery_allows_only_target(monkeypatch):
    service = TelegramBridgeService()
    monkeypatch.setattr(
        service,
        "_telegram_cfg",
        lambda: {
            "write_policy": {
                "allow_write_private": True,
                "allow_write_groups": False,
                "allow_write_channels": False,
                "allowed_private_chat_ids": [111],
                "denied_chat_ids": [],
            },
            "reflection": {
                "enabled": True,
                "target_chat_id": 777,
                "source_chat_kinds": ["channel", "group"],
                "source_chat_ids": [],
            },
        },
    )

    can_write_target, reason_target = service._can_write_to_chat(
        TelegramMessageEnvelope(chat_id=777, message_id=1, chat_kind="private", text="hi"),
        write_context="reflection_delivery",
    )
    can_write_other, reason_other = service._can_write_to_chat(
        TelegramMessageEnvelope(chat_id=111, message_id=1, chat_kind="private", text="hi"),
        write_context="reflection_delivery",
    )
    can_write_group_target, reason_group_target = service._can_write_to_chat(
        TelegramMessageEnvelope(chat_id=777, message_id=1, chat_kind="group", text="hi"),
        write_context="reflection_delivery",
    )

    assert can_write_target is True
    assert reason_target == "ok"
    assert can_write_other is False
    assert reason_other == "reflection_target_only"
    assert can_write_group_target is False
    assert reason_group_target == "reflection_target_not_private"


def test_public_reflection_source_filtering(monkeypatch):
    service = TelegramBridgeService()
    monkeypatch.setattr(
        service,
        "_telegram_cfg",
        lambda: {
            "reflection": {
                "enabled": True,
                "source_chat_ids": [123],
                "source_chat_kinds": ["channel", "group"],
                "target_chat_id": 777,
            }
        },
    )
    assert service._is_public_reflection_source(
        TelegramMessageEnvelope(chat_id=123, message_id=1, chat_kind="group", text="a")
    )
    assert not service._is_public_reflection_source(
        TelegramMessageEnvelope(chat_id=124, message_id=1, chat_kind="group", text="a")
    )


def test_mark_as_read_uses_client_ack_when_enabled(monkeypatch):
    service = TelegramBridgeService()

    class DummyClient:
        def __init__(self) -> None:
            self.calls = []

        async def send_read_acknowledge(self, *, entity, max_id):
            self.calls.append((entity, max_id))

    client = DummyClient()
    service._client = client
    monkeypatch.setattr(
        service,
        "_telegram_cfg",
        lambda: {
            "channels": {"mark_read_enabled": True},
            "routing": {},
        },
    )

    class DummyEvent:
        id = 42

    envelope = TelegramMessageEnvelope(chat_id=777, message_id=42, chat_kind="private")
    asyncio.run(service._mark_as_read(DummyEvent(), envelope))

    assert client.calls == [(777, 42)]


def test_repeat_fallback_uses_blocked_reply_instead_of_placeholder():
    service = TelegramBridgeService()
    blocked = TelegramReply(
        text="Это нормальный осмысленный ответ, который не должен заменяться заглушкой.",
        reasoning="",
        provider="",
        raw="",
    )
    fallback = service._build_repeat_fallback_reply(
        chat_id=123,
        reason="semantic",
        blocked_reply=blocked,
    )
    assert fallback == blocked.text
    assert "избегаю повторов" not in fallback.lower()


def test_queue_initiative_candidate_deduplicates_chat_id():
    service = TelegramBridgeService()

    service._queue_initiative_candidate(777, "private", idle_minutes=60)
    service._queue_initiative_candidate(777, "private", idle_minutes=120)

    assert len(service._initiative_backlog) == 1
    assert service._initiative_backlog[777] == ("private", 120)


def test_send_initiative_queues_when_generation_is_busy():
    service = TelegramBridgeService()

    async def _run():
        lock = asyncio.Lock()
        await lock.acquire()
        service._generation_session_lock = lock
        ok = await service._send_initiative(999, "private", idle_minutes=30)
        lock.release()
        return ok

    ok = asyncio.run(_run())
    assert ok is False
    assert 999 in service._initiative_backlog


def test_effective_initiative_gap_uses_soft_daily_modifier_not_kill_switch(monkeypatch):
    service = TelegramBridgeService()
    monkeypatch.setattr(
        service,
        "_telegram_cfg",
        lambda: {
            "initiative": {
                "min_gap_minutes": 60,
                "max_proactive_per_day": 3,
            }
        },
    )

    base = service._effective_initiative_gap_minutes(
        {"unanswered_initiatives_in_row": 0, "today_proactive_count": 0}
    )
    soft_slowed = service._effective_initiative_gap_minutes(
        {"unanswered_initiatives_in_row": 2, "today_proactive_count": 5}
    )

    assert base == 60
    assert soft_slowed > base


def test_scheduled_checkin_mark_blocks_duplicate_enqueue():
    service = TelegramBridgeService()
    key = "checkin:2026-04-21:777:morning"

    assert service._can_enqueue_scheduled_mark(key) is True
    service._scheduled_notification_marks[key] = 123.0
    assert service._can_enqueue_scheduled_mark(key) is False
