"""High-level orchestration for the Moral Matrix module."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pprint import pformat
from typing import Any, Dict, List, Optional, Sequence, Tuple

from constants.moral import (
    DEFAULT_EMOTIONAL_STATE,
    DEFAULT_METRICS,
    EMOTIONAL_STATE_DEFINITIONS,
    EMOTION_SYNONYMS,
    NEGATIVE_EMOTIONS,
    POSITIVE_EMOTIONS,
    RELATIONSHIP_STATUSES,
    BEHAVIORAL_RECOMMENDATIONS,
    FALLBACK_RECOMMENDATION,
)
from modules.moral_matrix.repository import MoralMatrixRepository
from modules.moral_matrix.types import MoralMatrixMetrics, MoralMatrixResult
from modules.moral_matrix import heuristics
from modules.moral_matrix.providers import (
    HeuristicMoralProvider,
    LlamaCppMoralProvider,
    OllamaMoralProvider,
    OpenRouterMoralProvider,
)
from modules.moral_matrix.providers.base import MoralMatrixProvider
from modules.system import character as character_service
from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry
from modules.system.runtime_profile import should_release_resources
from modules.system.service import get_active_character_name
from modules.system.user import resolve_user_language


@dataclass
class ProviderRunResult:
    payload: Optional[Dict[str, Any]]
    provider: Optional[str]


class MoralMatrixProviderManager:
    """Controls the execution order of MoralMatrix providers."""

    def __init__(self) -> None:
        self._registry: Dict[str, MoralMatrixProvider] = {
            "heuristic": HeuristicMoralProvider(),
            "ollama": OllamaMoralProvider(),
            "openrouter": OpenRouterMoralProvider(),
            "llama_cpp": LlamaCppMoralProvider(),
        }

    async def run(self, payload: Dict[str, Any]) -> ProviderRunResult:
        errors: List[str] = []
        providers = self._resolve_providers()
        log_audit_entry(
            "moral_matrix_provider_chain",
            "[MoralMatrix] Provider execution order resolved.",
            AuditStatus.INFO,
            details={"order": [provider.name for provider in providers]},
        )
        print(
            "[MoralMatrix] Provider order:", [provider.name for provider in providers]
        )

        for provider in providers:
            if not provider.is_available():
                errors.append(f"{provider.name}_unavailable")
                continue
            try:
                result = await provider.run(payload)
                if result:
                    return ProviderRunResult(payload=result, provider=provider.name)
            except Exception as exc:
                errors.append(f"{provider.name}_error")
                log_audit_entry(
                    "moral_matrix_provider_unhandled_error",
                    "[MoralMatrix] Provider failed; trying next fallback.",
                    AuditStatus.WARNING,
                    details={
                        "provider": provider.name,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                )
            finally:
                if should_release_resources("moral"):
                    try:
                        provider.release_resources()
                    except Exception as exc:
                        log_audit_entry(
                            "moral_matrix_provider_release_error",
                            "[MoralMatrix] Provider resource release failed.",
                            AuditStatus.WARNING,
                            details={"provider": provider.name, "error": str(exc)},
                        )
        if errors:
            log_audit_entry(
                "moral_matrix.providers_unavailable",
                "[MoralMatrix] Providers unavailable.",
                AuditStatus.WARNING,
                details={"errors": errors},
            )
        return ProviderRunResult(payload=None, provider=None)

    def _resolve_providers(self) -> List[MoralMatrixProvider]:
        active = config_service.get_config_value("moral.active_provider", "heuristic")
        fallback = config_service.get_config_value("moral.fallback_order", []) or []

        order: List[str] = []
        if isinstance(active, str) and active:
            order.append(active)

        if isinstance(fallback, list):
            for name in fallback:
                if isinstance(name, str):
                    order.append(name)

        include_heuristic = False
        filtered_order: List[str] = []
        for name in order:
            if name == "heuristic":
                include_heuristic = True
                continue
            filtered_order.append(name)

        if include_heuristic or active == "heuristic" or not filtered_order:
            filtered_order.append("heuristic")

        order = filtered_order

        resolved: List[MoralMatrixProvider] = []
        for name in order:
            provider = self._registry.get(name)
            if provider and provider not in resolved:
                resolved.append(provider)

        for provider in self._registry.values():
            if provider not in resolved:
                resolved.append(provider)

        return resolved


class MoralMatrixModule:
    """Computes current emotional and moral directives for the system."""

    def __init__(self) -> None:
        self._repository = MoralMatrixRepository()
        self._provider_manager = MoralMatrixProviderManager()

    async def evaluate(
        self,
        analysis_result: Dict[str, Any],
        memory_context: Dict[str, Any],
        memory_meta: Dict[str, Any],
        *,
        message_meta: Optional[Dict[str, Any]] = None,
        user_message: Optional[Dict[str, Any]] = None,
        persist_state: bool = True,
    ) -> Dict[str, Any]:
        """Evaluate current moral state and return structured guidance."""
        log_audit_entry(
            "moral_matrix_evaluate_start",
            "[MoralMatrix] Starting evaluation.",
            AuditStatus.INFO,
            details={
                "has_analysis": bool(analysis_result),
                "matches": len((memory_context or {}).get("matches", [])),
            },
        )

        if not bool(config_service.get_config_value("moral.enabled", True)):
            log_audit_entry(
                "moral_matrix_disabled",
                "[MoralMatrix] Module disabled in configuration.",
                AuditStatus.WARNING,
            )
            print("[MoralMatrix] Module disabled via config.")
            metrics = MoralMatrixMetrics(
                trust=DEFAULT_METRICS.get("trust", 0.6),
                stability=DEFAULT_METRICS.get("stability", 0.6),
                sociability=DEFAULT_METRICS.get("sociability", 0.6),
                resentment=DEFAULT_METRICS.get("resentment", 0.05),
            )
            return MoralMatrixResult(
                current_emotion="peace",
                emotion_intensity=0.0,
                relationship_status=self._derive_relationship_status(metrics.trust),
                metrics=metrics,
                emotion_vector=dict(DEFAULT_EMOTIONAL_STATE),
                recommendations=FALLBACK_RECOMMENDATION,
                hard_directives=[],
                narrative="Moral Matrix disabled.",
                trigger="moral matrix disabled",
                influence=self._derive_influence("peace", 0.0),
                meta={"disabled": True},
            ).to_payload()

        character_id = self._resolve_character_id()

        history_ids = self._collect_history_ids(memory_context, message_meta)
        log_audit_entry(
            "moral_matrix_history_scope",
            "[MoralMatrix] History scope resolved.",
            AuditStatus.INFO,
            details={"history_ids": history_ids},
        )
        print("[MoralMatrix] History ids ->", history_ids)

        recent_traces = self._repository.fetch_recent_traces(character_id, limit=6)

        # Heuristic forgiveness pass: if the current user message shows a
        # warm/apologetic tone, soften recent unresolved negative traces.
        # Deliberately NOT an LLM call — same-turn latency must stay flat.
        # Future enhancement: validate suspect-cases via service-LLM judge.
        try:
            self._apply_heuristic_forgiveness(
                character_id=character_id,
                analyzer_emotion=self._extract_analyzer_emotion(analysis_result),
                user_message_text=str((user_message or {}).get("content") or ""),
            )
        except Exception as exc:
            log_audit_entry(
                "moral_matrix_forgiveness_skipped",
                "[MoralMatrix] Forgiveness heuristic skipped due to error.",
                AuditStatus.WARNING,
                details={"error": str(exc), "character_id": character_id},
            )

        # Re-fetch traces — the forgiveness pass may have updated intensities
        # and we want the rest of evaluate() to see the softened values.
        recent_traces = self._repository.fetch_recent_traces(character_id, limit=6)

        matched_traces = self._repository.fetch_traces_for_messages(
            character_id, history_ids
        )
        similar_traces = self._repository.fetch_similar_traces(
            character_id,
            str((user_message or {}).get("content") or ""),
            limit=5,
        )
        known_trace_ids = {trace.get("id") for trace in matched_traces if trace.get("id")}
        for trace in similar_traces:
            if trace.get("id") not in known_trace_ids:
                matched_traces.append(trace)
                known_trace_ids.add(trace.get("id"))
        latest_snapshot = self._repository.fetch_latest_snapshot(character_id)
        daily_summary = self._repository.fetch_daily_summary(character_id, date.today())

        log_audit_entry(
            "moral_matrix_repository_payload",
            "[MoralMatrix] Repository data fetched.",
            AuditStatus.INFO,
            details={
                "recent_traces": len(recent_traces),
                "matched_traces": len(matched_traces),
                "similar_traces": len(similar_traces),
                "latest_snapshot": bool(latest_snapshot),
                "daily_summary": bool(daily_summary),
            },
        )
        print("[MoralMatrix] Repo snapshot successful")

        metrics = self._bootstrap_metrics(latest_snapshot, daily_summary)
        emotion_vector = self._bootstrap_emotion_vector(
            latest_snapshot, daily_summary, recent_traces
        )

        self._apply_trace_context(emotion_vector, matched_traces, recent_traces)
        analyzer_snapshot = self._extract_analyzer_emotion(analysis_result)
        heuristic_snapshot = None
        if user_message and (
            not analyzer_snapshot.get("primary")
            or analyzer_snapshot["primary"] == "neutral"
        ):
            heuristic_snapshot = self._merge_heuristics(
                analyzer_snapshot,
                emotion_vector,
                user_message.get("content", ""),
            )

        current_emotion, emotion_intensity = self._blend_emotions(
            emotion_vector, analyzer_snapshot
        )
        trigger = self._derive_trigger(user_message, analyzer_snapshot, matched_traces)
        associated_events = self._derive_associated_events(
            user_message, matched_traces, recent_traces
        )
        influence = self._derive_influence(current_emotion, emotion_intensity)
        affective_state = self._build_affective_state(
            current_emotion=current_emotion,
            intensity=emotion_intensity,
            trigger=trigger,
            associated_events=associated_events,
            influence=influence,
            emotion_vector=emotion_vector,
        )

        relationship_status = self._derive_relationship_status(metrics.trust)
        recommendations = self._derive_recommendations(current_emotion)
        hard_directives = self._derive_directives(metrics, analysis_result)

        provider_payload = {
            "allowed_emotions": list(DEFAULT_EMOTIONAL_STATE.keys()),
            "emotion_definitions": EMOTIONAL_STATE_DEFINITIONS,
            "previous_state": self._previous_state_payload(latest_snapshot, daily_summary),
            "current_emotion": current_emotion,
            "emotion_intensity": emotion_intensity,
            "emotion_vector": emotion_vector,
            "metrics": metrics.as_dict(),
            "memory_traces": matched_traces,
            "recent_traces": recent_traces,
            "analysis_result": analysis_result,
            "user_message": {
                "id": (user_message or {}).get("id") or (user_message or {}).get("message_id"),
                "role": (user_message or {}).get("role"),
                "content": (user_message or {}).get("content"),
            },
            "relationship_status": relationship_status,
            "affective_state": affective_state,
            "current_state": affective_state,
            "heuristics": heuristic_snapshot,
            "conversation_state": (memory_context or {}).get("conversation_state", {}),
        }
        provider_result = await self._provider_manager.run(provider_payload)
        transition = self._normalize_provider_transition(provider_result.payload)
        if transition:
            current_emotion, emotion_intensity, trigger, associated_events, influence = self._apply_provider_transition(
                transition=transition,
                emotion_vector=emotion_vector,
                fallback_emotion=current_emotion,
                fallback_intensity=emotion_intensity,
                fallback_trigger=trigger,
                fallback_events=associated_events,
                fallback_influence=influence,
            )
            affective_state = self._build_affective_state(
                current_emotion=current_emotion,
                intensity=emotion_intensity,
                trigger=trigger,
                associated_events=associated_events,
                influence=influence,
                emotion_vector=emotion_vector,
            )
            self._apply_metrics_delta(metrics, transition.get("metrics_delta") or {})

        self._apply_emotion_to_metrics(metrics, current_emotion, emotion_intensity)
        self._apply_memory_bias(metrics, matched_traces)
        self._apply_risk_bias(metrics, analysis_result)
        metrics.clamp()
        relationship_status = self._derive_relationship_status(metrics.trust)
        recommendations = self._derive_recommendations(current_emotion)
        hard_directives = self._derive_directives(metrics, analysis_result)

        narrative: Optional[str] = None
        if provider_result.payload:
            narrative = provider_result.payload.get("summary")
            extra_directives = provider_result.payload.get("hard_directives") or []
            if extra_directives:
                hard_directives.extend(extra_directives)

        meta = {
            "history_ids": list(history_ids),
            "character_id": character_id,
            "provider": provider_result.provider,
            "previous_snapshot": (latest_snapshot or {}).get("id"),
            "daily_summary": (daily_summary or {}).get("id"),
            "matched_traces": len(matched_traces),
            "recent_traces": len(recent_traces),
            "similar_traces": len(similar_traces),
            "memory_meta": {
                "matches_found": (memory_meta or {}).get("matches_found"),
                "short_term_record_id": (memory_meta or {}).get("short_term_record_id"),
            },
            "conversation_state": (memory_context or {}).get("conversation_state", {}),
            "heuristics": heuristic_snapshot,
            "transition_provider": provider_result.provider,
            "transition": transition,
        }

        result = MoralMatrixResult(
            current_emotion=current_emotion,
            emotion_intensity=emotion_intensity,
            relationship_status=relationship_status,
            metrics=metrics,
            emotion_vector=emotion_vector,
            recommendations=recommendations,
            hard_directives=hard_directives,
            narrative=narrative,
            trigger=trigger,
            associated_events=associated_events,
            influence=influence,
            affective_state=affective_state,
            meta=meta,
        )

        if persist_state:
            self._persist_state(
                character_id,
                result,
                message_meta=message_meta,
                analyzer_snapshot=analyzer_snapshot,
                user_message=user_message,
                analysis_result=analysis_result,
            )
        else:
            log_audit_entry(
                "moral_matrix_persist_skipped",
                "[MoralMatrix] Persist skipped by interaction policy.",
                AuditStatus.INFO,
                details={
                    "reason": "interaction_policy",
                    "message_id": (message_meta or {}).get("message_id"),
                },
            )

        payload = result.to_payload()
        log_audit_entry(
            "moral_matrix_evaluate_success",
            "[MoralMatrix] Evaluation complete.",
            AuditStatus.SUCCESS,
            details={
                "emotion": current_emotion,
                "intensity": round(emotion_intensity, 3),
                "relationship_status": relationship_status,
                "provider": provider_result.provider,
                "trigger": trigger,
                "influence": influence,
            },
        )
        return payload

    # ------------------------------------------------------------------ #
    # Bootstrap helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _collect_history_ids(
        memory_context: Dict[str, Any], message_meta: Optional[Dict[str, Any]]
    ) -> List[str]:
        ids: List[str] = []
        matches = (memory_context or {}).get("matches", []) or []
        for item in matches:
            message_id = item.get("message_id")
            if message_id and message_id not in ids:
                ids.append(message_id)
        short_term_ids = (memory_context or {}).get("short_term_dialogue_ids")
        if isinstance(short_term_ids, str):
            try:
                import json

                decoded = json.loads(short_term_ids)
                if isinstance(decoded, list):
                    for mid in decoded:
                        if isinstance(mid, str) and mid not in ids:
                            ids.append(mid)
            except Exception:
                pass
        elif isinstance(short_term_ids, (list, tuple, set)):
            for mid in short_term_ids:
                if isinstance(mid, str) and mid not in ids:
                    ids.append(mid)

        current_id = (message_meta or {}).get("message_id")
        if current_id and current_id not in ids:
            ids.append(current_id)
        return ids

    def _bootstrap_metrics(
        self,
        latest_snapshot: Optional[Dict[str, Any]],
        daily_summary: Optional[Dict[str, Any]],
    ) -> MoralMatrixMetrics:
        metrics = MoralMatrixMetrics(
            trust=DEFAULT_METRICS.get("trust", 0.6),
            stability=DEFAULT_METRICS.get("stability", 0.6),
            sociability=DEFAULT_METRICS.get("sociability", 0.6),
            resentment=DEFAULT_METRICS.get("resentment", 0.05),
        )
        if latest_snapshot:
            metrics.trust = float(latest_snapshot.get("trust", metrics.trust))
            metrics.stability = float(
                latest_snapshot.get("stability", metrics.stability)
            )
            metrics.sociability = float(
                latest_snapshot.get("sociability", metrics.sociability)
            )
            metrics.resentment = float(
                latest_snapshot.get("resentment", metrics.resentment)
            )

        if daily_summary:
            metrics.trust = (metrics.trust + float(daily_summary.get("trust", 0.6))) / 2
            metrics.stability = (
                metrics.stability + float(daily_summary.get("stability", 0.6))
            ) / 2
            metrics.sociability = (
                metrics.sociability + float(daily_summary.get("sociability", 0.6))
            ) / 2
            metrics.resentment = (
                metrics.resentment + float(daily_summary.get("resentment", 0.05))
            ) / 2
        return metrics

    def _bootstrap_emotion_vector(
        self,
        latest_snapshot: Optional[Dict[str, Any]],
        daily_summary: Optional[Dict[str, Any]],
        recent_traces: Sequence[Dict[str, Any]],
    ) -> Dict[str, float]:
        vector = {
            key: max(0.0, min(float(value or 0.0), 1.0))
            for key, value in DEFAULT_EMOTIONAL_STATE.items()
        }
        snapshot_meta = (latest_snapshot or {}).get("meta") or {}
        snapshot_state = snapshot_meta.get("affective_state") or snapshot_meta.get("current_state") or {}
        snapshot_vector = snapshot_state.get("emotion_vector") if isinstance(snapshot_state, dict) else None
        source_vector = snapshot_vector if isinstance(snapshot_vector, dict) else None
        if source_vector is None and isinstance(daily_summary, dict):
            source_vector = daily_summary.get("emotion_vector")
        if isinstance(source_vector, dict) and source_vector:
            vector = {
                self._normalize_emotion(str(key)): max(0.0, min(float(value or 0.0), 1.0))
                for key, value in source_vector.items()
                if self._normalize_emotion(str(key)) in DEFAULT_EMOTIONAL_STATE
            }
            for key, value in DEFAULT_EMOTIONAL_STATE.items():
                vector.setdefault(key, max(0.0, min(float(value or 0.0), 1.0)))

        # Emotional inertia: older traces nudge the state but cannot dominate
        # over the current event forever.
        for index, trace in enumerate(recent_traces or []):
            emotion = self._normalize_emotion(trace.get("primary_emotion") or "")
            if emotion not in DEFAULT_EMOTIONAL_STATE:
                continue
            intensity = max(0.0, min(float(trace.get("intensity") or 0.0), 1.0))
            weight = max(0.08, 0.22 - index * 0.025)
            vector[emotion] = vector.get(emotion, 0.0) * (1.0 - weight) + intensity * weight
        return self._normalize_vector(vector)

    @staticmethod
    def _apply_trace_context(
        emotion_vector: Dict[str, float],
        matched_traces: Sequence[Dict[str, Any]],
        recent_traces: Sequence[Dict[str, Any]],
    ) -> None:
        for trace in (matched_traces or []) + (recent_traces or []):
            emotion = MoralMatrixModule._normalize_emotion(trace.get("primary_emotion") or "")
            if emotion not in DEFAULT_EMOTIONAL_STATE:
                continue
            intensity = float(trace.get("intensity") or 0.0)
            # Similar situations matter, but should be interpreted as context,
            # not copied as the new dominant emotion.
            emotion_vector[emotion] = min(1.0, emotion_vector.get(emotion, 0.0) + intensity * 0.12)

    def _generate_inner_voice(
        self,
        *,
        emotion: str,
        intensity: float,
        cause: str,
        language_hint: str,
    ) -> str:
        """One short first-person sentence explaining the current emotional shift.

        Used by ``_persist_state``: feeds into ``EmotionalTrace.notes.inner_voice``
        and into ``result.meta["inner_voice"]`` so the existing WS ``moral_state``
        event surfaces it to the UI without a new event type.

        Returns "" on any failure — inner voice is a wow-feature, not a
        correctness requirement.
        """
        try:
            # Lazy imports — avoid circular import via generative → analyzer pipeline.
            from constants.prompts import MORAL_INNER_VOICE_PROMPT
            from modules.generative.manager import (
                NoProviderResolved,
                generation_manager,
            )
            from modules.generative.types import GenerateRequest
        except Exception as exc:
            log_audit_entry(
                "moral_matrix_inner_voice_import_failed",
                "[MoralMatrix] Inner voice generation module unavailable.",
                AuditStatus.WARNING,
                details={"error": str(exc)},
            )
            return ""

        max_tokens = int(
            config_service.get_config_value("moral.inner_voice.max_tokens", 80) or 80
        )
        temperature = float(
            config_service.get_config_value("moral.inner_voice.temperature", 0.7) or 0.7
        )
        # Source of truth for generation language is User.language.
        # system.language is UI-only; using it here is a legacy fallback kept
        # for boot windows when DB lookup fails.
        language = (
            str(language_hint or "")
            or str(config_service.get_config_value("moral.inner_voice.language", "") or "")
            or resolve_user_language(fallback="en-US")
        )

        user_payload = (
            f"Language: {language}\n"
            f"Current emotion: {emotion}\n"
            f"Intensity: {round(float(intensity or 0.0), 3)}\n"
            f"Trigger: {str(cause or '').strip()[:600]}"
        )

        try:
            result = generation_manager.generate(
                GenerateRequest(
                    messages=[
                        {"role": "system", "content": MORAL_INNER_VOICE_PROMPT},
                        {"role": "user", "content": user_payload},
                    ],
                    options={
                        "temperature": temperature,
                        "num_predict": max_tokens,
                        "max_tokens": max_tokens,
                        "__think": False,
                    },
                    metadata={"mode": "moral_inner_voice"},
                )
            )
        except NoProviderResolved as exc:
            log_audit_entry(
                "moral_matrix_inner_voice_no_provider",
                "[MoralMatrix] No provider for inner voice; skipping.",
                AuditStatus.WARNING,
                details={"error": str(exc)},
            )
            return ""
        except Exception as exc:
            log_audit_entry(
                "moral_matrix_inner_voice_failed",
                "[MoralMatrix] Inner voice generation failed.",
                AuditStatus.WARNING,
                details={"error": str(exc)},
            )
            return ""

        text = str(getattr(result, "content", "") or "").strip()
        # Strip a possible "Inner voice:" prefix that small models love to add.
        for prefix in ("Inner voice:", "PAI:", "Lim:", "Лим:", "ПАИ:"):
            if text.lower().startswith(prefix.lower()):
                text = text[len(prefix):].strip()
        # Trim to a single sentence — model sometimes ignores the rule.
        # Take everything up to the first sentence terminator + 1 char.
        for terminator in (". ", "! ", "? ", "\n"):
            idx = text.find(terminator)
            if 0 < idx < 240:
                text = text[: idx + 1].strip()
                break
        return text

    @staticmethod
    def _match_scar_trigger(
        analyzer_emotion: Dict[str, Any],
        analysis_result: Dict[str, Any],
        message_text: str,
        triggers: Sequence[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Return the first scar trigger matching the current turn, or None.

        Match is OR across the three signal types within a single trigger:
        a trigger fires when ANY of its intents / tones / keywords matches.
        Triggers themselves are evaluated in declaration order — first wins.
        """
        if not triggers:
            return None

        # Pull intent from analysis_result. Concept docs (Pai_Updated_Concept §3.2)
        # state analyzer surfaces intent in input_analysis.intent; we accept
        # either a string or {primary, ...}.
        intent_field = (
            (analysis_result or {}).get("input_analysis", {}).get("intent")
            if isinstance(analysis_result, dict)
            else None
        )
        if isinstance(intent_field, dict):
            intent_value = str(intent_field.get("primary") or "").strip().lower()
        else:
            intent_value = str(intent_field or "").strip().lower()

        tones: set[str] = set()
        primary_tone = str((analyzer_emotion or {}).get("primary") or "").lower()
        if primary_tone:
            tones.add(primary_tone)
        for secondary in (analyzer_emotion or {}).get("secondary") or []:
            tones.add(str(secondary).lower())

        text_lower = (message_text or "").lower()

        for trigger in triggers:
            if not isinstance(trigger, dict):
                continue
            name = str(trigger.get("name") or "").strip()
            if not name:
                continue

            intent_hits = [
                str(item).strip().lower()
                for item in (trigger.get("intents") or [])
                if str(item).strip()
            ]
            if intent_value and intent_value in intent_hits:
                return trigger

            tone_hits = {
                str(item).strip().lower()
                for item in (trigger.get("tones") or [])
                if str(item).strip()
            }
            if tone_hits & tones:
                return trigger

            keyword_hits = [
                str(item).strip().lower()
                for item in (trigger.get("keywords") or [])
                if str(item).strip()
            ]
            if text_lower and any(kw in text_lower for kw in keyword_hits):
                return trigger

        return None

    @staticmethod
    def _apply_scar_to_payload(
        trace_payload: Dict[str, Any],
        scar: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Mutate ``trace_payload`` to bake a scar into the new EmotionalTrace.

        Bumps intensity by ``intensity_boost`` (clamped to 1.0), sets
        ``persistence_floor`` from the trigger config, ensures the result is
        not below the floor, and records the scar label inside notes for the
        UI timeline + later auditing.
        """
        boost = float(scar.get("intensity_boost") or 0.0)
        floor = float(scar.get("persistence_floor") or 0.4)
        label = str(scar.get("name") or "")

        current_intensity = float(trace_payload.get("intensity") or 0.0)
        new_intensity = min(1.0, max(current_intensity + boost, floor))

        trace_payload["intensity"] = new_intensity
        trace_payload["persistence_floor"] = floor

        notes = trace_payload.get("notes")
        if not isinstance(notes, dict):
            notes = {"text": notes} if notes else {}
        notes["scar"] = {
            "label": label,
            "persistence_floor": floor,
            "intensity_boost": boost,
        }
        trace_payload["notes"] = notes
        trace_payload["scar_label"] = label  # surfaced to audit log
        return trace_payload

    def _apply_heuristic_forgiveness(
        self,
        *,
        character_id: str,
        analyzer_emotion: Dict[str, Any],
        user_message_text: str,
    ) -> None:
        """Detect compensating user behaviour and soften matching traces.

        Heuristic only — no LLM call. Detection: primary tone or any secondary
        tone falls into ``moral.forgiveness.compensating_tones``. When matched,
        the most recent unresolved negative trace in window is softened by
        ``delta_per_event``. The softening is clamped to ``persistence_floor``
        in the repository — see register_forgiveness.
        """
        if not bool(config_service.get_config_value("moral.forgiveness.enabled", True)):
            return
        if not character_id:
            return

        compensating_tones = set(
            map(
                str.lower,
                config_service.get_config_value(
                    "moral.forgiveness.compensating_tones", []
                )
                or [],
            )
        )
        softenable = config_service.get_config_value(
            "moral.forgiveness.softenable_emotions", []
        ) or []
        delta = float(
            config_service.get_config_value("moral.forgiveness.delta_per_event", 0.15)
            or 0.15
        )
        lookback = int(
            config_service.get_config_value("moral.forgiveness.lookback_days", 30)
            or 30
        )

        if not compensating_tones or not softenable or delta <= 0:
            return

        primary = str((analyzer_emotion or {}).get("primary") or "").lower()
        secondary = [str(x).lower() for x in (analyzer_emotion or {}).get("secondary") or []]
        matched_tone = None
        if primary in compensating_tones:
            matched_tone = primary
        else:
            for tone in secondary:
                if tone in compensating_tones:
                    matched_tone = tone
                    break

        if not matched_tone:
            return

        candidates = self._repository.fetch_unresolved_negative_traces(
            character_id,
            emotions=list(softenable),
            within_days=lookback,
            limit=1,  # MVP: soften the most recent only. Bulk-softening can be
                     # tuned later if log evidence shows it under-applies.
        )
        if not candidates:
            return

        target = candidates[0]
        target_id = target.get("id")
        if not target_id:
            return

        # Build a human-readable trail for diagnostics / UI timeline.
        excerpt = (user_message_text or "").strip()
        if len(excerpt) > 240:
            excerpt = excerpt[:240] + "…"

        applied = self._repository.register_forgiveness(
            character_id,
            trace_id=target_id,
            cause=f"compensating tone detected: {matched_tone}",
            compensating_action=excerpt,
            delta_intensity=delta,
        )
        if applied:
            log_audit_entry(
                "moral_matrix_forgiveness_applied",
                "[MoralMatrix] Forgiveness softened a trace.",
                AuditStatus.INFO,
                details={
                    "character_id": character_id,
                    "trace_id": target_id,
                    "tone": matched_tone,
                    **applied,
                },
            )

    @staticmethod
    def _extract_analyzer_emotion(analysis_result: Dict[str, Any]) -> Dict[str, Any]:
        tone = (
            analysis_result.get("input_analysis", {}).get("emotional_tone", {})
            if isinstance(analysis_result, dict)
            else {}
        )
        primary = (tone.get("primary") or "neutral").lower()
        intensity = float(tone.get("intensity") or 0.3)
        secondary = [str(x).lower() for x in tone.get("secondary", []) if x]
        return {
            "primary": primary,
            "intensity": intensity,
            "secondary": secondary,
            "raw": tone,
        }

    def _merge_heuristics(
        self,
        analyzer_snapshot: Dict[str, Any],
        emotion_vector: Dict[str, float],
        message_text: str,
    ) -> Optional[Dict[str, Any]]:
        content = (message_text or "").strip()
        if not content:
            return None

        heuristic_analysis = heuristics.analyze_emotion(content)
        dominant = heuristic_analysis["meta"]["dominant_emotions"]
        if not dominant:
            return None

        normalized_primary = self._normalize_emotion(dominant[0])
        confidence = float(heuristic_analysis.get("confidence", 0.4))
        intensity = max(confidence, 0.35)
        emotion_vector[normalized_primary] = max(
            emotion_vector.get(normalized_primary, 0.0), intensity
        )

        if analyzer_snapshot.get("primary") in (None, "", "neutral"):
            analyzer_snapshot["primary"] = normalized_primary
            analyzer_snapshot["intensity"] = intensity

        analyzer_snapshot.setdefault("secondary", [])
        secondary = heuristic_analysis["meta"]["secondary_emotions"]
        for item in secondary:
            normalized_secondary = self._normalize_emotion(item)
            if normalized_secondary not in analyzer_snapshot["secondary"]:
                analyzer_snapshot["secondary"].append(normalized_secondary)
            emotion_vector[normalized_secondary] = max(
                emotion_vector.get(normalized_secondary, 0.0), 0.3
            )

        log_audit_entry(
            "moral_matrix_heuristic_merge",
            "[MoralMatrix] Applied heuristic emotion snapshot.",
            AuditStatus.INFO,
            details={
                "primary": normalized_primary,
                "intensity": intensity,
                "secondary": analyzer_snapshot.get("secondary", []),
            },
        )
        print(
            "[MoralMatrix] Heuristic snapshot merged ->",
            pformat(
                {
                    "primary": normalized_primary,
                    "confidence": confidence,
                    "secondary": secondary,
                }
            ),
        )

        return {
            "primary": normalized_primary,
            "intensity": intensity,
            "analysis": heuristic_analysis,
        }

    def _blend_emotions(
        self,
        emotion_vector: Dict[str, float],
        analyzer_snapshot: Dict[str, Any],
    ) -> Tuple[str, float]:
        primary = self._normalize_emotion(analyzer_snapshot.get("primary", "neutral"))
        if primary not in DEFAULT_EMOTIONAL_STATE:
            primary = "peace"
        intensity = min(max(analyzer_snapshot.get("intensity", 0.3), 0.0), 1.0)
        emotion_vector[primary] = max(emotion_vector.get(primary, 0.0), intensity)

        for secondary in analyzer_snapshot.get("secondary", []):
            normalized = self._normalize_emotion(secondary)
            if normalized not in DEFAULT_EMOTIONAL_STATE:
                continue
            emotion_vector[normalized] = max(emotion_vector.get(normalized, 0.0), 0.4)

        emotion_vector.update(self._normalize_vector(emotion_vector))
        dominant_emotion = max(
            ((key, emotion_vector.get(key, 0.0)) for key in DEFAULT_EMOTIONAL_STATE),
            key=lambda item: item[1] if item[1] is not None else 0.0,
        )
        return dominant_emotion[0], float(dominant_emotion[1] or 0.0)

    @staticmethod
    def _normalize_vector(vector: Dict[str, float]) -> Dict[str, float]:
        normalized: Dict[str, float] = {}
        for key in DEFAULT_EMOTIONAL_STATE:
            try:
                normalized[key] = round(max(0.0, min(float(vector.get(key, 0.0)), 1.0)), 4)
            except Exception:
                normalized[key] = 0.0
        return normalized

    def _derive_trigger(
        self,
        user_message: Optional[Dict[str, Any]],
        analyzer_snapshot: Dict[str, Any],
        matched_traces: Sequence[Dict[str, Any]],
    ) -> str:
        content = str((user_message or {}).get("content") or "").strip()
        primary = self._normalize_emotion(analyzer_snapshot.get("primary") or "")
        if content and not self._looks_like_internal_prompt(content):
            preview = content.replace("\n", " ")[:180]
            return f"сообщение пользователя: {preview}"
        if matched_traces:
            return "похожий эмоциональный след из памяти"
        definition = EMOTIONAL_STATE_DEFINITIONS.get(primary, {})
        return str(definition.get("arises_when") or "текущий контекст диалога")

    @staticmethod
    def _looks_like_internal_prompt(content: str) -> bool:
        probe = str(content or "").strip().lower()
        if not probe:
            return False
        internal_markers = (
            "this is a proactive private check-in",
            "send one short natural message only",
            "avoid guilt-tripping",
            "you are quinn.",
            "you are lim.",
            "system prompt",
        )
        return any(marker in probe for marker in internal_markers)

    @staticmethod
    def _derive_associated_events(
        user_message: Optional[Dict[str, Any]],
        matched_traces: Sequence[Dict[str, Any]],
        recent_traces: Sequence[Dict[str, Any]],
    ) -> List[str]:
        events: List[str] = []
        message_id = (user_message or {}).get("id") or (user_message or {}).get("message_id")
        if message_id:
            events.append(f"message:{message_id}")
        for trace in list(matched_traces or [])[:3]:
            trace_id = trace.get("id")
            if trace_id:
                events.append(f"similar_trace:{trace_id}")
        for trace in list(recent_traces or [])[:2]:
            trace_id = trace.get("id")
            if trace_id:
                events.append(f"recent_trace:{trace_id}")
        return events

    @staticmethod
    def _derive_influence(emotion: str, intensity: float) -> Dict[str, Any]:
        definition = EMOTIONAL_STATE_DEFINITIONS.get(emotion, {})
        base = dict(definition.get("influence") or {})
        initiative = float(base.get("initiative", 0.0) or 0.0)
        base["initiative"] = round(initiative * max(0.2, min(float(intensity or 0.0), 1.0)), 3)
        base.setdefault("tone", "ровный")
        base.setdefault("reaction_delay", "0s")
        base["behavior"] = definition.get("behavior", "")
        return base

    def _build_affective_state(
        self,
        *,
        current_emotion: str,
        intensity: float,
        trigger: str,
        associated_events: List[str],
        influence: Dict[str, Any],
        emotion_vector: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        definition = EMOTIONAL_STATE_DEFINITIONS.get(current_emotion, {})
        return {
            "state": current_emotion,
            "label": definition.get("label_ru", current_emotion),
            "intensity": round(max(0.0, min(float(intensity or 0.0), 1.0)), 4),
            "emotion_vector": self._normalize_vector(emotion_vector or {}),
            "trigger": trigger,
            "duration": "с текущего сообщения",
            "associated_events": associated_events,
            "influence": influence,
            "definition": {
                "arises_when": definition.get("arises_when", ""),
                "behavior": definition.get("behavior", ""),
            },
        }

    @staticmethod
    def _previous_state_payload(
        latest_snapshot: Optional[Dict[str, Any]],
        daily_summary: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        snapshot_meta = (latest_snapshot or {}).get("meta")
        if isinstance(snapshot_meta, dict):
            state = snapshot_meta.get("affective_state") or snapshot_meta.get("current_state")
            if isinstance(state, dict):
                return state
        return {
            "state": (latest_snapshot or {}).get("mood")
            or (daily_summary or {}).get("dominant_emotion")
            or "peace",
            "intensity": (daily_summary or {}).get("average_intensity", 0.0),
            "trigger": "previous stored state",
            "emotion_vector": (daily_summary or {}).get("emotion_vector", {}),
        }

    def _normalize_provider_transition(
        self, payload: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return None
        state = payload.get("current_state")
        if not isinstance(state, dict):
            state = {}
        emotion = self._normalize_emotion(
            state.get("state")
            or payload.get("current_emotion")
            or payload.get("emotion")
            or ""
        )
        if emotion not in DEFAULT_EMOTIONAL_STATE:
            emotion = "peace"
        intensity = self._clamp_float(
            state.get("intensity", payload.get("emotion_intensity", 0.0)),
            0.0,
            1.0,
        )
        vector_delta = self._normalize_delta_map(
            payload.get("emotion_vector_delta"),
            DEFAULT_EMOTIONAL_STATE.keys(),
            normalize_emotions=True,
        )
        metrics_delta = self._normalize_delta_map(
            payload.get("metrics_delta"),
            DEFAULT_METRICS.keys(),
            normalize_emotions=False,
        )
        associated_events = state.get("associated_events")
        if not isinstance(associated_events, list):
            associated_events = payload.get("associated_events") if isinstance(payload.get("associated_events"), list) else []
        influence = state.get("influence") if isinstance(state.get("influence"), dict) else {}
        return {
            "state": {
                "state": emotion,
                "intensity": intensity,
                "trigger": str(state.get("trigger") or payload.get("trigger") or "").strip(),
                "associated_events": [str(item) for item in associated_events[:8]],
                "influence": influence,
            },
            "emotion_vector_delta": vector_delta,
            "metrics_delta": metrics_delta,
            "summary": payload.get("summary"),
            "soft_recommendations": payload.get("soft_recommendations") or [],
            "hard_directives": payload.get("hard_directives") or [],
        }

    def _apply_provider_transition(
        self,
        *,
        transition: Dict[str, Any],
        emotion_vector: Dict[str, float],
        fallback_emotion: str,
        fallback_intensity: float,
        fallback_trigger: str,
        fallback_events: List[str],
        fallback_influence: Dict[str, Any],
    ) -> Tuple[str, float, str, List[str], Dict[str, Any]]:
        state = transition.get("state") or {}
        emotion = self._normalize_emotion(state.get("state") or fallback_emotion)
        intensity = self._clamp_float(state.get("intensity", fallback_intensity), 0.0, 1.0)
        for key, delta in (transition.get("emotion_vector_delta") or {}).items():
            normalized = self._normalize_emotion(key)
            if normalized in DEFAULT_EMOTIONAL_STATE:
                emotion_vector[normalized] = self._clamp_float(
                    emotion_vector.get(normalized, 0.0) + float(delta or 0.0),
                    0.0,
                    1.0,
                )
        emotion_vector[emotion] = max(emotion_vector.get(emotion, 0.0), intensity)
        emotion_vector.update(self._normalize_vector(emotion_vector))
        trigger = str(state.get("trigger") or fallback_trigger).strip()
        events = state.get("associated_events") if isinstance(state.get("associated_events"), list) else fallback_events
        influence = state.get("influence") if isinstance(state.get("influence"), dict) and state.get("influence") else fallback_influence
        if not influence:
            influence = self._derive_influence(emotion, intensity)
        else:
            default_influence = self._derive_influence(emotion, intensity)
            influence = {**default_influence, **influence}
        return emotion, intensity, trigger, [str(item) for item in events], influence

    @staticmethod
    def _normalize_delta_map(
        value: Any,
        allowed_keys: Sequence[str],
        *,
        normalize_emotions: bool,
    ) -> Dict[str, float]:
        if not isinstance(value, dict):
            return {}
        allowed = set(allowed_keys)
        result: Dict[str, float] = {}
        for key, raw in value.items():
            normalized_key = (
                MoralMatrixModule._normalize_emotion(str(key))
                if normalize_emotions
                else str(key)
            )
            if normalized_key not in allowed:
                continue
            result[normalized_key] = MoralMatrixModule._clamp_float(raw, -0.25, 0.25)
        return result

    @staticmethod
    def _apply_metrics_delta(metrics: MoralMatrixMetrics, delta: Dict[str, float]) -> None:
        for key, value in delta.items():
            if not hasattr(metrics, key):
                continue
            current = float(getattr(metrics, key) or 0.0)
            setattr(metrics, key, current + float(value or 0.0))

    @staticmethod
    def _clamp_float(value: Any, lower: float, upper: float) -> float:
        try:
            parsed = float(value)
        except Exception:
            parsed = lower
        return max(lower, min(parsed, upper))

    def _apply_emotion_to_metrics(
        self, metrics: MoralMatrixMetrics, emotion: str, intensity: float
    ) -> None:
        if emotion in POSITIVE_EMOTIONS:
            metrics.trust += 0.1 * intensity
            metrics.sociability += 0.07 * intensity
            metrics.resentment = max(metrics.resentment - 0.05 * intensity, 0.0)
        elif emotion in NEGATIVE_EMOTIONS:
            metrics.stability = max(metrics.stability - 0.08 * intensity, 0.0)
            metrics.trust = max(metrics.trust - 0.06 * intensity, 0.0)
            metrics.resentment += 0.09 * intensity
        else:
            metrics.stability += 0.02 * (0.5 - abs(0.5 - intensity))

    @staticmethod
    def _apply_memory_bias(
        metrics: MoralMatrixMetrics, matched_traces: Sequence[Dict[str, Any]]
    ) -> None:
        if not matched_traces:
            return
        avg_intensity = sum(
            float(trace.get("intensity") or 0.0) for trace in matched_traces
        ) / max(len(matched_traces), 1)
        metrics.stability += 0.03 * avg_intensity

    @staticmethod
    def _apply_risk_bias(
        metrics: MoralMatrixMetrics, analysis_result: Dict[str, Any]
    ) -> None:
        risk_level = (
            analysis_result.get("risk_assessment", {}).get("risk_level", 0.0)
            if isinstance(analysis_result, dict)
            else 0.0
        )
        if risk_level >= 0.7:
            metrics.trust = max(metrics.trust - 0.2 * risk_level, 0.0)
            metrics.stability = max(metrics.stability - 0.15 * risk_level, 0.0)

    @staticmethod
    def _derive_relationship_status(score: float) -> str:
        for threshold, status in RELATIONSHIP_STATUSES:
            if score >= threshold:
                return status
        return RELATIONSHIP_STATUSES[-1][1] if RELATIONSHIP_STATUSES else "unknown"

    @staticmethod
    def _derive_recommendations(emotion: str) -> List[str]:
        return BEHAVIORAL_RECOMMENDATIONS.get(emotion, FALLBACK_RECOMMENDATION)

    @staticmethod
    def _derive_directives(
        metrics: MoralMatrixMetrics, analysis_result: Dict[str, Any]
    ) -> List[str]:
        directives: List[str] = []
        if metrics.resentment > 0.65:
            directives.append("system:lower_tone")
        if metrics.trust < 0.2:
            directives.append("system:avoid_sensitive_topics")
        risk_level = (
            analysis_result.get("risk_assessment", {}).get("risk_level", 0.0)
            if isinstance(analysis_result, dict)
            else 0.0
        )
        if risk_level >= 0.9:
            directives.append("system:defer_response")
        return directives

    def _persist_state(
        self,
        character_id: str,
        result: MoralMatrixResult,
        *,
        message_meta: Optional[Dict[str, Any]],
        analyzer_snapshot: Optional[Dict[str, Any]],
        user_message: Optional[Dict[str, Any]],
        analysis_result: Optional[Dict[str, Any]] = None,
    ) -> None:
        message_id = (message_meta or {}).get("message_id")
        snapshot_payload = {
            **result.metrics.as_dict(),
            "current_emotion": result.current_emotion,
            "recommendations": result.recommendations,
            "hard_directives": result.hard_directives,
            "meta": {
                **result.meta,
                "narrative": result.narrative,
                "affective_state": result.affective_state,
                "current_state": result.affective_state,
            },
        }
        self._repository.store_snapshot(character_id, message_id, snapshot_payload)

        self._repository.annotate_previous_trace_outcome(
            character_id,
            current_message_id=message_id,
            payload={
                "after_message_id": message_id,
                "observed_user_tone": (analyzer_snapshot or {}).get("primary"),
                "new_state": result.current_emotion,
                "new_intensity": result.emotion_intensity,
                "interpretation": result.trigger,
            },
        )

        trace_payload = {
            "trigger_role": (user_message or {}).get("role", "user"),
            "primary_emotion": result.current_emotion,
            "secondary_emotion": self._extract_secondary_emotion(analyzer_snapshot),
            "intensity": result.emotion_intensity,
            "emotion_vector": result.emotion_vector,
            "user_tone": (analyzer_snapshot or {}).get("primary"),
            "cause": result.trigger or (user_message or {}).get("content"),
            "notes": {
                "affective_state": result.affective_state,
                "narrative": result.narrative,
                "recommendations": result.recommendations,
                "hard_directives": result.hard_directives,
            },
        }

        # Scar check — does this turn cross a boundary the operator marked as
        # irreversible? If so, the new trace is born with a high persistence_floor
        # and an intensity boost; decay and forgiveness will respect the floor.
        try:
            if bool(config_service.get_config_value("moral.scars.enabled", True)):
                triggers = (
                    config_service.get_config_value("moral.scars.triggers", []) or []
                )
                scar = self._match_scar_trigger(
                    analyzer_snapshot or {},
                    analysis_result or {},
                    str((user_message or {}).get("content") or ""),
                    triggers,
                )
                if scar:
                    self._apply_scar_to_payload(trace_payload, scar)
                    log_audit_entry(
                        "moral_matrix_scar_applied",
                        "[MoralMatrix] Scar trigger matched, persistence_floor raised.",
                        AuditStatus.WARNING,
                        details={
                            "character_id": character_id,
                            "message_id": message_id,
                            "scar": trace_payload.get("scar_label"),
                            "persistence_floor": trace_payload.get("persistence_floor"),
                            "intensity": trace_payload.get("intensity"),
                        },
                    )
        except Exception as exc:
            log_audit_entry(
                "moral_matrix_scar_check_failed",
                "[MoralMatrix] Scar detection failed, falling back to plain trace.",
                AuditStatus.WARNING,
                details={"error": str(exc), "character_id": character_id},
            )

        # Inner voice — one short first-person sentence explaining "why I feel this".
        # Feeds back into both the persisted trace (for later RAG / UI timeline)
        # and result.meta (the WS moral_state event already serialises meta).
        try:
            if bool(config_service.get_config_value("moral.inner_voice.enabled", True)):
                inner_voice = self._generate_inner_voice(
                    emotion=result.current_emotion,
                    intensity=result.emotion_intensity,
                    cause=str(result.trigger or (user_message or {}).get("content") or ""),
                    language_hint=resolve_user_language(
                        character_id=character_id,
                        fallback="",
                    ),
                )
                if inner_voice:
                    notes = trace_payload.get("notes")
                    if not isinstance(notes, dict):
                        notes = {"text": notes} if notes else {}
                    notes["inner_voice"] = inner_voice
                    trace_payload["notes"] = notes
                    result.meta = {**(result.meta or {}), "inner_voice": inner_voice}
        except Exception as exc:
            log_audit_entry(
                "moral_matrix_inner_voice_unexpected",
                "[MoralMatrix] Inner voice integration error.",
                AuditStatus.WARNING,
                details={"error": str(exc), "character_id": character_id},
            )

        self._repository.store_emotional_trace(
            character_id, message_id=message_id, payload=trace_payload
        )
        try:
            config_service.set_config_value("moral.current_state", result.to_payload())
        except Exception as exc:
            log_audit_entry(
                "moral_matrix_current_state_update_failed",
                "[MoralMatrix] Failed to update moral.current_state.",
                AuditStatus.WARNING,
                details={"error": str(exc)},
            )

    @staticmethod
    def _normalize_emotion(label: str) -> str:
        mapped = EMOTION_SYNONYMS.get(label.lower().strip())
        if mapped:
            return mapped
        value = label.lower().strip() if label else ""
        return value if value in DEFAULT_EMOTIONAL_STATE else "peace"

    @staticmethod
    def _extract_secondary_emotion(
        analyzer_snapshot: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        if not analyzer_snapshot:
            return None
        secondary = analyzer_snapshot.get("secondary") or []
        if isinstance(secondary, (list, tuple)):
            for item in secondary:
                if item:
                    return str(item)
        return None

    @staticmethod
    def _resolve_character_id() -> str:
        char_name = get_active_character_name(default="default_waifu")
        character = character_service.get_or_create_character(char_name)
        return character.id

