from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


SubjectMode = Literal[
    "self",
    "self_plus_environment",
    "environment_only",
    "symbolic_mood",
    "object_focus",
]

DistanceMode = Literal[
    "extreme_closeup",
    "close_selfie",
    "portrait",
    "upper_body",
    "medium_shot",
]


class VisualProfile(BaseModel):
    character_name: str = "PAI"
    appearance_textarea: Optional[str] = None
    default_outfit: Optional[str] = None
    default_environment: Optional[str] = None
    style_preset: str = "anime"
    render_profile: str = "default_anime"
    selfie_bias: float = 0.85
    environment_bias: float = 0.10
    symbolic_bias: float = 0.05
    anti_repetition_strength: float = 0.65
    use_time_of_day: bool = True
    use_season: bool = True
    use_weather: bool = True
    use_relation_state: bool = True
    use_recent_topics: bool = True
    selfie_composition_base: Optional[str] = None
    selfie_composition_pool_override: Optional[str] = None
    environment_composition_pool_override: Optional[str] = None
    allow_self_images: bool = True
    allow_environment_images: bool = True
    allow_symbolic_images: bool = True


class VisualIntentInput(BaseModel):
    emotion_state: Dict[str, Any] = Field(default_factory=dict)
    relation_state: Dict[str, Any] = Field(default_factory=dict)
    recent_context: Dict[str, Any] = Field(default_factory=dict)
    world_state: Dict[str, Any] = Field(default_factory=dict)
    self_expression_context: Dict[str, Any] = Field(default_factory=dict)
    visual_profile: VisualProfile = Field(default_factory=VisualProfile)


class VisualIntentPlan(BaseModel):
    visual_intent: str
    should_generate: bool = True
    subject_mode: SubjectMode
    distance: DistanceMode
    tone: List[str] = Field(default_factory=list)
    setting: str
    lighting: List[str] = Field(default_factory=list)
    composition_pool_id: str = ""
    composition_prompt: str = ""
    expression: Dict[str, Any] = Field(default_factory=dict)
    composition: Dict[str, Any] = Field(default_factory=dict)
    purpose: str
    style_modifiers: Optional[Dict[str, Any]] = None
    generator_mode: str
    confidence: float
    reasoning_summary: str
    generated_appearance: Optional[str] = None
