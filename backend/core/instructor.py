# core/instructor.py
from typing import Dict, Any, List, Optional
from datetime import datetime
from zoneinfo import ZoneInfo

from core.prompt_loader import load_system_prompt
from modules.system import config as config_service
from modules.system.logger import log_audit_entry, AuditStatus
from modules.system.localization import get_text
from constants.rules import SYSTEM_RULES
from constants.messages import DEFAULT_CONTEXT, NO_MEMORY, NO_KNOWLEDGE

# What a module block in the scope says (so the system
# knows what is happening to it). Data; a successful lookup that found nothing;
# a module switched off (left out while the instructor excludes disabled
# modules); a module that failed, which always goes in.
MODULE_OK = "ok"
MODULE_EMPTY = "empty"
MODULE_DISABLED = "disabled"
MODULE_FAILED = "failed"

_MEMORY_STATES = {
    "ready": MODULE_OK,
    "not_found": MODULE_EMPTY,
    "empty_input": MODULE_EMPTY,
    "disabled": MODULE_DISABLED,
    "module_unavailable": MODULE_FAILED,
    "embedding_failed": MODULE_FAILED,
    "error": MODULE_FAILED,
    "failed": MODULE_FAILED,
}

NO_LOREBOOK_ENTRIES = "[OK]: no lorebook entries found."


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

        # Failed and disabled memory are said by _build_dynamic_tool_messages. A
        # lookup that found nothing still carries a fallback key fact ("За сегодня
        # ничего не найдено."), which is not a record.
        found = _MEMORY_STATES.get(status, MODULE_EMPTY) != MODULE_EMPTY or not status
        if found and facts and any(item != NO_MEMORY for item in facts):
            lines = "\n".join(f"- {item}" for item in facts[:10])
            return f"[OK]: memory records found:\n{lines}{stages_block}{emotions_block}"
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
        return NO_LOREBOOK_ENTRIES

    @staticmethod
    def _describe_strength(intensity: Any) -> str:
        """The model gets the strength of a feeling in words; the numbers stay in the matrix."""
        if not isinstance(intensity, (int, float)):
            return ""
        value = float(intensity)
        if value >= 0.7:
            return "strong"
        if value >= 0.35:
            return "noticeable"
        return "slight"

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
        meta = state.get("meta") if isinstance(state.get("meta"), dict) else {}
        inner_voice = str(meta.get("inner_voice") or "").strip()

        events_block = (
            "Associated events:\n" + "\n".join(f"- {str(item)[:220]}" for item in associated_events[:5])
            if associated_events
            else ""
        )
        recommendations_block = (
            "Recommendations:\n" + "\n".join(f"- {item}" for item in recommendations[:6])
            if recommendations
            else ""
        )
        directives_block = (
            "Hard directives:\n" + "\n".join(f"- {item}" for item in directives[:6])
            if directives
            else ""
        )

        if inner_voice:
            # The inner voice already says what I feel, why, and how I want to answer.
            blocks = [inner_voice, events_block, recommendations_block, directives_block]
            return "\n".join(block for block in blocks if block)

        label = str(affective_state.get("label") or emotion).strip()
        parts: List[str] = [f"Current emotional state: {label} ({emotion})"]
        strength = self._describe_strength(intensity)
        if strength:
            parts.append(f"strength={strength}")
        if relationship_status:
            parts.append(f"relationship={relationship_status}")

        influence_text = ", ".join(
            f"{key}={value}"
            for key, value in influence.items()
            if key not in ("initiative", "reaction_delay")
            and value not in (None, "")
            and not isinstance(value, (int, float))
        )
        blocks = [
            "; ".join(parts),
            f"Why this state changed: {trigger[:700]}" if trigger else "",
            f"Behavior influence: {influence_text}" if influence_text else "",
            events_block,
            f"Self-expression guidance: {narrative[:800]}" if narrative else "",
            recommendations_block,
            directives_block,
        ]
        return "\n".join(block for block in blocks if block)

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

        # The assistant must know when it has no eyes right now, not guess.
        attachments_info = visual_context.get("attachments") or {}
        if attachments_info.get("unavailable"):
            count = int(attachments_info.get("count") or 0) or 1
            reason = str(attachments_info.get("reason") or "vision is unavailable").strip()
            lines.append(
                f"The user attached {count} image(s), but your vision could not look at them ({reason}). "
                "You do not know what is in them: say so honestly instead of guessing."
            )

        screen_info = visual_context.get("screen") or {}
        screen_description = (screen_info.get("description") or "").strip()
        if screen_description:
            timestamp = screen_info.get("captured_at")
            prefix = "Screen snapshot"
            if timestamp:
                prefix = f"{prefix} ({timestamp})"
            lines.append(f"{prefix}: {screen_description}")
        elif screen_info.get("unavailable"):
            reason = str(screen_info.get("reason") or "vision is unavailable").strip()
            lines.append(
                f"You were asked to look at the screen, but your vision is not available ({reason}). "
                "You cannot see the screen now: say so honestly."
            )

        return "\n".join(lines)

    def _get_environment_info(self) -> str:
        parts: List[str] = []

        # The instructor switch "include date and time" decides whether the clock
        # enters the scope at all. The clock is the owner's: PAI lives with the
        # owner, and guests chat on the owner's settings.
        if bool(
            config_service.get_config_value(
                "decision_layer.instructor.include_datetime", True
            )
        ):
            now, zone_label = self._clock_now()
            parts.extend(
                [
                    f"Date: {now.strftime('%d %B %Y')}",
                    f"Time: {now.strftime('%H:%M:%S')}",
                    f"Timezone: {zone_label}",
                ]
            )

        location = config_service.get_config_value("location", "unknown")
        coordinates = config_service.get_config_value("coordinates", None)

        if location and location != "unknown":
            parts.append(f"Location: {location}")

        if coordinates:
            parts.append(f"Coordinates: {coordinates}")

        return "\n".join(parts)

    @staticmethod
    def _clock_now() -> tuple[datetime, str]:
        """Now in the owner's timezone; the server's local time when unknown."""
        from modules.system.user import resolve_owner_timezone

        zone_name = resolve_owner_timezone()
        if zone_name:
            return datetime.now(ZoneInfo(zone_name)), zone_name
        local_now = datetime.now().astimezone()
        return local_now, str(local_now.tzinfo or "server local time")

    def _build_environment_tool_content(self) -> str:
        return self._get_environment_info()

    @staticmethod
    def _memory_module_state(memory_context: Dict[str, Any]) -> str:
        status = str(memory_context.get("memory_status") or "").strip().lower()
        return _MEMORY_STATES.get(status, MODULE_EMPTY)

    @staticmethod
    def _lore_state(memory_context: Dict[str, Any], memory_state: str) -> Optional[str]:
        """None when the lorebook was not searched and there is nothing to say."""
        if memory_state == MODULE_DISABLED:
            return MODULE_DISABLED
        if memory_state == MODULE_FAILED:
            # The memory failure block already says the lookup did not run.
            return None
        stated = str(memory_context.get("lore_status") or "").strip().lower()
        if stated in {MODULE_OK, MODULE_EMPTY, MODULE_FAILED}:
            return stated
        lore_matches = memory_context.get("lore_matches")
        if isinstance(lore_matches, list) and any(str(item or "").strip() for item in lore_matches):
            return MODULE_OK
        if "lore_matches" in memory_context:
            return MODULE_EMPTY
        return None

    @staticmethod
    def _exclude_disabled_modules() -> bool:
        return bool(
            config_service.get_config_value(
                "decision_layer.instructor.exclude_disabled_modules", True
            )
        )

    @staticmethod
    def _actor_is_owner(user_message: Optional[Dict[str, Any]]) -> bool:
        try:
            from core.interaction import resolve_interaction_policy

            policy = resolve_interaction_policy((user_message or {}).get("actor_user_uuid"))
            return policy.actor_role == "owner"
        except Exception:
            return False

    @staticmethod
    def _failure_block(
        module_label: str, error: Any, user_message: Optional[Dict[str, Any]]
    ) -> str:
        if Instructor._actor_is_owner(user_message):
            detail = " ".join(str(error or "unknown error").split())[:300]
            return (
                f"[ERROR]: the {module_label} failed: {detail}. "
                "Tell the user you tried to use it and it fails with this error, "
                "so they can check it."
            )
        # A guest gets no details: an error can carry paths and internals of the
        # owner's machine. The wording is a placeholder.
        return (
            f"[ERROR]: the {module_label} is not working right now. "
            "Tell the user only that something went wrong, without any details."
        )

    def _build_diary_tool_content(self) -> str:
        """§3.9-bis-retrieval: recent diary days as generation context.

        Reads the nightly diary (narrative + self_reflection + mood) for the
        active character and renders the freshest N entries, newest first.
        Pure SQLite read — no LLM calls. Returns '' when disabled, when the
        diary is empty, or on any error (context building must never break
        a turn).
        """
        try:
            if not bool(
                config_service.get_config_value("memory.diary.context.enabled", True)
            ):
                return ""

            days = int(
                config_service.get_config_value("memory.diary.context.days", 7) or 7
            )
            max_entries = int(
                config_service.get_config_value("memory.diary.context.max_entries", 3)
                or 3
            )
            max_chars = int(
                config_service.get_config_value(
                    "memory.diary.context.max_chars_per_entry", 600
                )
                or 600
            )

            from modules.memory.diary import list_daily_activity_entries
            from modules.system import character as character_module
            from modules.system.service import get_active_character_name

            char_name = get_active_character_name(default="default_waifu")
            character = character_module.get_or_create_character(char_name)
            entries = list_daily_activity_entries(
                character_id=character.id,
                days=max(1, days),
            )
            if not entries:
                return ""

            lines: List[str] = [
                "Your private diary — the most recent days. Use it for continuity "
                "(what happened, how you felt, what you noticed about yourself). "
                "Do not quote it verbatim unless asked."
            ]
            for entry in entries[: max(1, max_entries)]:
                payload = entry.payload if isinstance(entry.payload, dict) else {}
                narrative = str(payload.get("narrative") or "").strip()
                reflection = str(payload.get("self_reflection") or "").strip()
                body = narrative or str(entry.summary or "").strip()
                if not body and not reflection:
                    continue
                block: List[str] = [f"[{entry.day}] mood: {entry.mood or 'neutral'}"]
                if body:
                    block.append(body[:max_chars])
                if reflection:
                    block.append(f"Self-reflection: {reflection[:max_chars]}")
                lines.append("\n".join(block))

            if len(lines) <= 1:
                return ""
            return "\n\n".join(lines)
        except Exception as exc:
            log_audit_entry(
                "instructor_diary_context_failed",
                "[Instructor] Diary context block failed (non-fatal).",
                AuditStatus.WARNING,
                details={"error": str(exc)},
            )
            return ""

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

        context = memory_context or {}
        memory_status = str(context.get("memory_status") or "").strip().lower()
        exclude_disabled = self._exclude_disabled_modules()

        memory_state = self._memory_module_state(context)
        if memory_state == MODULE_FAILED:
            memory_info = self._failure_block(
                "memory module", context.get("memory_error"), user_message
            )
        elif memory_state == MODULE_DISABLED:
            memory_info = "" if exclude_disabled else "[OK]: memory module is disabled."
        else:
            memory_info = self._build_memory_tool_content(context).strip()
        if memory_info:
            dynamic_messages.append(
                {
                    "role": "tool",
                    "name": "memory.lookup",
                    "content": memory_info,
                }
            )

        lore_state = self._lore_state(context, memory_state)
        knowledge_info = ""
        if lore_state == MODULE_OK:
            knowledge_info = self._build_knowledge_tool_content(context).strip()
        elif lore_state == MODULE_EMPTY:
            knowledge_info = NO_LOREBOOK_ENTRIES
        elif lore_state == MODULE_FAILED:
            knowledge_info = self._failure_block(
                "lorebook", context.get("lore_error"), user_message
            )
        elif lore_state == MODULE_DISABLED and not exclude_disabled:
            knowledge_info = "[OK]: lorebook is disabled together with the memory module."
        if knowledge_info:
            dynamic_messages.append(
                {
                    "role": "tool",
                    "name": "knowledge.lorebook",
                    "content": knowledge_info,
                }
            )

        # §7.3.3: chunks retrieved from indexed knowledge collections, with
        # file-level sources. Prepared by the decision layer (rides on
        # memory_context to avoid widening every caller signature).
        knowledge_documents = (memory_context or {}).get("knowledge_documents")
        if isinstance(knowledge_documents, dict):
            documents_content = str(knowledge_documents.get("content") or "").strip()
            if documents_content:
                dynamic_messages.append(
                    {
                        "role": "tool",
                        "name": "knowledge.documents",
                        "content": (
                            "Fragments from the user's indexed documents relevant to the "
                            "current request. Each fragment is prefixed with its source "
                            "file in brackets — mention the source naturally when you "
                            "rely on it:\n" + documents_content
                        ),
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

        # §3.9-bis-retrieval: recent diary days (narrative + self_reflection).
        # Pure DB read, gated by memory.diary.context.enabled.
        diary_info = self._build_diary_tool_content().strip()
        if diary_info:
            dynamic_messages.append(
                {
                    "role": "tool",
                    "name": "diary.recent",
                    "content": diary_info,
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
