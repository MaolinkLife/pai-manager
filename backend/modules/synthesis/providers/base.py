from __future__ import annotations

from modules.synthesis.types import ImageGenerationRequest, ImageGenerationResult


class ImageProviderError(RuntimeError):
    pass


class ImageProvider:
    name = "base"

    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        raise NotImplementedError

