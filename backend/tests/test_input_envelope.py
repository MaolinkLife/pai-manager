import pytest

from core.input_envelope import InputEnvelope


pytestmark = pytest.mark.regression


def test_input_envelope_normalizes_transport_message():
    envelope = InputEnvelope.from_message(
        {
            "id": "m1",
            "content": "hello",
            "media": [{"name": "image.png", "data": "base64"}],
            "actor_user_uuid": "u1",
            "runtime_meta": {
                "source": "telegram_bridge",
                "transport": {
                    "name": "telegram",
                    "chat_id": 42,
                    "chat_kind": "private",
                    "chat_title": "Maou",
                },
            },
        }
    )

    assert envelope.source == "telegram_bridge"
    assert envelope.text == "hello"
    assert envelope.media[0]["name"] == "image.png"
    assert envelope.user["actor_user_uuid"] == "u1"
    assert envelope.channel == {
        "id": 42,
        "kind": "private",
        "title": "Maou",
        "transport": "telegram_bridge",
    }


def test_input_envelope_round_trips_to_legacy_message():
    envelope = InputEnvelope.from_message(
        {
            "id": "m2",
            "text": "from speech",
            "runtime_meta": {"transport": {"name": "voice"}},
            "history": [{"role": "user", "content": "before"}],
        }
    )

    message = envelope.to_message()

    assert message["id"] == "m2"
    assert message["content"] == "from speech"
    assert message["source"] == "voice"
    assert message["message_type"] == "user_message"
    assert message["history"][0]["content"] == "before"
