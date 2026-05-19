from modules.synthesis.media_pipeline import MediaPipelineRequest, _apply_image_scenario


def test_image_scenario_applies_soft_text_defaults(monkeypatch):
    monkeypatch.setattr(
        "modules.synthesis.media_pipeline.config_service.get_config_value",
        lambda key, default=None: {
            "scenarios": {
                "sandbox": {
                    "enabled": True,
                    "style_prompt": "clean cinematic anime style",
                    "prompt_policy": "avoid hidden body-part requirements",
                }
            }
        }
        if key == "synthesis.prompting"
        else default,
    )

    request, scenario_key, scenario = _apply_image_scenario(
        MediaPipelineRequest(mode="sandbox_forced", prompt="test", source="sandbox_image_pipeline")
    )

    assert scenario_key == "sandbox"
    assert scenario
    assert request.style_prompt == "clean cinematic anime style"
    assert request.prompt_policy == "avoid hidden body-part requirements"
    assert request.image_provider == "diffusers"


def test_image_scenario_controls_telegram_when_allowed(monkeypatch):
    monkeypatch.setattr(
        "modules.synthesis.media_pipeline.config_service.get_config_value",
        lambda key, default=None: {
            "scenarios": {
                "telegram_command": {
                    "enabled": True,
                    "image_provider": "core",
                    "image_model": "z_image_turbo",
                    "use_prompt_builder": True,
                    "review_generated_image": True,
                    "use_visual_intent": True,
                    "width": 768,
                    "height": 1024,
                    "steps": 12,
                    "cfg": 0.0,
                }
            }
        }
        if key == "synthesis.prompting"
        else default,
    )

    request, _, _ = _apply_image_scenario(
        MediaPipelineRequest(
            mode="sandbox_forced",
            prompt="test",
            scenario_key="telegram_command",
            image_provider="auto",
            width=512,
            height=512,
            num_inference_steps=4,
            guidance_scale=7.0,
            metadata={"allow_scenario_controls": True},
        )
    )

    assert request.image_provider == "core"
    assert request.image_model == "z_image_turbo"
    assert request.review_generated_image is True
    assert request.use_visual_intent is True
    assert request.width == 768
    assert request.height == 1024
    assert request.num_inference_steps == 12
    assert request.guidance_scale == 0.0
