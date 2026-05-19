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


def test_generate_image_normalizes_legacy_provider_model(monkeypatch):
    captured = {}

    def fake_emit_tool_event(**kwargs):
        return "tool-msg-id"

    def fake_generate_image(request):
        captured["provider"] = request.provider
        captured["model"] = request.model
        return ImageGenerationResult(
            provider="diffusers",
            model_id="z_image_turbo",
            image_bytes=b"\x89PNG\r\n\x1a\n",
        )

    monkeypatch.setattr(synthesis_routes.tool_event_bus, "emit_tool_event", fake_emit_tool_event)
    monkeypatch.setattr(synthesis_routes.synthesis_service, "generate_image", fake_generate_image)

    response = synthesis_routes.generate_image(
        {"prompt": "test image", "provider": "z_image_turbo"}
    )

    assert response["status"] == "ok"
    assert captured == {"provider": "diffusers", "model": "z_image_turbo"}


def test_generate_image_emits_error_tool_event_on_provider_error(monkeypatch):
    emitted = []
    audited = []

    def fake_emit_tool_event(**kwargs):
        emitted.append(kwargs)
        return "tool-msg-id"

    def fake_log_audit_entry(*args, **kwargs):
        audited.append({"args": args, "kwargs": kwargs})

    def fake_generate_image(_request):
        raise ImageProviderError("provider down")

    monkeypatch.setattr(synthesis_routes.tool_event_bus, "emit_tool_event", fake_emit_tool_event)
    monkeypatch.setattr(synthesis_routes, "log_audit_entry", fake_log_audit_entry)
    monkeypatch.setattr(synthesis_routes.synthesis_service, "generate_image", fake_generate_image)

    with pytest.raises(HTTPException) as exc_info:
        synthesis_routes.generate_image({"prompt": "test image"})

    assert exc_info.value.status_code == 400
    assert any(event.get("status") == "error" and event.get("tool_name") == "image.generate" for event in emitted)
    assert audited
    assert audited[0]["args"][0] == "synthesis_api_image_generate_error"
    assert emitted[0]["runtime_meta"]["request"]["allow_fallback"] is False
