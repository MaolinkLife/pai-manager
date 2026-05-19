# core/instructor.py
from typing import Dict, Any, List, Optional
from datetime import datetime

from core.prompt_loader import load_system_prompt
from modules.system import config as config_service
from modules.system.logger import log_audit_entry, AuditStatus
from modules.system.localization import get_text
from constants.rules import SYSTEM_RULES
from constants.messages import DEFAULT_CONTEXT, NO_MEMORY, NO_KNOWLEDGE


def _normalize_message_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


class Instructor:
    """Assembles the final structured system prompt."""

    async def build_system_prompt(
        self,
        analysis: Dict[str, Any],
        decisions: Dict[str, bool],
        memory_context: Dict[str, Any],
        moral_state: Dict[str, Any],
        visual_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build strict system prompt (core persona + hard rules only)."""
        try:
            print(
                get_text(
                    "instructor.print_start",
                    default="[Instructor] Старт сборки системного промпта.",
                )
            )
            log_audit_entry(
                "instructor_prompt_build_start",
                get_text(
                    "instructor.build_start",
                    default="[Instructor] Building system prompt.",
                ),
                AuditStatus.INFO,
                details={
                    "analysis_keys": list((analysis or {}).keys()),
                    "decisions": decisions,
                    "memory_meta": {
                        "has_key_facts": bool(
                            (memory_context or {}).get("key_facts")
                        ),
                        "matches": len((memory_context or {}).get("matches", [])),
                    },
                    "moral_state_keys": list((moral_state or {}).keys()),
                    "has_visual_context": bool(visual_context),
                },
                message_key="instructor.build_start",
            )

            base_prompt = load_system_prompt()
            print(
                get_text(
                    "instructor.print_base_loaded",
                    default="[Instructor] Загружен базовый промпт персонажа.",
                )
            )
            sections: List[str] = []
            section_map: Dict[str, Dict[str, Any]] = {}

            # Base persona prompt. Keep the generator-facing system message plain;
            # section tags are internal structure, not behavioral content.
            core_section = base_prompt.strip()
            sections.append(core_section)
            section_map["core"] = {
                "reason": "Base persona prompt",
                "content": base_prompt,
                "length": len(base_prompt),
            }

            # [INSTRUCTION] persona tweaks (currently disabled, reserved)
            persona_section = self._build_persona_section(analysis)
            if persona_section:
                sections.append(persona_section)
                section_map["persona"] = {
                    "reason": "Persona adjustments",
                    "length": len(persona_section),
                }

            # [RULES] hard constraints
            sections.append("\n".join(SYSTEM_RULES))
            section_map["rules"] = {
                "reason": "Hard system rules",
                "rules_count": len(SYSTEM_RULES),
            }
            print("[Instructor] Добавлены системные правила.")

            final_prompt = "\n\n".join(sections)
            print(
                get_text(
                    "instructor.print_complete",
                    default="[Instructor] Системный промпт собран.",
                )
            )

            log_audit_entry(
                "instructor_prompt_build_success",
                get_text(
                    "instructor.build_success",
                    default="[Instructor] System prompt successfully built.",
                ),
                AuditStatus.SUCCESS,
                details={
                    "sections_count": len(sections),
                    "prompt_sections": section_map,
                    "final_prompt": final_prompt,
                },
                message_key="instructor.build_success",
            )

            return final_prompt

        except Exception as exc:
            error_text = str(exc)
            log_audit_entry(
                "instructor_prompt_build_error",
                get_text(
                    "instructor.build_error",
                    params={"error": error_text},
                    default="[Instructor] Error while building system prompt: {error}",
                ),
                AuditStatus.ERROR,
                details={"error": error_text, "error_type": type(exc).__name__},
                message_key="instructor.build_error",
                message_args={"error": error_text},
            )
            return "System prompt unavailable due to error."

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------
    def _build_context_section(self, analysis: Dict[str, Any]) -> str:
        context_parts: List[str] = []

        themes = analysis.get("input_analysis", {}).get("dominant_themes", [])
        if themes:
            context_parts.append(f"Themes: {', '.join(themes)}")

        intent = (
            analysis.get("input_analysis", {})
            .get("intent_analysis", {})
            .get("primary_intent", "")
        )
        if intent:
            context_parts.append(f"Intent: {intent}")

        emotional_tone = (
            analysis.get("input_analysis", {})
            .get("emotional_tone", {})
            .get("primary", "")
        )
        if emotional_tone:
            context_parts.append(f"Emotional tone: {emotional_tone}")

        if context_parts:
            return f"[CONTEXT]\n{'; '.join(context_parts)}"
        return f"[CONTEXT]\n{DEFAULT_CONTEXT}"

    def _build_context_tool_content(self, analysis: Dict[str, Any]) -> str:
        section = self._build_context_section(analysis)
        return section.replace("[CONTEXT]\n", "", 1).strip()

    def _build_memory_section(self, memory_context: Dict[str, Any]) -> str:
        key_facts = memory_context.get("key_facts")
        if key_facts:
            return f"[MEMORY]\n{'; '.join(key_facts)}"
        return f"[MEMORY]\n{NO_MEMORY}"

    def _build_memory_tool_content(self, memory_context: Dict[str, Any]) -> str:
        context = memory_context or {}
        status = str(context.get("memory_status") or "").strip().lower()
        key_facts = context.get("key_facts")
        stage_trace = context.get("stage_trace")
        emotional_events = context.get("emotional_events")
        facts: List[str] = []
        if isinstance(key_facts, list):
            facts = [str(item or "").strip() for item in key_facts if str(item or "").strip()]

        stage_lines: List[str] = []
        if isinstance(stage_trace, list):
            for item in stage_trace:
                if not isinstance(item, dict):
                    continue
                stage_name = str(item.get("stage") or "unknown").strip()
                stage_status = str(item.get("status") or "unknown").strip()
                candidates = item.get("candidates")
                matches = item.get("matches")
                parts = [f"- {stage_name}: status={stage_status}"]
                if isinstance(candidates, int):
                    parts.append(f"candidates={candidates}")
                if isinstance(matches, int):
                    parts.append(f"matches={matches}")
                chunk_size = item.get("chunk_size")
                chunks_checked = item.get("chunks_checked")
                if isinstance(chunk_size, int) and chunk_size > 0:
                    parts.append(f"chunk_size={chunk_size}")
                if isinstance(chunks_checked, int):
                    parts.append(f"chunks_checked={chunks_checked}")
                stage_lines.append("; ".join(parts))

        stages_block = ""
        if stage_lines:
            stages_block = "\n[STAGES]\n" + "\n".join(stage_lines[:12])

        emotions_block = ""
        if isinstance(emotional_events, list) and emotional_events:
            emotion_lines: List[str] = []
            for event in emotional_events[:5]:
                if not isinstance(event, dict):
                    continue
                emotion = str(event.get("emotion") or "").strip()
                if not emotion:
                    continue
                intensity = event.get("intensity")
                trigger_text = str(event.get("trigger_text") or "").strip()
                line = f"- {emotion}"
                if isinstance(intensity, (int, float)):
                    line += f" ({round(float(intensity), 3)})"
                if trigger_text:
                    line += f": {trigger_text[:120]}"
                emotion_lines.append(line)
            if emotion_lines:
                emotions_block = "\n[EMOTIONS]\n" + "\n".join(emotion_lines)

        if status in {"module_unavailable", "embedding_failed", "error"}:
            return "[ERROR]: memory module is unavailable." + stages_block + emotions_block
        if facts and any(item != NO_MEMORY for item in facts):
            lines = "\n".join(f"- {item}" for item in facts[:10])
            return f"[OK]: memory records found:\n{lines}{stages_block}{emotions_block}"
        if status == "disabled":
            return "[OK]: memory module is disabled." + stages_block + emotions_block
        return "[OK]: no relevant memory records found." + stages_block + emotions_block

    def _build_conversation_state_section(self, memory_context: Dict[str, Any]) -> str:
        state = memory_context.get("conversation_state") or {}
        if not isinstance(state, dict):
            return ""

        last_message_at = state.get("last_message_at")
        hours_since = state.get("hours_since_last_message")
        inactivity_bucket = state.get("inactivity_bucket")
        last_topic = state.get("last_topic")
        recent_tone_summary = state.get("recent_tone_summary")

        if (
            last_message_at is None
            and hours_since is None
            and not last_topic
            and not recent_tone_summary
        ):
            return ""

        details: List[str] = []
        if last_message_at:
            details.append(f"Last message at: {last_message_at}")
        if hours_since is not None:
            details.append(f"Hours since last message: {hours_since}")
        if inactivity_bucket:
            details.append(f"Inactivity bucket: {inactivity_bucket}")
        if last_topic:
            details.append(f"Last topic: {last_topic}")
        if recent_tone_summary:
            details.append(f"Recent tone summary: {recent_tone_summary}")

        if not details:
            return ""
        return "[CONTEXT:RELATION]\n" + "; ".join(details)

    def _build_conversation_state_tool_content(
        self, memory_context: Dict[str, Any]
    ) -> str:
        section = self._build_conversation_state_section(memory_context)
        if not section:
            return ""
        return section.replace("[CONTEXT:RELATION]\n", "", 1).strip()

    def _build_knowledge_section(self, memory_context: Dict[str, Any]) -> str:
        lore_matches = memory_context.get("lore_matches")
        if lore_matches:
            return f"[KNOWLEDGE]\n" + "\n---\n".join(lore_matches)
        return f"[KNOWLEDGE]\n{NO_KNOWLEDGE}"

    def _build_knowledge_tool_content(self, memory_context: Dict[str, Any]) -> str:
        context = memory_context or {}
        lore_matches = context.get("lore_matches")
        if isinstance(lore_matches, list) and lore_matches:
            lines = "\n".join(
                f"- {str(item or '').strip()}" for item in lore_matches[:8] if str(item or "").strip()
            ).strip()
            if lines:
                return f"[OK]: lorebook matches found:\n{lines}"
        return "[ERROR] Not Found"

    def _build_emotion_tool_content(self, moral_state: Dict[str, Any]) -> str:
        state = moral_state or {}
        emotion = str(state.get("current_emotion") or "neutral").strip() or "neutral"
        intensity = state.get("emotion_intensity", state.get("intensity"))
        relationship_status = str(state.get("relationship_status") or "").strip()
        narrative = str(state.get("narrative") or "").strip()
        affective_state = state.get("affective_state") if isinstance(state.get("affective_state"), dict) else {}
        trigger = str(state.get("trigger") or affective_state.get("trigger") or "").strip()
        influence = state.get("influence") if isinstance(state.get("influence"), dict) else {}
        if not influence and isinstance(affective_state.get("influence"), dict):
            influence = affective_state.get("influence") or {}
        associated_events = (
            state.get("associated_events")
            if isinstance(state.get("associated_events"), list)
            else affective_state.get("associated_events")
            if isinstance(affective_state.get("associated_events"), list)
            else []
        )
        metrics = state.get("metrics") if isinstance(state.get("metrics"), dict) else {}
        recommendations = [
            str(item or "").strip()
            for item in (state.get("recommendations") or [])
            if str(item or "").strip()
        ]
        directives = [
            str(item or "").strip()
            for item in (state.get("hard_directives") or [])
            if str(item or "").strip()
        ]

        label = str(affective_state.get("label") or emotion).strip()
        parts: List[str] = [f"Current emotional state: {label} ({emotion})"]
        if isinstance(intensity, (int, float)):
            parts.append(f"intensity={round(float(intensity), 3)}")
        if relationship_status:
            parts.append(f"relationship={relationship_status}")
        if metrics:
            metric_text = ", ".join(
                f"{key}={round(float(value), 3)}"
                for key, value in metrics.items()
                if isinstance(value, (int, float))
            )
            if metric_text:
                parts.append(f"metrics: {metric_text}")

        lines = ["; ".join(parts)]
        if trigger:
            lines.append(f"Why this state changed: {trigger[:700]}")
        if influence:
            influence_text = ", ".join(
                f"{key}={value}" for key, value in influence.items() if value not in (None, "")
            )
            if influence_text:
                lines.append(f"Behavior influence: {influence_text}")
        if associated_events:
            lines.append(
                "Associated events:\n"
                + "\n".join(f"- {str(item)[:220]}" for item in associated_events[:5])
            )
        if narrative:
            lines.append(f"Self-expression guidance: {narrative[:800]}")
        if recommendations:
            lines.append("Recommendations:\n" + "\n".join(f"- {item}" for item in recommendations[:6]))
        if directives:
            lines.append("Hard directives:\n" + "\n".join(f"- {item}" for item in directives[:6]))
        return "\n".join(lines)

    def _build_persona_section(self, analysis: Dict[str, Any]) -> str:
        persona_constraints = (
            analysis.get("response_guidance", {})
            .get("generation_parameters", {})
            .get("persona_constraints", [])
        )
        # Persona adjustments are intentionally disabled to preserve the base character profile.
        if persona_constraints:  # pragma: no cover - informative branch only
            return ""
        return ""

    def _render_visual_context(self, visual_context: Optional[Dict[str, Any]]) -> str:
        if not visual_context:
            return ""

        lines: List[str] = []

        attachments = (visual_context.get("attachments") or {}).get("items", [])
        for idx, item in enumerate(attachments, start=1):
            description = (item.get("description") or "").strip()
            if not description:
                continue
            label = (
                item.get("label")
                or item.get("name")
                or item.get("filename")
                or f"Attachment {idx}"
            )
            lines.append(f"{label}: {description}")

        screen_info = visual_context.get("screen") or {}
        screen_description = (screen_info.get("description") or "").strip()
        if screen_description:
            timestamp = screen_info.get("captured_at")
            prefix = "Screen snapshot"
            if timestamp:
                prefix = f"{prefix} ({timestamp})"
            lines.append(f"{prefix}: {screen_description}")

        return "\n".join(lines)

    def _get_environment_info(self) -> str:
        now = datetime.now()
        date_str = now.strftime("%d %B %Y")
        time_str = now.strftime("%H:%M:%S")

        from modules.system import config as config_service

        location = config_service.get_config_value("location", "unknown")
        coordinates = config_service.get_config_value("coordinates", None)

        parts = [
            f"Date: {date_str}",
            f"Time: {time_str}",
        ]

        if location and location != "unknown":
            parts.append(f"Location: {location}")

        if coordinates:
            parts.append(f"Coordinates: {coordinates}")

        return "\n".join(parts)

    def _build_environment_tool_content(self) -> str:
        return self._get_environment_info()

    def _build_dynamic_tool_messages(
        self,
        *,
        user_message: Dict[str, Any],
        analysis: Optional[Dict[str, Any]] = None,
        decisions: Optional[Dict[str, bool]] = None,
        moral_state: Optional[Dict[str, Any]] = None,
        memory_context: Optional[Dict[str, Any]] = None,
        visual_context: Optional[Dict[str, Any]] = None,
        generated_image_context: Optional[Dict[str, Any]] = None,
        module_tasks: Optional[List[Dict[str, Any]]] = None,
        tool_hints: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        dynamic_messages: List[Dict[str, Any]] = []

        # Analyzer output is operational routing metadata for Decision Layer.
        # It should not be exposed as final-answer context to the generator.

        memory_info = self._build_memory_tool_content(memory_context or {}).strip()
        if memory_info and not memory_info.lower().startswith("[ok]: memory module is disabled"):
            dynamic_messages.append(
                {
                    "role": "tool",
                    "name": "memory.lookup",
                    "content": memory_info,
                }
            )

        knowledge_info = self._build_knowledge_tool_content(memory_context or {}).strip()
        memory_status = str((memory_context or {}).get("memory_status") or "").strip().lower()
        if (
            knowledge_info
            and not knowledge_info.startswith("[ERROR]")
            and memory_status not in {"", "disabled"}
        ):
            dynamic_messages.append(
                {
                    "role": "tool",
                    "name": "knowledge.lorebook",
                    "content": knowledge_info,
                }
            )

        emotion_info = self._build_emotion_tool_content(moral_state or {}).strip()
        moral_disabled = bool((moral_state or {}).get("meta", {}).get("disabled")) or not bool(moral_state)
        if emotion_info and not moral_disabled:
            dynamic_messages.append(
                {
                    "role": "tool",
                    "name": "state.emotion",
                    "content": emotion_info,
                }
            )

        env_info = self._build_environment_tool_content().strip()
        if env_info:
            dynamic_messages.append(
                {
                    "role": "tool",
                    "name": "system.clock",
                    "content": env_info,
                }
            )

        relation_info = self._build_conversation_state_tool_content(
            memory_context or {}
        ).strip()
        if relation_info and memory_status not in {"", "disabled"}:
            dynamic_messages.append(
                {
                    "role": "tool",
                    "name": "context.relationship",
                    "content": relation_info,
                }
            )

        visual_info = self._render_visual_context(visual_context or {}).strip()
        if visual_info:
            dynamic_messages.append(
                {
                    "role": "tool",
                    "name": "vision.context",
                    "content": visual_info,
                }
            )

        if isinstance(generated_image_context, dict) and generated_image_context:
            image_lines: List[str] = []
            prompt = str(generated_image_context.get("prompt") or "").strip()
            description = str(generated_image_context.get("description") or "").strip()
            model = str(generated_image_context.get("model") or "").strip()
            if prompt:
                image_lines.append(f"Prompt used: {prompt[:1200]}")
            if description:
                image_lines.append(f"Generated image description: {description[:1200]}")
            if model:
                image_lines.append(f"Image model: {model}")
            if image_lines:
                dynamic_messages.append(
                    {
                        "role": "tool",
                        "name": "image_generation.result",
                        "content": "\n".join(image_lines),
                    }
                )

        # module_tasks and tool_hints are operational data for Decision Layer/UI logs.
        # They are intentionally not exposed as final-answer tool context.

        runtime_meta = user_message.get("runtime_meta")
        if isinstance(runtime_meta, dict):
            time_awareness = runtime_meta.get("time_awareness")
            open_loop = runtime_meta.get("open_loop_context")
            runtime_lines: List[str] = []
            if isinstance(time_awareness, dict):
                local_time = str(time_awareness.get("local_time") or "").strip()
                day_phase = str(time_awareness.get("day_phase") or "").strip()
                if local_time:
                    runtime_lines.append(f"Local time: {local_time}")
                if day_phase:
                    runtime_lines.append(f"Day phase: {day_phase}")
                runtime_lines.append(
                    f"Quiet hours: {'yes' if bool(time_awareness.get('is_quiet_hours')) else 'no'}"
                )
            if isinstance(open_loop, dict):
                runtime_lines.extend(
                    [
                        (
                            "Open loop: "
                            f"unanswered_initiatives_in_row={int(open_loop.get('unanswered_initiatives_in_row') or 0)}; "
                            f"hours_since_last_user_message={open_loop.get('hours_since_last_user_message')}; "
                            f"hours_since_last_outbound={open_loop.get('hours_since_last_outbound')}; "
                            f"has_open_conversational_loop={bool(open_loop.get('has_open_conversational_loop'))}"
                        ),
                        f"Last user excerpt: {str(open_loop.get('last_user_message_excerpt') or 'none')[:220]}",
                        f"Last unanswered outbound excerpt: {str(open_loop.get('last_unanswered_outbound_excerpt') or 'none')[:220]}",
                    ]
                )
            if runtime_lines:
                dynamic_messages.append(
                    {
                        "role": "tool",
                        "name": "telegram.runtime",
                        "content": "\n".join(runtime_lines),
                    }
                )

            repeat_feedback = runtime_meta.get("repeat_feedback")
            if isinstance(repeat_feedback, dict) and bool(repeat_feedback.get("enabled")):
                repeat_lines = [
                    f"Reason: {str(repeat_feedback.get('reason') or 'repeat_guard').strip()}",
                    str(repeat_feedback.get("instruction") or "").strip(),
                ]
                blocked_text = str(repeat_feedback.get("blocked_text") or "").strip()
                if blocked_text:
                    repeat_lines.append(f"Blocked draft: {blocked_text[:400]}")
                dynamic_messages.append(
                    {
                        "role": "tool",
                        "name": "repeat.guard",
                        "content": "\n".join(line for line in repeat_lines if line),
                    }
                )

            memory_hint = str(runtime_meta.get("memory_hint") or "").strip()
            if memory_hint:
                dynamic_messages.append(
                    {
                        "role": "tool",
                        "name": "memory.hint",
                        "content": memory_hint[:1200],
                    }
                )

        return dynamic_messages

    def _build_attachment_summary(
        self, media_list: Optional[List[Dict[str, Any]]]
    ) -> str:
        if not media_list:
            return ""

        image_descriptions: List[str] = []
        image_index = 0
        for media in media_list:
            if (media.get("category") or "").lower() != "image":
                continue
            image_index += 1
            summary = (media.get("description") or "").strip()
            if summary:
                label = f"Image {image_index}" if image_index > 1 else "Image"
                image_descriptions.append(f"{label}: {summary}")

        if not image_descriptions:
            return ""

        lines = "\n".join(image_descriptions)
        return "User provided image attachments:\n" + lines

    async def format_for_api(
        self,
        system_prompt: str,
        user_message: Dict[str, Any],
        *,
        analysis: Optional[Dict[str, Any]] = None,
        decisions: Optional[Dict[str, bool]] = None,
        moral_state: Optional[Dict[str, Any]] = None,
        memory_context: Optional[Dict[str, Any]] = None,
        visual_context: Optional[Dict[str, Any]] = None,
        generated_image_context: Optional[Dict[str, Any]] = None,
        module_tasks: Optional[List[Dict[str, Any]]] = None,
        tool_hints: Optional[Dict[str, Any]] = None,
        history_limit_override: Optional[int] = None,
        include_dynamic_context_tools: bool = True,
    ) -> list:
        print(
            get_text(
                "instructor.print_format_start",
                default="[Instructor] Форматируем историю для генератора.",
            )
        )
        log_audit_entry(
            "instructor_format_for_api",
            get_text(
                "instructor.format_start",
                default="[Instructor] Formatting message history for API.",
            ),
            AuditStatus.INFO,
            details={
                "message_id": user_message.get("id"),
                "history_length": len(user_message.get("history", [])),
                "system_prompt_preview": system_prompt[:500],
                "history_limit_raw": config_service.get_config_value("rag.history_limit", 10),
                "has_tool_hints": bool(tool_hints),
                "has_memory_context": bool(memory_context),
            },
            message_key="instructor.format_start",
        )

        history = user_message.get("history", [])
        history_limit_raw = (
            history_limit_override
            if history_limit_override is not None
            else config_service.get_config_value("rag.history_limit", 10)
        )
        try:
            history_limit = int(history_limit_raw)
        except (TypeError, ValueError):
            history_limit = 10
        history_limit = max(history_limit, 0)
        recent_history = history[-history_limit:] if history_limit else []
        recent_history = self._dedupe_recent_history(recent_history)
        raw_recent_history_count = len(recent_history)
        pair_limit = self._get_recent_dialogue_pair_limit()
        recent_history = self._select_recent_dialogue_pairs(recent_history, pair_limit)

        messages = [{"role": "system", "content": system_prompt}]
        dynamic_tool_messages: List[Dict[str, Any]] = []
        memory_context_for_tools = self._remove_recent_history_memory_duplicates(
            memory_context or {},
            recent_history,
            user_message,
        )
        if include_dynamic_context_tools:
            dynamic_tool_messages = self._build_dynamic_tool_messages(
                user_message=user_message,
                analysis=analysis,
                decisions=decisions,
                moral_state=moral_state,
                memory_context=memory_context_for_tools,
                visual_context=visual_context,
                generated_image_context=generated_image_context,
                module_tasks=module_tasks,
                tool_hints=tool_hints,
            )
        messages.extend(dynamic_tool_messages)

        user_already_in_history = self._history_contains_current_user(
            recent_history,
            user_message,
        )

        for msg in recent_history:
            if msg.get("role") == "system":
                continue
            role = str(msg.get("role") or "user")
            if role not in {"user", "assistant"}:
                continue
            enriched_msg = {
                "role": role,
                "content": msg.get("content"),
                "id": msg.get("id"),
            }
            if msg.get("timestamp"):
                enriched_msg["timestamp"] = msg.get("timestamp")
            if "media" in msg:
                enriched_msg["media"] = msg.get("media")
            messages.append(enriched_msg)

        if not user_already_in_history:
            enriched_user = {
                "role": "user",
                "content": user_message.get("content", ""),
                "id": user_message.get("id"),
            }
            if user_message.get("timestamp"):
                enriched_user["timestamp"] = user_message.get("timestamp")
            if "media" in user_message:
                enriched_user["media"] = user_message.get("media")
            messages.append(enriched_user)

        log_audit_entry(
            "instructor_format_for_api_result",
            get_text(
                "instructor.format_success",
                default="[Instructor] History formatted for generator.",
            ),
            AuditStatus.SUCCESS,
            details={
                "total_messages": len(messages),
                "user_message_id": user_message.get("id"),
                "message_roles": [msg.get("role") for msg in messages],
                "history_messages_used": len(recent_history),
                "history_messages_raw": raw_recent_history_count,
                "history_limit": history_limit,
                "history_pair_limit": pair_limit,
                "has_tool_hints": bool(tool_hints),
                "dynamic_tool_messages": len(dynamic_tool_messages),
                "current_user_already_in_history": user_already_in_history,
            },
            message_key="instructor.format_success",
        )
        print(
            get_text(
                "instructor.print_format_complete",
                default="[Instructor] Формирование истории завершено.",
            )
        )

        return messages

    @staticmethod
    def _get_recent_dialogue_pair_limit() -> int:
        raw = config_service.get_config_value("api.message_pair_limit", 4)
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 4

    def _select_recent_dialogue_pairs(
        self,
        history: List[Dict[str, Any]],
        pair_limit: int,
    ) -> List[Dict[str, Any]]:
        if pair_limit <= 0 or not history:
            return []

        dialogue = [
            item for item in history
            if isinstance(item, dict) and str(item.get("role") or "").strip() in {"user", "assistant"}
        ]
        selected: List[Dict[str, Any]] = []
        selected_keys: set[tuple[str, str, str]] = set()
        pairs = 0
        index = len(dialogue) - 1

        def key_for(item: Dict[str, Any]) -> tuple[str, str, str]:
            return (
                str(item.get("id") or "").strip(),
                str(item.get("role") or "").strip(),
                _normalize_message_text(item.get("content")),
            )

        def add(item: Dict[str, Any]) -> None:
            key = key_for(item)
            if key not in selected_keys:
                selected.append(item)
                selected_keys.add(key)

        while index >= 0 and pairs < pair_limit:
            item = dialogue[index]
            role = str(item.get("role") or "").strip()
            if role != "assistant":
                index -= 1
                continue

            add(item)
            user_index = index - 1
            while user_index >= 0:
                candidate = dialogue[user_index]
                if str(candidate.get("role") or "").strip() == "user":
                    add(candidate)
                    break
                user_index -= 1

            pairs += 1
            index = user_index - 1

        selected.reverse()
        return selected

    def _remove_recent_history_memory_duplicates(
        self,
        memory_context: Dict[str, Any],
        recent_history: List[Dict[str, Any]],
        current_user_message: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not isinstance(memory_context, dict) or not memory_context:
            return memory_context or {}

        recent_ids = {
            str(item.get("id") or "").strip()
            for item in (recent_history or [])
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        }
        current_id = str((current_user_message or {}).get("id") or "").strip()
        if current_id:
            recent_ids.add(current_id)
        if not recent_ids:
            return memory_context

        matches = memory_context.get("matches")
        if not isinstance(matches, list) or not matches:
            return memory_context

        kept_matches: List[Dict[str, Any]] = []
        removed_ids: set[str] = set()
        for match in matches:
            if not isinstance(match, dict):
                kept_matches.append(match)
                continue
            message_id = str(match.get("message_id") or "").strip()
            if message_id and message_id in recent_ids:
                removed_ids.add(message_id)
                continue
            kept_matches.append(match)

        if not removed_ids:
            return memory_context

        cleaned = dict(memory_context)
        cleaned["matches"] = kept_matches
        cleaned["session_length"] = len(kept_matches)
        if isinstance(cleaned.get("key_facts"), list):
            cleaned["key_facts"] = [
                self._format_memory_match_fact(match)
                for match in kept_matches
                if isinstance(match, dict) and self._format_memory_match_fact(match)
            ]
        cleaned["deduped_recent_message_ids"] = sorted(removed_ids)
        if not kept_matches and not cleaned.get("key_facts"):
            cleaned["memory_status"] = "ready"
        return cleaned

    @staticmethod
    def _format_memory_match_fact(match: Dict[str, Any]) -> str:
        content = str(match.get("content") or "").strip()
        if not content:
            return ""
        role = str(match.get("role") or "").strip().lower()
        label = "User" if role == "user" else "Assistant"
        timestamp = str(match.get("timestamp") or "").strip()
        return f"{label} ({timestamp}): {content}" if timestamp else f"{label}: {content}"

    def _dedupe_recent_history(self, history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()
        previous_key: tuple[str, str] | None = None
        for msg in history or []:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "").strip().lower()
            content = _normalize_message_text(msg.get("content"))
            msg_id = str(msg.get("id") or "").strip()
            if msg_id:
                if msg_id in seen_ids:
                    continue
                seen_ids.add(msg_id)
            current_key = (role, content)
            if content and current_key == previous_key:
                continue
            deduped.append(msg)
            previous_key = current_key
        return deduped

    def _history_contains_current_user(
        self,
        history: List[Dict[str, Any]],
        user_message: Dict[str, Any],
    ) -> bool:
        current_id = str(user_message.get("id") or "").strip()
        current_content = _normalize_message_text(user_message.get("content"))
        current_timestamp = str(user_message.get("timestamp") or "").strip()
        for msg in history or []:
            if not isinstance(msg, dict):
                continue
            if str(msg.get("role") or "").strip().lower() != "user":
                continue
            msg_id = str(msg.get("id") or "").strip()
            if current_id and msg_id == current_id:
                return True
            if (
                current_timestamp
                and current_content
                and str(msg.get("timestamp") or "").strip() == current_timestamp
                and _normalize_message_text(msg.get("content")) == current_content
            ):
                return True
        if not current_content or not history:
            return False
        last_msg = history[-1] if isinstance(history[-1], dict) else {}
        if str(last_msg.get("role") or "").strip().lower() != "user":
            return False
        if _normalize_message_text(last_msg.get("content")) == current_content:
            return True
        return False
