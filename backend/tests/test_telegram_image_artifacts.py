import asyncio

from modules.telegram.service import TelegramBridgeService


class _FakeImageResult:
    image_bytes = b"fake-image"
    mime_type = "image/png"
    image_prompt = "night city"
    provider = "diffusers"
    model = "z-image-turbo"
    image_parameters = {"width": 512, "height": 512}


class _FakeMediaPipelineRequest:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeMediaPipeline:
    @staticmethod
    async def run_image(_request):
        return _FakeImageResult()


def test_take_photo_stores_artifact_metadata():
    service = TelegramBridgeService()
    image_artifacts = {}

    async def _fake_describe(image_bytes, *, name):
        return "soft neon room"

    service._describe_image_bytes = _fake_describe
    service._media_pipeline_modules = lambda: (
        _FakeMediaPipelineRequest,
        _FakeMediaPipeline,
    )

    async def _run():
        return await service._tool_take_photo(
            {"photo_desc": "night city", "caption": "caption"},
            image_artifacts,
            {"runtime_meta": {"event": "scheduled_checkin"}},
        )

    result = asyncio.run(_run())
    assert result.startswith("[OK]: image generated.")
    assert len(image_artifacts) == 1
    artifact = next(iter(image_artifacts.values()))
    assert artifact.prompt == "night city"
    assert artifact.description == "soft neon room"
    assert artifact.source_notification_kind == "scheduled_checkin"
    assert artifact.provider == "diffusers"
