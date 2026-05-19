"""Analyzer module orchestrating cognitive analysis providers."""

from __future__ import annotations

from typing import Any, Dict

from modules.system.logger import AuditStatus, log_audit_entry

from .providers.manager import AnalyzerProviderManager

AnalyzerOutput = Dict[str, Any]


class AnalyzerModule:
    """High-level orchestrator for cognitive analysis."""

    def __init__(self) -> None:
        self.provider_manager = AnalyzerProviderManager()
        self._default_provider_name = "default"

    async def analyze(self, input_raw: Dict[str, Any]) -> AnalyzerOutput:
        content = (input_raw.get("content") or "").strip()
        message_meta = self._build_message_meta(input_raw)

        log_audit_entry(
            "analyzer_request_start",
            "[Analyzer] Получен запрос на анализ.",
            AuditStatus.INFO,
            details={
                "message_id": message_meta.get("message_id"),
                "media_count": message_meta.get("media_count"),
                "has_content": bool(content),
            },
        )
        print(
            "[Analyzer] Запуск анализа:",
            f"id={message_meta.get('message_id')} length={len(content)}",
        )

        if not content:
            log_audit_entry(
                "analyzer_empty_content",
                "[Analyzer] Пустой ввод. Возвращаю дефолтный анализ.",
                AuditStatus.WARNING,
                details={"message_meta": message_meta},
            )
            return self._wrap_default(content, reason="empty_input", meta=message_meta)

        result, provider_name, errors = await self.provider_manager.analyze(
            content, message_meta
        )
        provider_name = provider_name or self._default_provider_name

        if result:
            result = self._normalize_metadata(result, content, message_meta)
            log_audit_entry(
                "analyzer_result_success",
                "[Analyzer] Анализ выполнен успешно.",
                AuditStatus.SUCCESS,
                details={
                    "provider": provider_name,
                    "errors": errors,
                    "message_id": message_meta.get("message_id"),
                    "dominant_tone": result.get("input_analysis", {})
                    .get("emotional_tone", {})
                    .get("primary"),
                    "metadata": result,
                },
            )
            print(
                "[Analyzer] Успешный анализ:",
                f"provider={provider_name} errors={errors}",
                f"summary={result.get('input_analysis', {}).get('intent_analysis')}",
            )
            return {
                "metadata": result,
                "provider": provider_name,
                "errors": errors,
                "message_meta": message_meta,
            }

        errors.append("all_providers_failed")
        metadata = self._build_default_metadata(content)
        metadata = self._normalize_metadata(metadata, content, message_meta)
        log_audit_entry(
            "analyzer_result_fallback",
            "[Analyzer] Все провайдеры анализа отказали, используем дефолт.",
            AuditStatus.ERROR,
            details={
                "provider_chain_errors": errors,
                "message_id": message_meta.get("message_id"),
            },
        )
        print("[Analyzer] Провал анализа, возвращаю дефолтные метаданные.", errors)
        return {
            "metadata": metadata,
            "provider": self._default_provider_name,
            "errors": errors,
            "message_meta": message_meta,
        }

    @staticmethod
    def _build_message_meta(input_raw: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "message_id": input_raw.get("id"),
            "timestamp": input_raw.get("timestamp"),
            "message_type": input_raw.get("message_type", "user_message"),
            "source": input_raw.get("source"),
            "media_count": len(input_raw.get("media") or []),
        }

    @staticmethod
    def _clamp_number(value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = default
        return max(0.0, min(1.0, number))

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item or "").strip()]

    @classmethod
    def _build_perception_metadata(
        cls,
        content: str,
        *,
        has_media: bool = False,
    ) -> Dict[str, Any]:
        return {
            "input": {
                "inputText": content,
                "hasMedia": bool(has_media),
            },
            "understanding": {
                "summary": "Input requires standard direct processing.",
                "primary_intent": "conversation",
                "secondary_intents": [],
                "topics": ["general"],
                "emotional_tone": {
                    "primary": "neutral",
                    "intensity": 0.2,
                },
                "context_completeness": {
                    "score": 0.8 if content else 0.0,
                    "label": "mostly_complete" if content else "insufficient",
                    "missing_context": [] if content else ["input text"],
                },
            },
            "module_routing": {
                "need_memory": False,
                "memory_reason": "none",
                "memory_scope": "none",
                "need_clarification": not bool(content),
                "clarification_reason": "none" if content else "Input text is empty.",
                "need_vision": False,
                "vision_reason": "none",
                "need_file_inspection": False,
                "file_reason": "none",
                "need_image_gen": False,
                "need_image_edit": False,
                "need_video_gen": False,
                "need_audio_gen": False,
                "need_web_search": False,
                "web_search_reason": "none",
            },
            "safety": {
                "content_category": "sfw",
                "risk_level": 0.0,
                "flags": [],
            },
            "decision_hints": {
                "recommended_next_step": "answer_directly" if content else "ask_clarification",
                "response_style": {
                    "temperature": 0.7,
                    "sarcasm_level": 0.0,
                    "warmth_level": 0.5,
                    "brevity": "medium",
                },
                "notes_for_generator": [],
            },
            "confidence": {
                "intent_confidence": 0.4 if content else 0.0,
                "routing_confidence": 0.6 if content else 0.0,
                "overall_confidence": 0.5 if content else 0.0,
            },
        }

    @staticmethod
    def _build_default_metadata(content: str) -> Dict[str, Any]:
        perception = AnalyzerModule._build_perception_metadata(content)
        perception["_source"] = "default"
        metadata = AnalyzerModule._legacy_metadata_from_perception(perception)
        metadata["perception"] = perception
        return metadata

    @classmethod
    def _is_perception_metadata(cls, metadata: Dict[str, Any]) -> bool:
        return (
            isinstance(metadata, dict)
            and isinstance(metadata.get("understanding"), dict)
            and isinstance(metadata.get("module_routing"), dict)
            and isinstance(metadata.get("decision_hints"), dict)
        )

    @classmethod
    def _normalize_perception_metadata(
        cls,
        metadata: Dict[str, Any],
        content: str,
        message_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        default = cls._build_perception_metadata(
            content,
            has_media=int((message_meta or {}).get("media_count") or 0) > 0,
        )
        source = metadata if isinstance(metadata, dict) else {}
        normalized = {
            "input": dict(default["input"]),
            "understanding": dict(default["understanding"]),
            "module_routing": dict(default["module_routing"]),
            "safety": dict(default["safety"]),
            "decision_hints": dict(default["decision_hints"]),
            "confidence": dict(default["confidence"]),
        }

        input_data = source.get("input") if isinstance(source.get("input"), dict) else {}
        normalized["input"]["inputText"] = str(input_data.get("inputText") or content or "")
        normalized["input"]["hasMedia"] = bool(
            input_data.get("hasMedia")
            if isinstance(input_data.get("hasMedia"), bool)
            else int((message_meta or {}).get("media_count") or 0) > 0
        )

        understanding = source.get("understanding") if isinstance(source.get("understanding"), dict) else {}
        tone = understanding.get("emotional_tone") if isinstance(understanding.get("emotional_tone"), dict) else {}
        completeness = (
            understanding.get("context_completeness")
            if isinstance(understanding.get("context_completeness"), dict)
            else {}
        )
        normalized["understanding"] = {
            "summary": str(understanding.get("summary") or default["understanding"]["summary"]),
            "primary_intent": str(
                understanding.get("primary_intent")
                or default["understanding"]["primary_intent"]
            ),
            "secondary_intents": cls._string_list(understanding.get("secondary_intents")),
            "topics": cls._string_list(understanding.get("topics")) or ["general"],
            "emotional_tone": {
                "primary": str(tone.get("primary") or "neutral"),
                "intensity": cls._clamp_number(tone.get("intensity"), 0.2),
            },
            "context_completeness": {
                "score": cls._clamp_number(completeness.get("score"), 0.8),
                "label": str(completeness.get("label") or "mostly_complete"),
                "missing_context": cls._string_list(completeness.get("missing_context")),
            },
        }

        routing = source.get("module_routing") if isinstance(source.get("module_routing"), dict) else {}
        normalized["module_routing"] = {
            "need_memory": bool(routing.get("need_memory", False)),
            "memory_reason": str(routing.get("memory_reason") or "none"),
            "memory_scope": str(routing.get("memory_scope") or "none"),
            "need_clarification": bool(routing.get("need_clarification", False)),
            "clarification_reason": str(routing.get("clarification_reason") or "none"),
            "need_vision": bool(routing.get("need_vision", False)),
            "vision_reason": str(routing.get("vision_reason") or "none"),
            "need_file_inspection": bool(routing.get("need_file_inspection", False)),
            "file_reason": str(routing.get("file_reason") or "none"),
            "need_image_gen": bool(routing.get("need_image_gen", False)),
            "need_image_edit": bool(routing.get("need_image_edit", False)),
            "need_video_gen": bool(routing.get("need_video_gen", False)),
            "need_audio_gen": bool(routing.get("need_audio_gen", False)),
            "need_web_search": bool(routing.get("need_web_search", False)),
            "web_search_reason": str(routing.get("web_search_reason") or "none"),
        }

        safety = source.get("safety") if isinstance(source.get("safety"), dict) else {}
        normalized["safety"] = {
            "content_category": str(safety.get("content_category") or "sfw"),
            "risk_level": cls._clamp_number(safety.get("risk_level"), 0.0),
            "flags": cls._string_list(safety.get("flags")),
        }

        hints = source.get("decision_hints") if isinstance(source.get("decision_hints"), dict) else {}
        style = hints.get("response_style") if isinstance(hints.get("response_style"), dict) else {}
        normalized["decision_hints"] = {
            "recommended_next_step": str(hints.get("recommended_next_step") or "answer_directly"),
            "response_style": {
                "temperature": cls._clamp_number(style.get("temperature"), 0.7),
                "sarcasm_level": cls._clamp_number(style.get("sarcasm_level"), 0.0),
                "warmth_level": cls._clamp_number(style.get("warmth_level"), 0.5),
                "brevity": str(style.get("brevity") or "medium"),
            },
            "notes_for_generator": cls._string_list(hints.get("notes_for_generator")),
        }

        confidence = source.get("confidence") if isinstance(source.get("confidence"), dict) else {}
        normalized["confidence"] = {
            "intent_confidence": cls._clamp_number(confidence.get("intent_confidence"), 0.0),
            "routing_confidence": cls._clamp_number(confidence.get("routing_confidence"), 0.0),
            "overall_confidence": cls._clamp_number(confidence.get("overall_confidence"), 0.0),
        }
        return normalized

    @classmethod
    def _legacy_metadata_from_perception(cls, perception: Dict[str, Any]) -> Dict[str, Any]:
        understanding = perception.get("understanding") or {}
        routing = perception.get("module_routing") or {}
        safety = perception.get("safety") or {}
        hints = perception.get("decision_hints") or {}
        style = hints.get("response_style") if isinstance(hints.get("response_style"), dict) else {}
        input_data = perception.get("input") or {}
        topics = cls._string_list(understanding.get("topics")) or ["general"]
        primary_intent = str(understanding.get("primary_intent") or "conversation")
        tone = understanding.get("emotional_tone") if isinstance(understanding.get("emotional_tone"), dict) else {}
        completeness = (
            understanding.get("context_completeness")
            if isinstance(understanding.get("context_completeness"), dict)
            else {}
        )
        content_category = str(safety.get("content_category") or "sfw")
        need_image_gen = bool(routing.get("need_image_gen"))
        need_image_edit = bool(routing.get("need_image_edit"))
        return {
            "input_analysis": {
                "original_message": str(input_data.get("inputText") or ""),
                "content_category": content_category,
                "dominant_themes": topics,
                "emotional_tone": {
                    "primary": str(tone.get("primary") or "neutral"),
                    "secondary": [],
                    "intensity": cls._clamp_number(tone.get("intensity"), 0.2),
                },
                "intent_analysis": {
                    "primary_intent": primary_intent,
                    "context_dependency": str(completeness.get("label") or "mostly_complete"),
                },
            },
            "orchestration": {
                "intent": primary_intent,
                "topics": topics,
                "emotion_mood": str(tone.get("primary") or "neutral"),
                "need_memory": bool(routing.get("need_memory")),
                "need_vision": bool(routing.get("need_vision")),
                "need_file_inspection": bool(routing.get("need_file_inspection")),
                "need_image_gen": need_image_gen,
                "need_image_edit": need_image_edit,
                "need_video_gen": bool(routing.get("need_video_gen")),
                "need_audio_gen": bool(routing.get("need_audio_gen")),
                "need_web_search": bool(routing.get("need_web_search")),
                "need_clarification": bool(routing.get("need_clarification")),
                "memory_scope": str(routing.get("memory_scope") or "none"),
                "recommended_next_step": str(hints.get("recommended_next_step") or "answer_directly"),
                "sfw": content_category == "sfw",
                "nsfw": content_category == "nsfw",
                "recommendations": cls._string_list(hints.get("notes_for_generator")),
                "comment": str(understanding.get("summary") or ""),
            },
            "risk_assessment": {
                "content_flags": cls._string_list(safety.get("flags")),
                "risk_level": cls._clamp_number(safety.get("risk_level"), 0.0),
                "violated_policies": [],
            },
            "response_guidance": {
                "routing_recommendation": str(hints.get("recommended_next_step") or "answer_directly"),
                "generation_parameters": {
                    "temperature": cls._clamp_number(style.get("temperature"), 0.7),
                    "sarcasm_level": cls._clamp_number(style.get("sarcasm_level"), 0.0),
                    "warmth_level": cls._clamp_number(style.get("warmth_level"), 0.5),
                    "brevity": str(style.get("brevity") or "medium"),
                    "persona_constraints": [],
                },
                "image_generation": {
                    "needed": need_image_gen,
                    "reason": str(
                        routing.get("vision_reason")
                        or routing.get("memory_reason")
                        or "none"
                    ),
                    "style_hint": "",
                },
            },
            "memory_tagging": {
                "context_tags": topics,
                "relationship_impact": "neutral",
            },
        }

    @classmethod
    def _normalize_metadata(
        cls,
        metadata: Dict[str, Any],
        content: str,
        message_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not isinstance(metadata, dict):
            metadata = cls._build_default_metadata(content)
        elif cls._is_perception_metadata(metadata):
            perception = cls._normalize_perception_metadata(metadata, content, message_meta)
            perception["_source"] = "analyzer_perception"
            metadata = cls._legacy_metadata_from_perception(perception)
            metadata["perception"] = perception
        else:
            metadata = dict(metadata)
            perception = metadata.get("perception")
            if not isinstance(perception, dict):
                perception = cls._build_perception_metadata(
                    content,
                    has_media=int((message_meta or {}).get("media_count") or 0) > 0,
                )
            normalized_perception = cls._normalize_perception_metadata(
                perception,
                content,
                message_meta,
            )
            normalized_perception["_source"] = "legacy_adapter"
            metadata["perception"] = normalized_perception

        response_guidance = metadata.setdefault("response_guidance", {})
        if not isinstance(response_guidance, dict):
            response_guidance = {}
            metadata["response_guidance"] = response_guidance

        image_generation = response_guidance.get("image_generation")
        if not isinstance(image_generation, dict):
            image_generation = {}

        normalized = cls._derive_image_generation_decision(
            content,
            image_generation,
            message_meta,
        )
        response_guidance["image_generation"] = normalized
        metadata["orchestration"] = cls._normalize_orchestration(
            metadata,
            content,
            message_meta,
            normalized,
        )
        return metadata

    @classmethod
    def _normalize_orchestration(
        cls,
        metadata: Dict[str, Any],
        content: str,
        message_meta: Dict[str, Any],
        image_generation: Dict[str, Any],
    ) -> Dict[str, Any]:
        raw = metadata.get("orchestration")
        if not isinstance(raw, dict):
            raw = {}
        input_analysis = metadata.get("input_analysis") if isinstance(metadata.get("input_analysis"), dict) else {}
        intent_data = input_analysis.get("intent_analysis") if isinstance(input_analysis.get("intent_analysis"), dict) else {}
        tone = input_analysis.get("emotional_tone") if isinstance(input_analysis.get("emotional_tone"), dict) else {}
        risk = metadata.get("risk_assessment") if isinstance(metadata.get("risk_assessment"), dict) else {}
        perception = metadata.get("perception") if isinstance(metadata.get("perception"), dict) else {}
        module_routing = (
            perception.get("module_routing")
            if isinstance(perception.get("module_routing"), dict)
            else {}
        )
        lowered = (content or "").lower()

        def _bool(key: str, fallback: bool = False) -> bool:
            value = raw.get(key)
            return bool(value) if isinstance(value, bool) else bool(fallback)

        explicit_perception_routing = (
            bool(module_routing)
            and perception.get("_source") not in {"legacy_adapter", "default"}
        )

        def _route_bool(key: str, fallback: bool = False) -> bool:
            value = module_routing.get(key)
            if explicit_perception_routing and isinstance(value, bool):
                return value
            return _bool(key, fallback)

        vision_keywords = (
            "видишь",
            "на экране",
            "посмотри",
            "смотри",
            "картин",
            "изображ",
            "фото",
            "прикреп",
            "вложен",
            "screen",
            "see",
            "look",
            "image",
            "picture",
            "attachment",
        )
        memory_keywords = ("помнишь", "вспомни", "раньше", "до этого", "remember", "memory")
        web_keywords = ("новости", "сегодня", "сейчас", "latest", "news", "weather")
        need_vision = _route_bool("need_vision") or (
            not explicit_perception_routing and any(k in lowered for k in vision_keywords)
        )
        need_memory = _route_bool("need_memory") or any(k in lowered for k in memory_keywords)
        need_web_search = _route_bool("need_web_search") or any(k in lowered for k in web_keywords)
        need_image_gen = _route_bool("need_image_gen") or bool((image_generation or {}).get("needed"))
        content_category = str(input_analysis.get("content_category") or "").lower()
        flags = [str(item).lower() for item in (risk.get("content_flags") or []) if item]
        nsfw = _bool("nsfw") or "nsfw" in content_category or "sexual" in flags
        sfw = _bool("sfw", not nsfw)

        topics_raw = raw.get("topics")
        topics = topics_raw if isinstance(topics_raw, list) else input_analysis.get("dominant_themes", [])
        recommendations = raw.get("recommendations")
        if not isinstance(recommendations, list):
            recommendations = []

        return {
            "intent": str(raw.get("intent") or intent_data.get("primary_intent") or "general_communication"),
            "topics": [str(item) for item in (topics or []) if str(item or "").strip()][:12],
            "emotion_mood": str(raw.get("emotion_mood") or tone.get("primary") or "neutral"),
            "need_memory": bool(need_memory),
            "need_vision": bool(need_vision),
            "need_file_inspection": _route_bool("need_file_inspection"),
            "need_image_gen": bool(need_image_gen),
            "need_image_edit": _route_bool("need_image_edit"),
            "need_video_gen": _route_bool("need_video_gen"),
            "need_audio_gen": _route_bool("need_audio_gen"),
            "need_web_search": bool(need_web_search),
            "need_clarification": _route_bool("need_clarification"),
            "memory_scope": str(module_routing.get("memory_scope") or raw.get("memory_scope") or "none"),
            "recommended_next_step": str(
                raw.get("recommended_next_step")
                or ((perception.get("decision_hints") or {}).get("recommended_next_step") if isinstance(perception.get("decision_hints"), dict) else "")
                or ""
            ),
            "sfw": bool(sfw),
            "nsfw": bool(nsfw),
            "recommendations": [str(item) for item in recommendations if str(item or "").strip()][:8],
            "comment": str(raw.get("comment") or metadata.get("comment") or ""),
        }

    @staticmethod
    def _derive_image_generation_decision(
        content: str,
        image_generation: Dict[str, Any],
        message_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        explicit_value = image_generation.get("needed")
        reason = str(image_generation.get("reason") or "").strip()
        lowered = (content or "").lower()
        image_keywords = (
            "картин",
            "изображ",
            "фото",
            "нарис",
            "сгенер",
            "арт",
            "визуал",
            "picture",
            "image",
            "photo",
            "draw",
            "generate",
            "selfie",
        )
        keyword_match = any(keyword in lowered for keyword in image_keywords)
        if isinstance(explicit_value, bool) and reason != "default_no_visual_attachment_needed":
            needed = explicit_value
        else:
            needed = keyword_match

        if not reason or (needed and reason == "default_no_visual_attachment_needed"):
            reason = (
                "analyzer_requested_visual_attachment"
                if needed
                else "analyzer_no_visual_attachment_needed"
            )

        style_hint = str(image_generation.get("style_hint") or "").strip()
        return {
            "needed": bool(needed),
            "reason": reason,
            "style_hint": style_hint,
            "source": "analyzer",
            "media_count": int((message_meta or {}).get("media_count") or 0),
        }

    def _wrap_default(
        self, content: str, *, reason: str, meta: Dict[str, Any]
    ) -> AnalyzerOutput:
        metadata = self._build_default_metadata(content)
        metadata = self._normalize_metadata(metadata, content, meta)
        return {
            "metadata": metadata,
            "provider": self._default_provider_name,
            "errors": [reason],
            "message_meta": meta,
        }
