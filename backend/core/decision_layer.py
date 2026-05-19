import asyncio
import hashlib
import json
import time
from typing import Dict, Any, List, Optional, Tuple
from pprint import pprint

from modules.moral_matrix import MoralMatrixModule
from core.instructor import Instructor
from modules.vision import VisualModule
from modules.analyzer.service import AnalyzerModule
from modules.tts.service import speak_line
from modules.memory import MemoryContextResult, MemoryModule

from constants.indicators import (
    VISION_INDICATORS,
    VISION_KEYWORDS,
    DEEP_MEMORY_THEMES,
    SEARCH_THEMES,
    SUPPORT_EMOTIONS,
    CREATIVE_THEMES,
)
from constants.prompts import DECISION_LAYER_ORCHESTRATOR_PROMPT

from modules.system import config as config_service
from modules.system.logger import log_audit_entry, AuditStatus
from modules.system.runtime_profile import should_release_resources
from core.interaction import resolve_interaction_policy
from core.input_envelope import InputEnvelope
from core.task_layer import (
    TASK_COMPLETE,
    TASK_SKIPPED,
    TASK_UNAVAILABLE,
    TaskPlan,
)
from modules.ollama import client as ollama_client


class DecisionLayer:
    """
    Decision layer orchestrates message processing pipeline:
    - Runs cognitive analysis
    - Makes routing decisions
    - Collects memory/lore context
    - Evaluates moral state
    - Builds final system prompt
    """

    def __init__(self):
        self._memory_module: Optional[MemoryModule] = None
        self._memory_module_failed: bool = False
        self.moral_matrix = MoralMatrixModule()
        self.instructor = Instructor()
        self.analyzer = AnalyzerModule()
        self._visual_module: Optional[VisualModule] = None
        self._visual_module_failed: bool = False
        # Логирование инициализации
        print("[DecisionLayer] Модуль DecisionLayer инициализирован.")
        log_audit_entry(
            "decision_layer_init",
            "[DecisionLayer] Модуль DecisionLayer инициализирован.",
            AuditStatus.INFO,
        )

        print("[DecisionLayer] Подключаем общий TTS сервис.")
        log_audit_entry(
            "decision_layer_tts_service_linked",
            "[DecisionLayer] DecisionLayer использует общий TTS сервис.",
            AuditStatus.INFO,
        )

    def _is_deep_memory_enabled(self) -> bool:
        direct_flag = config_service.get_config_value("memory.deep_memory_enabled", None)
        if isinstance(direct_flag, bool):
            return direct_flag
        rag_module_enabled = bool(config_service.get_config_value("modules.rag", True))
        rag_enabled = bool(config_service.get_config_value("rag.enabled", True))
        return rag_module_enabled and rag_enabled

    def _get_memory_module(self) -> Optional[MemoryModule]:
        if self._memory_module_failed:
            return None
        if self._memory_module is None:
            try:
                self._memory_module = MemoryModule()
                log_audit_entry(
                    "decision_layer_memory_module_init",
                    "[DecisionLayer] MemoryModule initialized.",
                    AuditStatus.INFO,
                )
            except Exception as exc:
                log_audit_entry(
                    "decision_layer_memory_init_error",
                    "[DecisionLayer] Failed to initialize MemoryModule.",
                    AuditStatus.ERROR,
                    details={"error": str(exc)},
                )
                self._memory_module_failed = True
                self._memory_module = None
        return self._memory_module

    @staticmethod
    def _empty_memory_context(status: str = "disabled") -> Dict[str, Any]:
        return {
            "key_facts": [],
            "session_length": 0,
            "memory_status": status,
            "matches": [],
            "lore_matches": [],
            "lore_block": "",
            "count": 0,
            "recent_history": [],
            "conversation_state": {
                "last_message_at": None,
                "hours_since_last_message": None,
                "inactivity_bucket": "unknown",
                "last_topic": "",
                "recent_tone_summary": "neutral",
            },
        }

    @staticmethod
    def _preview_text(value: Any, limit: int = 320) -> str:
        text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "..."

    @classmethod
    def _summarize_media_for_console(
        cls, media_payload: Optional[List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for index, item in enumerate(media_payload or [], start=1):
            if not isinstance(item, dict):
                continue
            mime_type = (
                item.get("mimeType")
                or item.get("mime_type")
                or item.get("contentType")
                or item.get("type")
                or ""
            )
            category = item.get("category") or item.get("mediaType") or ""
            items.append(
                {
                    "index": index,
                    "name": cls._preview_text(
                        item.get("name") or item.get("filename") or item.get("id") or "",
                        80,
                    ),
                    "category": category,
                    "mime": mime_type,
                    "size": item.get("size"),
                    "has_data": bool(item.get("data")),
                    "description": cls._preview_text(
                        item.get("description") or item.get("summary") or "",
                        140,
                    ),
                }
            )
        return items

    @classmethod
    def _summarize_message_for_console(
        cls,
        message: Dict[str, Any],
        raw_media_payload: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        content = message.get("content") or ""
        media_payload = raw_media_payload
        if media_payload is None:
            media_payload = message.get("media") or []
        return {
            "id": message.get("id"),
            "text": cls._preview_text(content),
            "text_length": len(str(content)),
            "media_count": len(media_payload or []),
            "media": cls._summarize_media_for_console(media_payload),
            "history_count": len(message.get("history") or []),
        }

    @classmethod
    def _console_log(cls, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        prefix = "[Decision Layer]"
        if not details:
            print(f"{prefix}: {message}")
            return
        try:
            payload = json.dumps(details, ensure_ascii=False, default=str)
        except Exception:
            payload = str(details)
        if len(payload) > 1800:
            payload = payload[:1800].rstrip() + "..."
        print(f"{prefix}: {message} | {payload}")

    @classmethod
    def _summarize_analysis_for_console(cls, analysis: Dict[str, Any]) -> Dict[str, Any]:
        input_analysis = (analysis or {}).get("input_analysis") or {}
        intent = input_analysis.get("intent_analysis") or {}
        tone = input_analysis.get("emotional_tone") or {}
        risk = (analysis or {}).get("risk_assessment") or {}
        guidance = (analysis or {}).get("response_guidance") or {}
        return {
            "category": input_analysis.get("content_category"),
            "intent": intent.get("primary_intent"),
            "context_dependency": intent.get("context_dependency"),
            "emotion": tone.get("primary"),
            "emotion_intensity": tone.get("intensity"),
            "themes": (input_analysis.get("dominant_themes") or [])[:8],
            "risk_level": risk.get("risk_level"),
            "flags": (risk.get("content_flags") or [])[:8],
            "routing": guidance.get("routing_recommendation"),
            "orchestration": (analysis or {}).get("orchestration") or {},
        }

    @staticmethod
    def _analysis_orchestration(analysis: Dict[str, Any]) -> Dict[str, Any]:
        orchestration = (analysis or {}).get("orchestration")
        return orchestration if isinstance(orchestration, dict) else {}

    def _build_task_plan(
        self,
        analysis: Dict[str, Any],
        decisions: Dict[str, bool],
        image_generation_decision: Dict[str, Any],
        media_payload: Optional[List[Dict[str, Any]]] = None,
    ) -> TaskPlan:
        orchestration = self._analysis_orchestration(analysis)
        plan = TaskPlan()

        plan.add("analysis", "analysis", "analyze_input", "normalize_intent_and_context")
        plan.add("decision", "decision", "build_task_plan", "route_required_modules")
        if decisions.get("needs_deep_memory") or orchestration.get("need_memory"):
            plan.add("memory", "memory", "collect_context", "analysis_requested_memory")
        else:
            plan.add("memory", "memory", "collect_context", "memory_not_required")
        if bool(config_service.get_config_value("moral.enabled", True)):
            plan.add("moral_matrix", "moral", "evaluate_state", "always_evaluate_before_reply")
        else:
            plan.add("moral_matrix", "moral", "evaluate_state", "moral_disabled")
        if decisions.get("needs_vision") or orchestration.get("need_vision"):
            plan.add("vision", "vision", "describe_visual_context", "visual_context_required")
        if image_generation_decision.get("enabled") or orchestration.get("need_image_gen"):
            plan.add("image_prompt", "image_prompt", "build_generation_prompt", image_generation_decision.get("reason", "image_requested"))
            plan.add("image_generation", "image_generation", "generate_image", "image_prompt_ready")
            plan.add("image_vision", "image_vision", "describe_generated_image", "generated_image_needs_description")
        plan.add("instructor", "prompt", "build_final_instructions", "prepare_final_llm_context")
        plan.add("llm", "generation", "generate_reply", "final_user_response")
        return plan

    def _build_module_tasks(
        self,
        analysis: Dict[str, Any],
        decisions: Dict[str, bool],
        image_generation_decision: Dict[str, Any],
        media_payload: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        return self._build_task_plan(
            analysis,
            decisions,
            image_generation_decision,
            media_payload,
        ).to_list()

    @classmethod
    def _summarize_memory_meta_for_console(
        cls, memory_context: Dict[str, Any], memory_meta: Dict[str, Any]
    ) -> Dict[str, Any]:
        context = memory_context or {}
        meta = memory_meta or {}
        return {
            "status": context.get("memory_status"),
            "recent_history": len(context.get("recent_history") or []),
            "matches": len(context.get("matches") or []),
            "lore_count": context.get("count", 0),
            "bypassed": bool(meta.get("memory_bypassed")),
            "reason": meta.get("reason"),
        }

    # --------------------------------------------------------------------- #
    #                     PUBLIC API
    # --------------------------------------------------------------------- #
    async def process_message(
        self, user_message: Dict[str, Any], websocket=None, trace_hook=None
    ) -> Dict[str, Any]:
        """
        Main entry point for message processing pipeline.
        """
        async def _trace(
            stage: str,
            state: str,
            *,
            details: Optional[Dict[str, Any]] = None,
            started_at: Optional[float] = None,
        ) -> None:
            if trace_hook is None:
                return
            payload: Dict[str, Any] = {
                "stage": stage,
                "state": state,
            }
            if started_at is not None:
                payload["elapsed_ms"] = round((time.perf_counter() - started_at) * 1000, 2)
            if details:
                payload["details"] = details
            await trace_hook(payload)

        input_envelope = InputEnvelope.from_message(user_message)
        normalized_user_message = input_envelope.to_message()
        safe_user_message, raw_media_payload = self._prepare_user_payload(
            normalized_user_message
        )
        interaction_policy = resolve_interaction_policy(
            safe_user_message.get("actor_user_uuid")
        )

        self._console_log(
            "Поступило сообщение.",
            self._summarize_message_for_console(safe_user_message, raw_media_payload),
        )
        print("[DecisionLayer] Запуск обработки сообщения.")
        log_audit_entry(
            "decision_layer_start",
            "[DecisionLayer] Начало обработки сообщения.",
            AuditStatus.INFO,
            details={
                "message_id": safe_user_message.get("id"),
                "input_envelope": input_envelope.to_audit_dict(),
                "media_count": len(raw_media_payload),
                "has_media": bool(raw_media_payload),
                "content_length": len(safe_user_message.get("content") or ""),
                "actor_role": interaction_policy.actor_role,
            },
        )

        # --------------------------------------------------------------- #
        # 1️⃣  Cognitive analysis
        # --------------------------------------------------------------- #
        analysis_started = time.perf_counter()
        await _trace(
            "analysis",
            "start",
            details={"message_id": safe_user_message.get("id")},
        )
        self._console_log(
            "Запрашиваю анализ интента.",
            {
                "message_id": safe_user_message.get("id"),
                "text": self._preview_text(safe_user_message.get("content")),
                "media_count": len(raw_media_payload),
            },
        )
        print("[DecisionLayer] Запрос анализа данных анализатором.")
        log_audit_entry(
            "decision_layer_analyzer_request",
            "[DecisionLayer] Запрос на анализ данных.",
            AuditStatus.INFO,
            details={
                "message_id": safe_user_message.get("id"),
                "media": safe_user_message.get("media"),
            },
        )
        if bool(config_service.get_config_value("analyzer.enabled", True)):
            analysis_payload = await self.analyzer.analyze(safe_user_message)
        else:
            metadata = AnalyzerModule._build_default_metadata(
                safe_user_message.get("content", "")
            )
            metadata = AnalyzerModule._normalize_metadata(
                metadata,
                safe_user_message.get("content", ""),
                {
                    "message_id": safe_user_message.get("id"),
                    "timestamp": safe_user_message.get("timestamp"),
                    "message_type": safe_user_message.get("message_type", "user_message"),
                    "source": safe_user_message.get("source"),
                    "media_count": len(raw_media_payload),
                },
            )
            metadata["disabled"] = True
            analysis_payload = {
                "metadata": metadata,
                "provider": "disabled",
                "errors": ["analyzer_disabled"],
                "message_meta": {
                    "message_id": safe_user_message.get("id"),
                    "media_count": len(raw_media_payload),
                },
            }
            self._console_log("Analyzer отключен, использую минимальную meta.")
        await _trace(
            "analysis",
            "end",
            started_at=analysis_started,
            details={"has_metadata": bool(analysis_payload.get("metadata"))},
        )
        print("[DecisionLayer] Анализ завершен.")
        analysis_result = analysis_payload.get("metadata", {})
        image_generation_decision = self._decide_main_chat_image_generation(
            safe_user_message,
            analysis_result,
        )
        self._console_log(
            "Анализ получен.",
            {
                "meta": self._summarize_analysis_for_console(analysis_result),
                "image_generation": image_generation_decision,
                "message_meta": analysis_payload.get("message_meta", {}),
            },
        )
        log_audit_entry(
            "decision_layer_analyzer_response",
            "[DecisionLayer] Анализ завершен.",
            AuditStatus.INFO,
            details={"analysis_payload": analysis_payload},
        )

        # --------------------------------------------------------------- #
        # 2️⃣  Decision‑making
        # --------------------------------------------------------------- #
        decision_started = time.perf_counter()
        await _trace("decision", "start")
        self._console_log(
            "Запрашиваю routing-решение.",
            {
                "mode": config_service.get_config_value("decision_layer.mode", "system"),
                "analysis_keys": list((analysis_result or {}).keys()),
            },
        )
        print("[DecisionLayer] Принятие решений на основе анализа.")
        log_audit_entry(
            "decision_layer_decision_request",
            "[DecisionLayer] Принятие решений на основе анализа.",
            AuditStatus.INFO,
            details={"analysis_result": analysis_result},
        )
        decisions = await self._make_decisions(analysis_result, safe_user_message)
        visual_signal = self._detect_visual_hard_signal(
            safe_user_message, raw_media_payload
        )
        if visual_signal.get("needs_vision"):
            decisions["needs_vision"] = True
            self._console_log(
                "Visual hard-signal detected.",
                {
                    "reason": visual_signal.get("reason"),
                    "sources": visual_signal.get("sources"),
                    "media_count": len(raw_media_payload),
                },
            )
            log_audit_entry(
                "decision_layer_visual_hard_signal",
                "[DecisionLayer] Visual hard-signal forced vision routing.",
                AuditStatus.INFO,
                details=visual_signal,
            )
        task_plan = self._build_task_plan(
            analysis_result,
            decisions,
            image_generation_decision,
            raw_media_payload,
        )
        task_plan.mark(
            "analysis",
            TASK_COMPLETE,
            details={
                "provider": analysis_payload.get("provider"),
                "disabled": bool((analysis_result or {}).get("disabled")),
                "errors": analysis_payload.get("errors") or [],
            },
        )
        task_plan.mark("decision", TASK_COMPLETE, details={"decisions": decisions})
        module_tasks = task_plan.to_list()
        await _trace(
            "decision",
            "end",
            started_at=decision_started,
            details={"decisions": decisions, "module_tasks": module_tasks},
        )
        print("[DecisionLayer] Решения приняты.")
        self._console_log("Routing-решение получено.", {"decisions": decisions})
        await _trace(
            "queue",
            "end",
            details={"tasks": module_tasks, "count": len(module_tasks)},
        )
        self._console_log("Очередь модулей собрана.", {"tasks": module_tasks})
        log_audit_entry(
            "decision_layer_decisions_made",
            "[DecisionLayer] Решения приняты.",
            AuditStatus.INFO,
            details={"decisions": decisions, "module_tasks": module_tasks},
        )

        # --------------------------------------------------------------- #
        # 3️⃣  Gather context from memory and lore
        # --------------------------------------------------------------- #
        memory_started = time.perf_counter()
        await _trace("memory", "start")
        memory_enabled = self._is_deep_memory_enabled()
        self._console_log(
            "Проверяю необходимость памяти.",
            {
                "enabled": memory_enabled,
                "needs_deep_memory": bool(decisions.get("needs_deep_memory")),
            },
        )
        print("[DecisionLayer] Сбор контекста из памяти и легенд.")
        log_audit_entry(
            "decision_layer_memory_context_request",
            "[DecisionLayer] Запрос на сбор контекста из памяти.",
            AuditStatus.INFO,
            details={"user_message": safe_user_message},
        )
        if memory_enabled:
            memory_module = self._get_memory_module()
            if memory_module is not None:
                memory_result = await memory_module.collect_context(
                    safe_user_message.get("content", ""), safe_user_message
                )
                task_plan.mark(
                    "memory",
                    TASK_COMPLETE,
                    details={
                        "status": (memory_result.context or {}).get("memory_status"),
                        "matches": len((memory_result.context or {}).get("matches") or []),
                    },
                )
            else:
                memory_result = MemoryContextResult(
                    context=self._empty_memory_context(status="module_unavailable"),
                    meta={"memory_bypassed": True, "reason": "module_unavailable"},
                )
                task_plan.mark(
                    "memory",
                    TASK_UNAVAILABLE,
                    reason="module_unavailable",
                )
        else:
            memory_result = MemoryContextResult(
                context=self._empty_memory_context(status="disabled"),
                meta={"memory_bypassed": True, "reason": "disabled_by_config"},
            )
            task_plan.mark("memory", TASK_SKIPPED, reason="disabled_by_config")
            log_audit_entry(
                "decision_layer_memory_context_skipped",
                "[DecisionLayer] MemoryModule skipped by configuration.",
                AuditStatus.INFO,
                details={
                    "enabled": False,
                    "needs_deep_memory": bool(decisions.get("needs_deep_memory")),
                },
            )
        await _trace(
            "memory",
            "end",
            started_at=memory_started,
            details={
                "history_count": len((memory_result.context or {}).get("recent_history") or []),
                "lore_count": (memory_result.context or {}).get("count", 0),
            },
        )
        print("[DecisionLayer] Контекст из памяти собран.")
        self._console_log(
            "Контекст памяти получен.",
            self._summarize_memory_meta_for_console(
                memory_result.context or {},
                memory_result.meta or {},
            ),
        )
        log_audit_entry(
            "decision_layer_memory_context_collected",
            "[DecisionLayer] Контекст из памяти собран.",
            AuditStatus.INFO,
            details={
                "memory_result": {
                    "context": memory_result.context,
                    "meta": memory_result.meta,
                }
            },
        )
        memory_context = memory_result.context
        memory_meta = memory_result.meta
        lore_context = {
            "lore_matches": memory_context.get("lore_matches", []),
            "lore_block": memory_context.get("lore_block"),
            "count": memory_context.get("count"),
        }

        existing_history = safe_user_message.get("history")
        if not isinstance(existing_history, list):
            existing_history = []
        history_preview = memory_context.get("recent_history") or []
        sanitized_history = self._sanitize_history_entries(history_preview)
        preserve_incoming_history = bool(safe_user_message.get("preserve_history"))
        if preserve_incoming_history:
            safe_user_message["history"] = existing_history
            if existing_history:
                log_audit_entry(
                    "decision_layer_history_preserved_for_control_action",
                    "[DecisionLayer] Incoming transport history preserved for control action.",
                    AuditStatus.INFO,
                    details={"messages_preserved": len(existing_history)},
                )
        elif sanitized_history:
            safe_user_message["history"] = sanitized_history
            history_meta = memory_meta.get("history_preview", {}) if isinstance(memory_meta, dict) else {}
            history_limit_config = history_meta.get("limit", len(history_preview))
            log_audit_entry(
                "decision_layer_history_attached",
                "[DecisionLayer] История сообщений прикреплена к пользовательскому запросу.",
                AuditStatus.INFO,
                details={
                    "messages_attached": len(sanitized_history),
                    "history_limit": history_limit_config,
                },
            )
        else:
            safe_user_message["history"] = existing_history
            if existing_history:
                log_audit_entry(
                    "decision_layer_history_preserved",
                    "[DecisionLayer] Memory history is empty, keeping incoming transport history.",
                    AuditStatus.INFO,
                    details={"messages_preserved": len(existing_history)},
                )

        # --------------------------------------------------------------- #
        # 5️⃣  Evaluate moral state
        # --------------------------------------------------------------- #
        message_meta = analysis_payload.get("message_meta", {})
        if bool(config_service.get_config_value("moral.enabled", True)):
            moral_started = time.perf_counter()
            await _trace("moral", "start")
            self._console_log("Запрашиваю состояние Moral Matrix.")
            print("[DecisionLayer] Оценка морального состояния.")
            log_audit_entry(
                "decision_layer_moral_state_request",
                "[DecisionLayer] Запрос на оценку морального состояния.",
                AuditStatus.INFO,
            )
            moral_state = await self.moral_matrix.evaluate(
                analysis_result,
                memory_context,
                memory_meta,
                message_meta=message_meta,
                user_message=safe_user_message,
                persist_state=interaction_policy.can_affect_moral,
            )
            task_plan.mark(
                "moral_matrix",
                TASK_COMPLETE,
                details={
                    "emotion": moral_state.get("current_emotion"),
                    "intensity": moral_state.get("intensity"),
                    "persisted": interaction_policy.can_affect_moral,
                },
            )
            await _trace(
                "moral",
                "end",
                started_at=moral_started,
                details={"intensity": moral_state.get("intensity")},
            )
            print("[DecisionLayer] Моральное состояние оценено.")
            self._console_log(
                "Состояние Moral Matrix получено.",
                {
                    "emotion": moral_state.get("current_emotion"),
                    "intensity": moral_state.get("intensity"),
                    "summary": self._preview_text(moral_state.get("summary"), 220),
                },
            )
            log_audit_entry(
                "decision_layer_moral_state_evaluated",
                "[DecisionLayer] Моральное состояние оценено.",
                AuditStatus.INFO,
                details={"moral_state": moral_state},
            )
        else:
            moral_state = {}
            task_plan.mark("moral_matrix", TASK_SKIPPED, reason="moral_disabled")
            await _trace("moral", "skipped", details={"reason": "moral_disabled"})
            self._console_log("Moral Matrix отключена, состояние не добавляется.")

        # --------------------------------------------------------------- #
        # 5️⃣  Gather visual context when available
        # --------------------------------------------------------------- #
        vision_started = time.perf_counter()
        await _trace("vision", "start")
        self._console_log(
            "Проверяю визуальный контекст.",
            {
                "needs_vision": bool(decisions.get("needs_vision")),
                "media_count": len(raw_media_payload),
            },
        )
        print("[DecisionLayer] Сбор визуального контекста.")
        log_audit_entry(
            "decision_layer_visual_context_request",
            "[DecisionLayer] Запрос на сбор визуального контекста.",
            AuditStatus.INFO,
            details={
                "media": safe_user_message.get("media"),
                "decisions": decisions,
            },
        )
        visual_context = await self._collect_visual_context(
            raw_media_payload, decisions
        )
        if task_plan.first("vision"):
            if visual_context:
                task_plan.mark(
                    "vision",
                    TASK_COMPLETE,
                    details={
                        "has_screen": bool((visual_context or {}).get("screen")),
                        "attachments": len(
                            ((visual_context.get("attachments", {}) or {}).get("items", []))
                            if isinstance(visual_context, dict)
                            else []
                        ),
                    },
                )
            else:
                task_plan.mark("vision", TASK_SKIPPED, reason="no_visual_context")
        if raw_media_payload:
            safe_user_message["media"] = self._sanitize_media_list(raw_media_payload)
        await _trace(
            "vision",
            "end",
            started_at=vision_started,
            details={
                "has_screen": bool((visual_context or {}).get("screen")),
                "attachments": len(
                    ((visual_context.get("attachments", {}) or {}).get("items", []))
                    if isinstance(visual_context, dict)
                    else []
                ),
            },
        )
        print("[DecisionLayer] Визуальный контекст собран.")
        self._console_log(
            "Визуальный контекст получен.",
            {
                "has_screen": bool((visual_context or {}).get("screen")),
                "attachments": len(
                    ((visual_context.get("attachments", {}) or {}).get("items", []))
                    if isinstance(visual_context, dict)
                    else []
                ),
            },
        )
        log_audit_entry(
            "decision_layer_visual_context_collected",
            "[DecisionLayer] Визуальный контекст собран.",
            AuditStatus.INFO,
            details={"visual_context": visual_context},
        )

        # --------------------------------------------------------------- #
        # 6️⃣  Build final system prompt
        # --------------------------------------------------------------- #
        prompt_started = time.perf_counter()
        await _trace("prompt", "start")
        self._console_log("Запрашиваю сборку системного промпта.")
        print("[DecisionLayer] Формирование финального системного запроса.")
        log_audit_entry(
            "decision_layer_system_prompt_request",
            "[DecisionLayer] Запрос на формирование системного запроса.",
            AuditStatus.INFO,
            details={
                "analysis_result": analysis_result,
                "decisions": decisions,
                "memory_context": memory_context,
                "moral_state": moral_state,
                "visual_context": visual_context,
            },
        )
        system_prompt = await self.instructor.build_system_prompt(
            analysis_result,
            decisions,
            memory_context,
            moral_state,
            visual_context=visual_context,
        )
        task_plan.mark(
            "instructor",
            TASK_COMPLETE,
            details={"prompt_length": len(system_prompt)},
        )
        module_tasks = task_plan.to_list()
        await _trace(
            "prompt",
            "end",
            started_at=prompt_started,
            details={"prompt_length": len(system_prompt)},
        )
        prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()[:12]
        print("[DecisionLayer] Финальный системный запрос сформирован.")
        self._console_log(
            "Системный промпт собран.",
            {"prompt_length": len(system_prompt), "prompt_hash": prompt_hash},
        )
        log_audit_entry(
            "decision_layer_system_prompt_built",
            "[DecisionLayer] Финальный системный запрос сформирован.",
            AuditStatus.INFO,
            details={
                "prompt_length": len(system_prompt),
                "prompt_hash": prompt_hash,
            },
        )

        # --------------------------------------------------------------- #
        # 7️⃣  Final audit log
        # --------------------------------------------------------------- #
        print("[DecisionLayer] Обработка сообщения завершена успешно.")
        self._console_log(
            "Обработка сообщения завершена.",
            {
                "message_id": safe_user_message.get("id"),
                "decisions": decisions,
                "prompt_hash": prompt_hash,
            },
        )
        log_audit_entry(
            "decision_layer_success",
            "[DecisionLayer] Сообщение обработано успешно.",
            AuditStatus.SUCCESS,
            details={
                "decisions": decisions,
                "visual_context": {
                    "attachments": len(
                        (visual_context.get("attachments", {}) or {}).get("items", [])
                    ),
                    "has_screen": bool(visual_context.get("screen")),
                },
                "memory_meta": memory_meta,
                "moral_state": moral_state,
                "system_prompt_hash": prompt_hash,
                "interaction_policy": {
                    "actor_role": interaction_policy.actor_role,
                    "can_affect_moral": interaction_policy.can_affect_moral,
                    "can_affect_global_memory": interaction_policy.can_affect_global_memory,
                },
            },
        )

        return {
            "system_prompt": system_prompt,
            "user_message": safe_user_message,
            "raw_media": raw_media_payload,
            "input_envelope": input_envelope.to_audit_dict(),
            "decisions": decisions,
            "analysis": analysis_result,
            "analysis_details": analysis_payload,
            "moral_state": moral_state,
            "visual_context": visual_context,
            "memory_context": memory_context,
            "memory_meta": memory_meta,
            "image_generation": image_generation_decision,
            "module_tasks": module_tasks,
            "interaction_policy": {
                "actor_role": interaction_policy.actor_role,
                "can_affect_moral": interaction_policy.can_affect_moral,
                "can_affect_global_memory": interaction_policy.can_affect_global_memory,
            },
        }

    def _decide_main_chat_image_generation(
        self,
        user_message: Dict[str, Any],
        analysis_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        runtime_meta = user_message.get("runtime_meta")
        transport = runtime_meta.get("transport") if isinstance(runtime_meta, dict) else None
        transport_name = (
            str((transport or {}).get("name") or "main_chat").strip().lower()
            if isinstance(transport, dict)
            else "main_chat"
        )
        if transport_name != "main_chat":
            self._console_log(
                "Выбор генерации картинки в ответе - нет.",
                {
                    "reason": "transport_not_main_chat",
                    "transport": transport_name,
                },
            )
            return {
                "enabled": False,
                "reason": "transport_not_main_chat",
                "source": "analyzer",
            }

        response_guidance = (analysis_result or {}).get("response_guidance") or {}
        image_generation = (
            response_guidance.get("image_generation")
            if isinstance(response_guidance, dict)
            else {}
        )
        if not isinstance(image_generation, dict):
            image_generation = {}

        orchestration = self._analysis_orchestration(analysis_result)
        feature_flags = user_message.get("feature_flags")
        explicit_image_generation = bool(
            isinstance(feature_flags, dict)
            and feature_flags.get("image_generation")
        )
        enabled = (
            explicit_image_generation
            or bool(image_generation.get("needed"))
            or bool(orchestration.get("need_image_gen"))
        )
        reason = str(
            image_generation.get("reason")
            or (
                "explicit_chat_image_generation"
                if explicit_image_generation
                else
                "analyzer_requested_visual_attachment"
                if enabled
                else "analyzer_no_visual_attachment_needed"
            )
        )
        self._console_log(
            f"Выбор генерации картинки в ответе - {'да' if enabled else 'нет'}.",
            {
                "source": image_generation.get("source", "analyzer"),
                "reason": reason,
                "style_hint": image_generation.get("style_hint", ""),
                "category": ((analysis_result or {}).get("input_analysis") or {}).get("content_category"),
                "explicit_image_generation": explicit_image_generation,
            },
        )
        if enabled:
            self._console_log("Запланирована генерация картинки до финального ответа.")
        return {
            "enabled": enabled,
            "reason": reason,
            "style_hint": image_generation.get("style_hint", ""),
            "source": "feature_flag" if explicit_image_generation else image_generation.get("source", "analyzer"),
        }

    def handle_response(self, text: str) -> None:
        if not text:
            return
        print("[DecisionLayer] Обработка ответа для озвучки.")
        log_audit_entry(
            "decision_layer_tts_request",
            "[DecisionLayer] Запрос на озвучку текста.",
            AuditStatus.INFO,
            details={"text": text},
        )
        if not config_service.get_config_value("voice.enabled", False):
            print("[DecisionLayer] Озвучка отключена в конфигурации.")
            log_audit_entry(
                "decision_layer_tts_disabled",
                "[DecisionLayer] Озвучка отключена в конфигурации.",
                AuditStatus.INFO,
            )
            return

        try:
            print("[DecisionLayer] Передаём текст в общий TTS сервис.")
            success = speak_line(text)
            log_audit_entry(
                "decision_layer_tts_success",
                "[DecisionLayer] Текст успешно передан в очередь сервису.",
                AuditStatus.INFO if success else AuditStatus.WARNING,
                details={
                    "queued": success,
                    "text_length": len(text),
                },
            )
            print(
                "[DecisionLayer] Текст отправлен в очередь для озвучки."
                if success
                else "[DecisionLayer] Общий TTS сервис отклонил запрос."
            )
        except Exception as exc:
            print(f"[DecisionLayer] Ошибка при озвучке: {exc}")
            log_audit_entry(
                "decision_layer_tts_error",
                "[DecisionLayer] Ошибка при озвучке текста.",
                AuditStatus.ERROR,
                details={"error": str(exc)},
            )

    # --------------------------------------------------------------------- #
    #                     PRIVATE HELPERS
    # --------------------------------------------------------------------- #
    @classmethod
    def _prepare_user_payload(
        cls, user_message: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Return a sanitized representation of the incoming message alongside
        a copy of raw media payload that may still contain binary/base64 data.
        """
        if not isinstance(user_message, dict):
            return {}, []

        media_payload: List[Dict[str, Any]] = []
        for item in user_message.get("media") or []:
            if isinstance(item, dict):
                media_payload.append(dict(item))

        message_copy: Dict[str, Any] = {k: v for k, v in user_message.items()}
        message_copy["media"] = media_payload

        history = message_copy.get("history")
        if isinstance(history, list):
            history_copy: List[Dict[str, Any]] = []
            for entry in history:
                if not isinstance(entry, dict):
                    history_copy.append(entry)
                    continue
                entry_copy = {k: v for k, v in entry.items()}
                entry_media = entry_copy.get("media")
                if isinstance(entry_media, list):
                    entry_copy["media"] = [
                        dict(media_item)
                        for media_item in entry_media
                        if isinstance(media_item, dict)
                    ]
                history_copy.append(entry_copy)
            message_copy["history"] = history_copy

        safe_message = cls._sanitize_message_payload(message_copy)
        return safe_message, media_payload

    @classmethod
    def _sanitize_message_payload(cls, message: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(message, dict):
            return {}

        sanitized: Dict[str, Any] = {
            k: v for k, v in message.items() if k not in {"media", "history"}
        }
        sanitized["media"] = cls._sanitize_media_list(message.get("media") or [])

        history = message.get("history")
        if isinstance(history, list):
            sanitized_history: List[Dict[str, Any]] = []
            for entry in history:
                if isinstance(entry, dict):
                    entry_sanitized = {
                        k: v for k, v in entry.items() if k not in {"media"}
                    }
                    entry_sanitized["media"] = cls._sanitize_media_list(
                        entry.get("media") or []
                    )
                    sanitized_history.append(entry_sanitized)
                else:
                    sanitized_history.append(entry)
            sanitized["history"] = sanitized_history

        return sanitized

    @classmethod
    def _sanitize_media_list(
        cls, media_list: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        sanitized: List[Dict[str, Any]] = []
        for item in media_list or []:
            cleaned = cls._sanitize_media_item(item)
            if cleaned:
                sanitized.append(cleaned)
        return sanitized

    @classmethod
    def _sanitize_history_entries(
        cls, history: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        sanitized: List[Dict[str, Any]] = []
        for entry in history or []:
            if not isinstance(entry, dict):
                continue
            role = str(entry.get("role") or "").strip().lower()
            if role not in {"user", "assistant"}:
                continue
            cleaned: Dict[str, Any] = {
                "role": role,
                "content": entry.get("content"),
            }
            if entry.get("id"):
                cleaned["id"] = entry.get("id")
            if entry.get("timestamp"):
                cleaned["timestamp"] = entry.get("timestamp")
            media_items = entry.get("media")
            if isinstance(media_items, list) and media_items:
                cleaned_media = cls._sanitize_media_list(media_items)
                if cleaned_media:
                    cleaned["media"] = cleaned_media
            sanitized.append(cleaned)
        return sanitized

    @staticmethod
    def _sanitize_media_item(media: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(media, dict):
            return {}

        sanitized: Dict[str, Any] = {}

        def _assign(key: str, value: Any) -> None:
            if value is None:
                return
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    return
            sanitized[key] = value

        _assign("id", media.get("id"))
        _assign("name", media.get("name") or media.get("filename"))
        _assign(
            "mimeType",
            media.get("mimeType")
            or media.get("mime_type")
            or media.get("contentType")
            or media.get("type"),
        )
        _assign("category", media.get("category") or media.get("mediaType"))
        size = media.get("size")
        if size is not None:
            sanitized["size"] = size
        duration = media.get("duration")
        if duration is not None:
            sanitized["duration"] = duration
        for key in ("width", "height"):
            if media.get(key) is not None:
                sanitized[key] = media.get(key)
        _assign("description", media.get("description") or media.get("summary"))
        _assign("url", media.get("url"))
        _assign("thumbnailUrl", media.get("thumbnailUrl"))
        return sanitized

    async def _make_decisions(
        self, analysis: Dict, user_message: Optional[Dict[str, Any]] = None
    ) -> Dict[str, bool]:
        """Derive high-level routing decisions based on config-selected mode."""
        mode = str(
            config_service.get_config_value("decision_layer.mode", "system") or "system"
        ).strip().lower()
        if mode == "llm":
            llm_decisions = await self._make_llm_decisions(analysis, user_message or {})
            if llm_decisions is not None:
                return llm_decisions
        return self._make_system_decisions(analysis)

    def _make_system_decisions(self, analysis: Dict) -> Dict[str, bool]:
        """Derive high-level routing decisions based on analyzer results and rules."""
        themes = analysis.get("input_analysis", {}).get("dominant_themes", [])
        orchestration = self._analysis_orchestration(analysis)
        decisions = {
            "needs_vision": bool(orchestration.get("need_vision")) or self._should_use_vision(analysis),
            "needs_deep_memory": bool(orchestration.get("need_memory")) or self._should_use_deep_memory(themes),
            "needs_web_search": bool(orchestration.get("need_web_search")) or self._should_use_web_search(themes),
            "needs_emotional_support": self._should_provide_emotional_support(analysis),
            "needs_creative_mode": self._should_use_creative_mode(themes),
        }
        print("[DecisionLayer] Решения приняты: ", decisions)
        log_audit_entry(
            "decision_layer_decisions_derived",
            "[DecisionLayer] Решения приняты.",
            AuditStatus.INFO,
            details={"decisions": decisions},
        )
        return decisions

    @classmethod
    def _detect_visual_hard_signal(
        cls,
        user_message: Dict[str, Any],
        media_payload: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Detect explicit visual inputs that must bypass analyzer uncertainty."""
        sources: List[str] = []
        media_items = list(media_payload or [])
        if not media_items:
            media_items = [
                dict(item)
                for item in (user_message.get("media") or [])
                if isinstance(item, dict)
            ]

        if cls._message_has_image_metadata(media_items):
            sources.append("image_attachment")

        feature_flags = user_message.get("feature_flags")
        runtime_meta = user_message.get("runtime_meta")
        if cls._has_truthy_visual_flag(feature_flags):
            sources.append("feature_flag")
        if cls._has_truthy_visual_flag(runtime_meta):
            sources.append("runtime_meta")

        screen_context = user_message.get("screen") or user_message.get("screen_context")
        if isinstance(screen_context, dict) and screen_context:
            sources.append("screen_context")

        sources = list(dict.fromkeys(sources))
        return {
            "needs_vision": bool(sources),
            "reason": "explicit_visual_input" if sources else "",
            "sources": sources,
            "media_count": len(media_items),
        }

    @staticmethod
    def _has_truthy_visual_flag(value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        visual_keys = {
            "vision",
            "visual",
            "visual_context",
            "screen",
            "screen_share",
            "screen_sharing",
            "screen_capture",
            "webrtc",
            "camera",
        }
        for key in visual_keys:
            flag = value.get(key)
            if isinstance(flag, bool) and flag:
                return True
            if isinstance(flag, dict) and flag:
                enabled = flag.get("enabled")
                if enabled is None or bool(enabled):
                    return True
        return False

    async def _make_llm_decisions(
        self, analysis: Dict, user_message: Dict[str, Any]
    ) -> Optional[Dict[str, bool]]:
        """Ask the configured LLM to route the message via a constrained tool schema."""
        provider = str(
            config_service.get_config_value(
                "decision_layer.active_provider", "ollama"
            )
            or "ollama"
        ).strip().lower()
        if provider != "ollama":
            return None

        provider_cfg = (
            config_service.get_config_value("decision_layer.providers.ollama", {}) or {}
        )
        model = str(
            provider_cfg.get("model")
            or config_service.get_config_value("api.providers.ollama.model", "")
            or config_service.get_config_value("api.model", "llama3.2")
        ).strip()
        if not model:
            return None

        capabilities = (
            config_service.get_config_value("decision_layer.capabilities", {}) or {}
        )
        use_tools = bool(capabilities.get("tool"))
        options = {
            "temperature": float(provider_cfg.get("temperature", 0.2)),
            "num_predict": int(provider_cfg.get("max_tokens", 512)),
            "__think": bool(provider_cfg.get("thinking", provider_cfg.get("think", False))),
        }
        route_tool = self._decision_route_tool()
        payload = self._build_llm_decision_payload(analysis, user_message)
        messages = [
            {"role": "system", "content": DECISION_LAYER_ORCHESTRATOR_PROMPT},
            {
                "role": "user",
                "content": (
                    "Choose routing decisions for this message. "
                    "Return only by using the decide_route tool.\n\n"
                    f"{json.dumps(payload, ensure_ascii=False)}"
                ),
            },
        ]

        try:
            raw = await asyncio.to_thread(
                ollama_client.chat_with_tools,
                messages,
                options,
                model,
                tools=[route_tool] if use_tools else None,
                tool_choice={"type": "function", "function": {"name": "decide_route"}}
                if use_tools
                else None,
            )
            parsed = self._extract_llm_decisions(raw)
            if parsed is None:
                return None
            system_decisions = self._make_system_decisions(analysis)
            decisions = {**system_decisions, **parsed}
            if self._message_has_image_metadata(user_message.get("media") or []):
                decisions["needs_vision"] = True
            log_audit_entry(
                "decision_layer_llm_decisions_made",
                "[DecisionLayer] LLM routing decisions accepted.",
                AuditStatus.INFO,
                details={"model": model, "decisions": decisions, "raw": raw},
            )
            return decisions
        except Exception as exc:
            log_audit_entry(
                "decision_layer_llm_decision_error",
                "[DecisionLayer] LLM routing failed; falling back to system decisions.",
                AuditStatus.WARNING,
                details={"model": model, "error": str(exc)},
            )
            return None
        finally:
            if should_release_resources("decision_layer"):
                try:
                    ollama_client.release_model(model=model)
                except Exception as exc:
                    log_audit_entry(
                        "decision_layer_provider_release_error",
                        "[DecisionLayer] Provider resource release failed.",
                        AuditStatus.WARNING,
                        details={"provider": provider, "model": model, "error": str(exc)},
                    )

    @staticmethod
    def _decision_route_tool() -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "decide_route",
                "description": "Set internal routing flags for the next cognitive pipeline steps.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "needs_vision": {"type": "boolean"},
                        "needs_deep_memory": {"type": "boolean"},
                        "needs_web_search": {"type": "boolean"},
                        "needs_emotional_support": {"type": "boolean"},
                        "needs_creative_mode": {"type": "boolean"},
                    },
                    "required": [
                        "needs_vision",
                        "needs_deep_memory",
                        "needs_web_search",
                        "needs_emotional_support",
                        "needs_creative_mode",
                    ],
                },
            },
        }

    @staticmethod
    def _build_llm_decision_payload(
        analysis: Dict[str, Any], user_message: Dict[str, Any]
    ) -> Dict[str, Any]:
        safe_message = {
            "content": str(user_message.get("content") or "")[:2000],
            "media": user_message.get("media") or [],
            "history_count": len(user_message.get("history") or []),
        }
        return {
            "message": safe_message,
            "analysis": analysis or {},
            "available_tools": [
                "vision.describe",
                "memory.collect_context",
                "moral_matrix.evaluate",
                "instructor.build_system_prompt",
            ],
        }

    @staticmethod
    def _extract_llm_decisions(raw: Dict[str, Any]) -> Optional[Dict[str, bool]]:
        message = (raw or {}).get("message") or {}
        tool_calls = message.get("tool_calls") or []
        args: Any = None
        if isinstance(tool_calls, list):
            for call in tool_calls:
                function = (call or {}).get("function") or {}
                if function.get("name") != "decide_route":
                    continue
                args = function.get("arguments")
                break
        if args is None:
            content = str(message.get("content") or "").strip()
            if content.startswith("```"):
                content = content.strip("`").strip()
                if content.lower().startswith("json"):
                    content = content[4:].strip()
            args = content
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                return None
        if not isinstance(args, dict):
            return None
        allowed = {
            "needs_vision",
            "needs_deep_memory",
            "needs_web_search",
            "needs_emotional_support",
            "needs_creative_mode",
        }
        return {key: bool(args.get(key, False)) for key in allowed}

    def _should_use_vision(self, analysis: Dict) -> bool:
        """
        Determine if visual module should be engaged.
        """
        themes = analysis.get("input_analysis", {}).get("dominant_themes", [])
        category = analysis.get("input_analysis", {}).get("content_category", "")
        primary_intent = (
            analysis.get("input_analysis", {})
            .get("intent_analysis", {})
            .get("primary_intent", "")
        )

        has_vision_theme = any(theme in themes for theme in VISION_INDICATORS["themes"])
        has_vision_intent = primary_intent in VISION_INDICATORS["intents"]
        has_vision_category = category in VISION_INDICATORS["categories"]

        original_message = (
            analysis.get("input_analysis", {}).get("original_message", "").lower()
        )
        has_keyword = any(keyword in original_message for keyword in VISION_KEYWORDS)

        result = (
            has_vision_theme or has_vision_intent or has_vision_category or has_keyword
        )
        print(f"[DecisionLayer] Необходимость использования зрения: {result}")
        log_audit_entry(
            "decision_layer_vision_decision",
            "[DecisionLayer] Решение о необходимости использования зрения.",
            AuditStatus.INFO,
            details={"result": result},
        )
        return result

    def _should_use_deep_memory(self, themes: List[str]) -> bool:
        """Check if deep memory module should be used."""
        allowed = self._is_deep_memory_enabled()
        forced = bool(config_service.get_config_value("memory.force_deep_memory", False))
        thematic_match = any(theme in DEEP_MEMORY_THEMES for theme in themes)
        result = bool(allowed and (thematic_match or forced))
        print(f"[DecisionLayer] Необходимость использования глубокой памяти: {result}")
        log_audit_entry(
            "decision_layer_deep_memory_decision",
            "[DecisionLayer] Решение о необходимости использования глубокой памяти.",
            AuditStatus.INFO,
            details={
                "result": result,
                "allowed_by_config": allowed,
                "thematic_match": thematic_match,
                "forced_by_config": forced,
            },
        )
        return result

    def _should_use_web_search(self, themes: List[str]) -> bool:
        """Check if web search should be used."""
        result = any(theme in SEARCH_THEMES for theme in themes)
        print(
            f"[DecisionLayer] Необходимость использования поиска в интернете: {result}"
        )
        log_audit_entry(
            "decision_layer_web_search_decision",
            "[DecisionLayer] Решение о необходимости использования поиска в интернете.",
            AuditStatus.INFO,
            details={"result": result},
        )
        return result

    def _should_provide_emotional_support(self, analysis: Dict) -> bool:
        """Check if emotional support is required."""
        primary_emotion = (
            analysis.get("input_analysis", {})
            .get("emotional_tone", {})
            .get("primary", "")
        )
        result = any(emotion in primary_emotion.lower() for emotion in SUPPORT_EMOTIONS)
        print(f"[DecisionLayer] Необходимость эмоциональной поддержки: {result}")
        log_audit_entry(
            "decision_layer_emotional_support_decision",
            "[DecisionLayer] Решение о необходимости эмоциональной поддержки.",
            AuditStatus.INFO,
            details={"result": result},
        )
        return result

    def _should_use_creative_mode(self, themes: List[str]) -> bool:
        """Check if creative mode should be activated."""
        result = any(theme in CREATIVE_THEMES for theme in themes)
        print(f"[DecisionLayer] Необходимость активации креативного режима: {result}")
        log_audit_entry(
            "decision_layer_creative_mode_decision",
            "[DecisionLayer] Решение о необходимости активации креативного режима.",
            AuditStatus.INFO,
            details={"result": result},
        )
        return result

    # --------------------------------------------------------------------- #
    #                     VISUAL MODULE HANDLING
    # --------------------------------------------------------------------- #
    def _get_visual_module(self) -> Optional[VisualModule]:
        if self._visual_module_failed:
            return None
        if self._visual_module is None:
            try:
                self._visual_module = VisualModule()
                print("[DecisionLayer] Модуль VisionModule инициализирован.")
                log_audit_entry(
                    "decision_layer_vision_module_init",
                    "[DecisionLayer] Модуль VisionModule инициализирован.",
                    AuditStatus.INFO,
                )
            except Exception as exc:
                print(f"[DecisionLayer] Ошибка инициализации VisionModule: {exc}")
                log_audit_entry(
                    "decision_layer_vision_init_error",
                    "[DecisionLayer] Ошибка инициализации VisionModule.",
                    AuditStatus.ERROR,
                    details={"error": str(exc)},
                )
                self._visual_module_failed = True
                self._visual_module = None
        return self._visual_module

    async def _collect_visual_context(
        self, media_payload: List[Dict[str, Any]], decisions: Dict[str, bool]
    ) -> Dict[str, Any]:
        """Collect visual description of attachments and/or screen snapshot."""
        if not config_service.get_config_value("vision.enabled", False):
            print("[DecisionLayer] Визуальный модуль отключен в конфигурации.")
            log_audit_entry(
                "decision_layer_vision_disabled",
                "[DecisionLayer] Визуальный модуль отключен в конфигурации.",
                AuditStatus.INFO,
            )
            return {}

        media_payload = media_payload or []
        has_images = self._has_image_attachments(media_payload)
        direct_ollama_media = self._should_pass_media_to_main_ollama_model()
        needs_vision = decisions.get("needs_vision", False)
        if not needs_vision:
            print("[DecisionLayer] Визуальный анализ не требуется — пропускаем.")
            log_audit_entry(
                "decision_layer_vision_skipped",
                "[DecisionLayer] Визуальный анализ пропущен.",
                AuditStatus.INFO,
                details={"needs_vision": needs_vision, "has_images": has_images},
            )
            return {}

        if direct_ollama_media and has_images:
            log_audit_entry(
                "decision_layer_vision_attachment_direct_context",
                "[DecisionLayer] Image attachments will be passed to the main Ollama model.",
                AuditStatus.INFO,
                details={"media_count": len(media_payload)},
            )
            return {
                "attachments": {
                    "direct_context": True,
                    "provider": "ollama",
                    "items": [],
                    "count": sum(
                        1
                        for item in media_payload
                        if (item.get("category") or "").lower() == "image" and item.get("data")
                    ),
                }
            }

        module = self._get_visual_module()
        if not module:
            print("[DecisionLayer] Визуальный модуль недоступен.")
            log_audit_entry(
                "decision_layer_vision_module_unavailable",
                "[DecisionLayer] Визуальный модуль недоступен.",
                AuditStatus.WARNING,
            )
            return {}

        if not module.is_ready():
            print("[DecisionLayer] Визуальный модуль не готов к обработке.")
            log_audit_entry(
                "decision_layer_vision_not_ready",
                "[DecisionLayer] Визуальный модуль не готов к обработке.",
                AuditStatus.WARNING,
            )
            return {}

        # ----------------------------------------------------------------- #
        # Run two potentially heavy visual operations in separate threads
        # ----------------------------------------------------------------- #
        coroutines = [
            (
                asyncio.to_thread(module.describe_media_attachments, media_payload)
                if has_images and not direct_ollama_media
                else asyncio.sleep(0, result=None)
            ),
            (
                asyncio.to_thread(module.describe_screen_snapshot)
                if decisions.get("needs_vision", False)
                else asyncio.sleep(0, result=None)
            ),
        ]

        attachments_result, screen_result = await asyncio.gather(
            *coroutines, return_exceptions=True
        )

        # ----------------------------------------------------------------- #
        # Log results (including exceptions, if they occurred)
        # ----------------------------------------------------------------- #
        if isinstance(attachments_result, Exception):
            print(
                f"[DecisionLayer] Ошибка при описании изображений: {attachments_result}"
            )
            log_audit_entry(
                "decision_layer_vision_attachment_error",
                "[DecisionLayer] Ошибка при описании изображений.",
                AuditStatus.ERROR,
                details={"error": str(attachments_result)},
            )
            attachments_result = None
        else:
            print("[DecisionLayer] Описание изображений завершено.")
            log_audit_entry(
                "decision_layer_vision_attachments",
                "[DecisionLayer] Описание изображений завершено.",
                AuditStatus.INFO,
                details={"result": attachments_result},
            )

        if isinstance(screen_result, Exception):
            print(f"[DecisionLayer] Ошибка при описании экрана: {screen_result}")
            log_audit_entry(
                "decision_layer_vision_screen_error",
                "[DecisionLayer] Ошибка при описании экрана.",
                AuditStatus.ERROR,
                details={"error": str(screen_result)},
            )
            screen_result = None
        else:
            print("[DecisionLayer] Описание экрана завершено.")
            log_audit_entry(
                "decision_layer_vision_screen",
                "[DecisionLayer] Описание экрана завершено.",
                AuditStatus.INFO,
                details={"result": screen_result},
            )

        # ----------------------------------------------------------------- #
        # Prepare final visual_context
        # ----------------------------------------------------------------- #
        visual_context: Dict[str, Any] = {}

        if attachments_result:
            updates = attachments_result.get("updates", [])
            for update in updates:
                idx = update.get("index")
                summary = update.get("description")
                if isinstance(idx, int) and summary and 0 <= idx < len(media_payload):
                    media_payload[idx]["description"] = summary
            if attachments_result.get("items"):
                visual_context["attachments"] = attachments_result

        if screen_result and screen_result.get("description"):
            visual_context["screen"] = screen_result

        if visual_context:
            print("[DecisionLayer] Визуальный контекст подготовлен.")
            log_audit_entry(
                "decision_layer_visual_context_prepared",
                "[DecisionLayer] Визуальный контекст подготовлен.",
                AuditStatus.INFO,
                details={
                    "attachments": len(
                        (visual_context.get("attachments", {}) or {}).get("items", [])
                    ),
                    "has_screen": bool(visual_context.get("screen")),
                },
            )

        return visual_context

    @staticmethod
    def _should_pass_media_to_main_ollama_model() -> bool:
        active_provider = str(
            config_service.get_config_value("vision.active_provider", "")
            or ""
        ).strip()
        if active_provider not in {"ollama_vision", "llava"}:
            return False
        return bool(
            config_service.get_config_value(
                f"vision.vision_modules.{active_provider}.use_main_model_context",
                False,
            )
        )

    @staticmethod
    def _has_image_attachments(media_payload: List[Dict[str, Any]]) -> bool:
        for item in media_payload:
            if (item.get("category") or "").lower() == "image" and item.get("data"):
                return True
        return False

    @staticmethod
    def _message_has_image_metadata(media_payload: List[Dict[str, Any]]) -> bool:
        for item in media_payload or []:
            category = (item.get("category") or item.get("mediaType") or "").lower()
            mime_type = (item.get("mimeType") or item.get("mime_type") or "").lower()
            if category == "image" or mime_type.startswith("image/"):
                return True
        return False


# --------------------------------------------------------------------- #
# Global singleton instance – can be imported everywhere as `decision_layer`
# --------------------------------------------------------------------- #
decision_layer = DecisionLayer()

