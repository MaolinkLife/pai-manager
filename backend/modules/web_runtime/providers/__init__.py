from .basic import BasicWebExtractor

EXTRACTOR_PROVIDERS = {
    BasicWebExtractor.name: BasicWebExtractor,
}

__all__ = ["BasicWebExtractor", "EXTRACTOR_PROVIDERS"]
