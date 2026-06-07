"""llama.cpp transport layer.

Mirrors the role ``modules.ollama`` plays for the Ollama HTTP API: this package
holds only the protocol-level pieces (HTTP client to ``llama-server``'s OpenAI-
compatible endpoints, model bundle scanning, server process launcher). Domain
adapters that turn these primitives into ``GenerateProvider`` /
``AnalyzerProvider`` / ``VisionProvider`` implementations live in the
respective domain modules under ``modules/<domain>/providers/llama_cpp.py``.
"""
