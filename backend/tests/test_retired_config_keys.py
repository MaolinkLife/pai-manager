"""Settings nothing reads any more leave the stored configs.

`decision_layer.capabilities` is retired — what the
router model can do comes from the model index — and the stale value is removed.
"""

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import UserConfig
from modules.database.core import Base
from modules.system import config as config_module


def test_the_retired_key_is_removed_from_stored_configs(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'core.db'}")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(config_module, "SessionLocal", factory)
    with factory() as session:
        session.add_all(
            [
                UserConfig(
                    id="owner-config",
                    user_uuid="owner",
                    config_json=json.dumps(
                        {"decision_layer": {"mode": "llm", "capabilities": {"tool": True}}, "api": {"model": "qwen3:8b"}}
                    ),
                ),
                UserConfig(id="clean-config", user_uuid="guest", config_json=json.dumps({"decision_layer": {"mode": "system"}})),
            ]
        )
        session.commit()

    assert config_module.drop_retired_config_keys() == 1
    assert config_module.drop_retired_config_keys() == 0

    with factory() as session:
        owner = json.loads(session.get(UserConfig, "owner-config").config_json)
        guest = json.loads(session.get(UserConfig, "clean-config").config_json)
    assert owner == {"decision_layer": {"mode": "llm"}, "api": {"model": "qwen3:8b"}}
    assert guest == {"decision_layer": {"mode": "system"}}
    engine.dispose()


def test_a_config_read_never_carries_the_retired_key():
    normalized = config_module.normalize_config_structure({"decision_layer": {"capabilities": {"tool": True}}})

    assert "capabilities" not in normalized["decision_layer"]


def test_the_main_model_image_bypass_and_the_generation_vision_model_are_gone():
    """Images go through the vision module only; the vision model lives in the vision settings."""
    stored = {
        "vision": {"vision_modules": {"ollama_vision": {"model": "qwen3.5:9b", "use_main_model_context": True}}},
        "api": {"model": "qwen3.5:9b", "visual_model": "apple/FastVLM-1.5B", "visual_model_options": ["apple/FastVLM-1.5B"]},
    }

    normalized = config_module.normalize_config_structure(stored)

    assert "use_main_model_context" not in normalized["vision"]["vision_modules"]["ollama_vision"]
    assert normalized["vision"]["vision_modules"]["ollama_vision"]["model"] == "qwen3.5:9b"
    assert "visual_model" not in normalized["api"]
    assert "visual_model_options" not in normalized["api"]
