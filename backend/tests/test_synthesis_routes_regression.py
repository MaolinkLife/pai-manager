import pytest
from fastapi import HTTPException

from modules.synthesis.providers.base import ImageProviderError
from modules.synthesis.types import ImageGenerationResult
from routes import synthesis_routes


pytestmark = pytest.mark.regression


def test_generate_image_emits_ok_tool_event(monkeypatch):
    emitted = []

    def fake_emit_tool_event(**kwargs):
        emitted.append(kwargs)
        return "tool-msg-id"

    def fake_generate_image(_request):
        return ImageGenerationResult(
            provider="z_image_turbo",
            model_id="z-image-turbo",
            image_bytes=b"\x89PNG\r\n\x1a\n",
            mime_type="image/png",
            width=1024,
            height=1024,
            seed=7,
        )

    monkeypatch.setattr(synthesis_routes.tool_event_bus, "emit_tool_event", fake_emit_tool_event)
    monkeypatch.setattr(synthesis_routes.synthesis_service, "generate_image", fake_generate_image)

    payload = {"prompt": "test image", "aspect_ratio": "1:1"}
    response = synthesis_routes.generate_image(payload)

    assert response["status"] == "ok"
    assert any(event.get("status") == "ok" and event.get("tool_name") == "image.generate" for event in emitted)


def test_generate_image_emits_error_tool_event_on_provider_error(monkeypatch):
    emitted = []

    def fake_emit_tool_event(**kwargs):
        emitted.append(kwargs)
        return "tool-msg-id"

    def fake_generate_image(_request):
        raise ImageProviderError("provider down")

    monkeypatch.setattr(synthesis_routes.tool_event_bus, "emit_tool_event", fake_emit_tool_event)
    monkeypatch.setattr(synthesis_routes.synthesis_service, "generate_image", fake_generate_image)

    with pytest.raises(HTTPException) as exc_info:
        synthesis_routes.generate_image({"prompt": "test image"})

    assert exc_info.value.status_code == 400
    assert any(event.get("status") == "error" and event.get("tool_name") == "image.generate" for event in emitted)
