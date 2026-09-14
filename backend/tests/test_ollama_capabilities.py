"""What an Ollama model can do comes from Ollama's own metadata.

Models are not run to check what they can do,
and nothing is guessed from the model name. A capability Ollama does not declare
is absent; the owner marks it by hand in the model index.
"""

from modules.ollama import client as ollama_client


def _show(monkeypatch, data=None, error=None):
    def show(model):
        if error:
            return {"status": "error", "model": model, "message": error}
        return {"status": "ok", "model": model, "data": data or {}}

    monkeypatch.setattr(ollama_client, "show_model", show)


def test_capabilities_are_what_ollama_declares(monkeypatch):
    _show(monkeypatch, {"capabilities": ["Completion", "vision", "tools", "thinking"]})

    info = ollama_client.model_capabilities("qwen3-vl:8b")

    assert info["declared"] is True
    assert info["capabilities"] == ["completion", "thinking", "tools", "vision"]
    assert ollama_client.model_supports_vision("qwen3-vl:8b")["supported"] is True


def test_nothing_is_guessed_from_the_name(monkeypatch):
    _show(monkeypatch, {"details": {"families": ["clip"]}, "model_info": {"llava.vision.block_count": 24}})

    info = ollama_client.model_capabilities("llava:latest")
    vision = ollama_client.model_supports_vision("llava:latest")

    assert info["declared"] is False
    assert info["capabilities"] == []
    assert "update Ollama" in info["reason"]
    assert vision["supported"] is False


def test_unavailable_metadata_is_not_a_capability(monkeypatch):
    _show(monkeypatch, error="Ollama not installed, not running or not accessible")

    assert ollama_client.model_capabilities("qwen")["status"] == "error"
    assert ollama_client.model_supports_vision("qwen")["supported"] is False
