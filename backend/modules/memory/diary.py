from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.orm import joinedload

from constants.prompts import (
    DAILY_ACTIVITY_DIARY_SYSTEM_PROMPT,
    DAILY_ACTIVITY_DIARY_USER_PROMPT_TEMPLATE,
    MEMORY_JUDGE_CONTRADICTION_PROMPT,
)
from modules.database.core import SessionLocal, engine
from models.models import History
from modules.generative.manager import NoProviderResolved, generation_manager
from modules.generative.types import GenerateRequest
from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry


@dataclass(slots=True)
class DiaryEntry:
    id: str
    character_id: str
    day: str
    mood: str
    summary: str
    tags: list[str]
    stats: dict[str, Any]
    payload: dict[str, Any]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def generate_daily_activity_entry(
    *,
    character_id: str,
    target_day: date | None = None,
    force: bool = False,
) -> dict[str, Any]:
    day = target_day or datetime.now(timezone.utc).date()
    if not force:
        existing = get_daily_activity_entry(character_id=character_id, target_day=day)
        if existing:
            return {"generated": False, "entry": existing.to_dict()}

    rows = _load_day_rows(character_id=character_id, day=day)
    stats = _build_day_activity_stats(rows)
    transcript = _build_activity_transcript(rows)
    summary_payload = _summarize_activity(day=day, stats=stats, transcript=transcript)

    entry = _upsert_diary_entry(
        character_id=character_id,
        day=day,
        mood=summary_payload["mood"],
        summary=summary_payload["summary"],
        tags=summary_payload["tags"],
        stats=stats,
        payload={
            "transcript_preview": transcript[:2400],
            "messages_used": len(rows),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "structured": _build_structured_payload(
                day=day,
                stats=stats,
                summary_payload=summary_payload,
            ),
        },
    )
    return {"generated": True, "entry": entry.to_dict()}


def _judge_settings() -> dict[str, Any]:
    cfg = config_service.get_config_value("memory.consolidation.judge", {}) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "provider": str(cfg.get("provider") or "ollama").strip().lower(),
        "model": str(cfg.get("model") or "").strip(),
        "temperature": float(cfg.get("temperature", 0.0) or 0.0),
        "max_tokens": int(cfg.get("max_tokens", 512) or 512),
        "request_timeout": float(cfg.get("request_timeout", 60) or 60),
    }


def _call_judge_llm(*, payload: dict[str, Any], settings: dict[str, Any]) -> str | None:
    """Send the judge prompt + payload to the configured provider.

    Returns the assistant text or None if the provider is unavailable. The
    caller decides whether a missing response should skip or fail the
    consolidation step.
    """
    messages = [
        {"role": "system", "content": MEMORY_JUDGE_CONTRADICTION_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]
    provider = settings["provider"]

    try:
        if provider == "ollama":
            from modules.ollama import client as ollama_client

            response = ollama_client.chat(
                messages,
                {
                    "temperature": settings["temperature"],
                    "max_tokens": settings["max_tokens"],
                    "__think": False,
                },
                model=settings["model"] or None,
            )
            return str(
                (response.get("message", {}) or {}).get("content", "")
                if isinstance(response, dict) else ""
            )

        if provider == "llama_cpp":
            from modules.llama_cpp import client as llama_client

            base_url = str(
                config_service.get_config_value(
                    "api.providers.llama_cpp.base_url",
                    "http://127.0.0.1:8080",
                )
                or "http://127.0.0.1:8080"
            )
            response = llama_client.chat_completion(
                base_url=base_url,
                messages=messages,
                model=settings["model"] or None,
                sampler={
                    "temperature": settings["temperature"],
                    "max_tokens": settings["max_tokens"],
                },
                timeout=settings["request_timeout"],
                purpose="memory_judge",
            )
            choices = response.get("choices") or []
            first = choices[0] if isinstance(choices, list) and choices else {}
            return str(
                (first.get("message", {}) if isinstance(first, dict) else {}).get("content", "")
            )

    except Exception as exc:
        log_audit_entry(
            "memory_judge_provider_error",
            "[Diary] Memory judge provider failed.",
            AuditStatus.WARNING,
            details={"provider": provider, "error": str(exc)},
        )
        return None

    log_audit_entry(
        "memory_judge_provider_unsupported",
        "[Diary] Memory judge provider not supported.",
        AuditStatus.WARNING,
        details={"provider": provider},
    )
    return None


def _parse_judge_response(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    text_raw = str(raw).strip()
    # Tolerate fenced output.
    if text_raw.startswith("```"):
        text_raw = text_raw.split("```", 1)[1]
        if text_raw.startswith("json"):
            text_raw = text_raw[4:]
        text_raw = text_raw.split("```", 1)[0]
    text_raw = text_raw.strip()
    try:
        payload = json.loads(text_raw)
    except Exception:
        # Try to recover the JSON object from surrounding prose.
        start = text_raw.find("{")
        end = text_raw.rfind("}")
        if start < 0 or end <= start:
            return []
        try:
            payload = json.loads(text_raw[start : end + 1])
        except Exception:
            return []
    if not isinstance(payload, dict):
        return []
    matches = payload.get("matches")
    if not isinstance(matches, list):
        return []
    out: list[dict[str, Any]] = []
    valid_actions = {"supersede", "merge", "keep_both", "skip"}
    for item in matches:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "").strip().lower()
        if action not in valid_actions:
            continue
        out.append(
            {
                "entry_id": str(item.get("entry_id") or "").strip(),
                "action": action,
                "note": str(item.get("note") or "").strip()[:400],
            }
        )
    return out


def _resolve_importance_threshold() -> float:
    """Lower bound for diary entry importance.

    Anything below this is flagged as ``payload.pruned`` by sleep consolidation
    and hidden from default reads. 0.0 disables the filter. Negative / invalid
    values clamp to 0.0.
    """
    raw = config_service.get_config_value("memory.consolidation.importance_threshold", 0.2)
    try:
        value = float(raw if raw is not None else 0.2)
    except (TypeError, ValueError):
        value = 0.2
    return max(0.0, min(value, 1.0))


def run_sleeping_consolidation(
    *,
    character_id: str,
    lookback_days: int = 14,
) -> dict[str, Any]:
    days = max(2, min(int(lookback_days or 14), 120))
    # Include pruned here so consolidation can re-evaluate them as the threshold
    # shifts. Reads after consolidation use the default include_pruned=False.
    entries = list_daily_activity_entries(
        character_id=character_id,
        days=days,
        include_pruned=True,
    )
    if not entries:
        return {
            "consolidated": False,
            "updated_entries": 0,
            "reason": "no_diary_entries",
            "lookback_days": days,
        }

    importance_threshold = _resolve_importance_threshold()

    sig_map: dict[str, list[str]] = {}
    tag_counter: dict[str, int] = {}
    for entry in entries:
        signature = _signature_text(entry.summary)
        if signature:
            sig_map.setdefault(signature, []).append(entry.id)
        for tag in entry.tags:
            tag_norm = str(tag or "").strip().lower()
            if tag_norm:
                tag_counter[tag_norm] = tag_counter.get(tag_norm, 0) + 1

    anchor_tags = [tag for tag, count in sorted(tag_counter.items(), key=lambda p: (-p[1], p[0])) if count >= 2][:8]
    updated = 0
    pruned_count = 0
    unpruned_count = 0
    judge_settings = _judge_settings()
    judge_invocations = 0
    judge_actions = {"supersede": 0, "merge": 0, "keep_both": 0, "skip": 0}
    # Build a lookup of all entries by id so the resolver can apply actions
    # against earlier rows in this same pass.
    entries_by_id: dict[str, DiaryEntry] = {e.id: e for e in entries}
    overrides: dict[str, dict[str, Any]] = {}  # entry_id -> patch dict for payload
    for entry in entries:
        signature = _signature_text(entry.summary)
        duplicate_ids = [
            item for item in sig_map.get(signature, []) if item != entry.id
        ] if signature else []
        confidence = _estimate_diary_confidence(entry)
        payload = dict(entry.payload or {})
        payload["consolidation"] = {
            "version": 1,
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "lookback_days": days,
            "confidence": confidence,
            "summary_signature": signature,
            "duplicate_entry_ids": duplicate_ids[:12],
            "anchor_tags": anchor_tags,
            "importance_threshold": importance_threshold,
        }

        importance_score = _coerce_float((payload or {}).get("importance_score"))
        existing_pruned = payload.get("pruned") if isinstance(payload.get("pruned"), dict) else None

        if (
            importance_threshold > 0.0
            and importance_score is not None
            and importance_score < importance_threshold
        ):
            if not existing_pruned:
                pruned_count += 1
            payload["pruned"] = {
                "reason": "low_importance",
                "score": importance_score,
                "threshold": importance_threshold,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        elif existing_pruned and existing_pruned.get("reason") == "low_importance":
            # Threshold lowered or importance re-rated upward — un-prune.
            payload.pop("pruned", None)
            unpruned_count += 1

        # Contradiction resolver — only fires when both the user opted in via
        # config and the summariser flagged contradictions for this entry.
        raw_contradictions = payload.get("contradictions") if isinstance(payload, dict) else None
        contradiction_notes = (
            [str(item).strip() for item in raw_contradictions if str(item).strip()]
            if isinstance(raw_contradictions, list)
            else []
        )
        if judge_settings["enabled"] and contradiction_notes:
            # Candidate set: every other (older) entry, capped to keep the prompt cheap.
            recent_candidates = [
                {
                    "id": other.id,
                    "day": str(other.day),
                    "summary": str(other.summary or "")[:600],
                }
                for other in entries
                if other.id != entry.id
            ][:25]
            judge_payload = {
                "new_entry": {
                    "id": entry.id,
                    "day": str(entry.day),
                    "summary": str(entry.summary or "")[:1200],
                    "contradictions": contradiction_notes[:10],
                },
                "recent_entries": recent_candidates,
            }
            raw_response = _call_judge_llm(payload=judge_payload, settings=judge_settings)
            matches = _parse_judge_response(raw_response)
            judge_invocations += 1
            applied: list[dict[str, Any]] = []
            for match in matches:
                action = match["action"]
                judge_actions[action] = judge_actions.get(action, 0) + 1
                target_id = match["entry_id"]
                if action == "skip" or not target_id or target_id not in entries_by_id:
                    applied.append(match)
                    continue
                if action == "supersede":
                    # Mark the older entry as superseded; the new one wins.
                    overrides.setdefault(target_id, {})["pruned"] = {
                        "reason": "superseded_by",
                        "by_entry_id": entry.id,
                        "note": match.get("note", ""),
                        "at": datetime.now(timezone.utc).isoformat(),
                    }
                elif action == "merge":
                    # Record a back-link on the new entry. No deletion.
                    merged_from = list(payload.get("merged_from") or [])
                    if target_id not in merged_from:
                        merged_from.append(target_id)
                    payload["merged_from"] = merged_from[:20]
                # keep_both: nothing to do beyond bookkeeping.
                applied.append(match)
            if applied:
                payload["consolidation"]["judge"] = {
                    "ran_at": datetime.now(timezone.utc).isoformat(),
                    "provider": judge_settings["provider"],
                    "model": judge_settings["model"],
                    "matches": applied,
                }

        merged_tags = _merge_tags(entry.tags, anchor_tags)
        target_day = date.fromisoformat(str(entry.day))
        _upsert_diary_entry(
            character_id=entry.character_id,
            day=target_day,
            mood=entry.mood,
            summary=entry.summary,
            tags=merged_tags,
            stats=dict(entry.stats or {}),
            payload=payload,
        )
        updated += 1

    # Apply judge-induced overrides (supersede markers) to older entries that
    # already passed through the main loop. We do this in a second pass so the
    # first pass can freely build payload.consolidation without racing.
    superseded_count = 0
    for target_id, patch in overrides.items():
        target_entry = entries_by_id.get(target_id)
        if not target_entry:
            continue
        target_payload = dict(target_entry.payload or {})
        existing_pruned = target_payload.get("pruned") if isinstance(target_payload.get("pruned"), dict) else None
        if existing_pruned and existing_pruned.get("reason") not in {None, "low_importance"}:
            # Do not stomp on archival reasons set by users or other workflows.
            continue
        target_payload["pruned"] = patch["pruned"]
        target_day = date.fromisoformat(str(target_entry.day))
        _upsert_diary_entry(
            character_id=target_entry.character_id,
            day=target_day,
            mood=target_entry.mood,
            summary=target_entry.summary,
            tags=list(target_entry.tags or []),
            stats=dict(target_entry.stats or {}),
            payload=target_payload,
        )
        superseded_count += 1
        if not existing_pruned:
            pruned_count += 1

    log_audit_entry(
        "daily_activity_diary_consolidation_complete",
        "[Diary] Sleeping consolidation complete.",
        AuditStatus.INFO,
        details={
            "character_id": character_id,
            "lookback_days": days,
            "entries_seen": len(entries),
            "entries_updated": updated,
            "entries_pruned": pruned_count,
            "entries_unpruned": unpruned_count,
            "importance_threshold": importance_threshold,
            "anchor_tags": anchor_tags,
            "judge_enabled": judge_settings["enabled"],
            "judge_invocations": judge_invocations,
            "judge_actions": judge_actions,
            "entries_superseded": superseded_count,
        },
    )
    return {
        "consolidated": True,
        "updated_entries": updated,
        "entries_seen": len(entries),
        "entries_pruned": pruned_count,
        "entries_unpruned": unpruned_count,
        "importance_threshold": importance_threshold,
        "lookback_days": days,
        "anchor_tags": anchor_tags,
        "judge_enabled": judge_settings["enabled"],
        "judge_invocations": judge_invocations,
        "judge_actions": judge_actions,
        "entries_superseded": superseded_count,
    }


def list_daily_activity_entries(
    *,
    character_id: str,
    days: int = 30,
    include_pruned: bool = False,
) -> list[DiaryEntry]:
    """List diary entries for the character.

    ``include_pruned`` controls whether entries flagged by sleep consolidation
    as low-importance (see ``payload.pruned``) are returned. Defaults to
    ``False`` so callers building RAG/diary context get a clean feed without
    having to filter themselves. Set True for admin / debug views.
    """
    days = max(1, min(int(days or 30), 365))
    since_day = datetime.now(timezone.utc).date() - timedelta(days=days - 1)
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, character_id, day, mood, summary, tags, stats, payload, created_at, updated_at
                FROM daily_activity_diary
                WHERE character_id = :character_id
                  AND day >= :since_day
                ORDER BY day DESC
                """
            ),
            {"character_id": character_id, "since_day": since_day.isoformat()},
        ).fetchall()
    entries = [_row_to_entry(row) for row in rows]
    if include_pruned:
        return entries
    return [entry for entry in entries if not _is_entry_pruned(entry)]


def _is_entry_pruned(entry: DiaryEntry) -> bool:
    payload = entry.payload if isinstance(entry.payload, dict) else {}
    pruned = payload.get("pruned") if isinstance(payload, dict) else None
    return isinstance(pruned, dict) and bool(pruned.get("reason"))


def get_daily_activity_entry(
    *,
    character_id: str,
    target_day: date,
) -> DiaryEntry | None:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, character_id, day, mood, summary, tags, stats, payload, created_at, updated_at
                FROM daily_activity_diary
                WHERE character_id = :character_id AND day = :day
                LIMIT 1
                """
            ),
            {"character_id": character_id, "day": target_day.isoformat()},
        ).fetchone()
    if not row:
        return None
    return _row_to_entry(row)


def _load_day_rows(*, character_id: str, day: date) -> list[History]:
    day_start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    session = SessionLocal()
    try:
        rows = (
            session.query(History)
            .options(joinedload(History.media))
            .filter(
                History.character_id == character_id,
                History.timestamp >= day_start,
                History.timestamp < day_end,
            )
            .order_by(History.timestamp.asc())
            .all()
        )
        return rows
    finally:
        session.close()


def _build_day_activity_stats(rows: Iterable[History]) -> dict[str, Any]:
    by_role: dict[str, int] = {}
    by_transport: dict[str, int] = {}
    by_event: dict[str, int] = {}
    tg_chats: set[int] = set()
    media_count = 0

    total = 0
    for row in rows:
        total += 1
        role = str(getattr(row, "role", "") or "unknown").strip().lower()
        by_role[role] = by_role.get(role, 0) + 1

        runtime_meta = _parse_runtime_meta(getattr(row, "runtime_meta", "{}"))
        transport = runtime_meta.get("transport") if isinstance(runtime_meta, dict) else {}
        transport_name = str((transport or {}).get("name") or "unknown").strip().lower()
        by_transport[transport_name] = by_transport.get(transport_name, 0) + 1

        event_name = str(runtime_meta.get("event") or "message").strip().lower()
        by_event[event_name] = by_event.get(event_name, 0) + 1

        if transport_name == "telegram":
            chat_id = (transport or {}).get("chat_id")
            try:
                if chat_id is not None:
                    tg_chats.add(int(chat_id))
            except Exception:
                pass

        media = list(getattr(row, "media", []) or [])
        media_count += len(media)

    return {
        "total_messages": total,
        "by_role": by_role,
        "by_transport": by_transport,
        "by_event": by_event,
        "telegram_chats_touched": len(tg_chats),
        "media_items": media_count,
    }


def _build_activity_transcript(rows: Iterable[History]) -> str:
    chunks: list[str] = []
    for row in rows:
        timestamp = getattr(row, "timestamp", None)
        ts = (
            timestamp.astimezone(timezone.utc).strftime("%H:%M")
            if isinstance(timestamp, datetime)
            else "--:--"
        )
        role = str(getattr(row, "role", "unknown") or "unknown").strip().lower()
        content = str(getattr(row, "content", "") or "").strip().replace("\n", " ")
        if len(content) > 240:
            content = content[:237] + "..."

        runtime_meta = _parse_runtime_meta(getattr(row, "runtime_meta", "{}"))
        transport = runtime_meta.get("transport") if isinstance(runtime_meta, dict) else {}
        transport_name = str((transport or {}).get("name") or "unknown").strip().lower()
        event_name = str(runtime_meta.get("event") or "message").strip().lower()
        chat_id = (transport or {}).get("chat_id")
        chat_fragment = f" chat={chat_id}" if chat_id is not None else ""

        chunks.append(
            f"[{ts}] ({transport_name}{chat_fragment}) {role} [{event_name}]: {content}"
        )

    if not chunks:
        return "No activity for this day."
    return "\n".join(chunks[:280])


def _summarize_activity(
    *,
    day: date,
    stats: dict[str, Any],
    transcript: str,
) -> dict[str, Any]:
    user = DAILY_ACTIVITY_DIARY_USER_PROMPT_TEMPLATE.format(
        day=day.isoformat(),
        stats_json=json.dumps(stats, ensure_ascii=False),
        transcript=transcript[:12000],
    )
    try:
        result = generation_manager.generate(
            GenerateRequest(
                messages=[
                    {"role": "system", "content": DAILY_ACTIVITY_DIARY_SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
                options={"temperature": 0.2, "num_predict": 700},
                metadata={"mode": "daily_activity_diary"},
            )
        )
        raw = str(getattr(result, "content", "") or "").strip()
        if not raw:
            raw = str(getattr(result, "reasoning", "") or "").strip()
        payload = _parse_summary_json(raw)
        if payload:
            return payload
        raise ValueError("invalid diary summary json")
    except (NoProviderResolved, Exception) as exc:
        log_audit_entry(
            "daily_activity_diary_fallback",
            "[Diary] Fallback summary used.",
            AuditStatus.WARNING,
            details={"error": str(exc)},
        )
        return _fallback_summary(day=day, stats=stats)


def _parse_summary_json(raw: str) -> dict[str, Any] | None:
    text_raw = str(raw or "").strip()
    if not text_raw:
        return None
    if "```json" in text_raw:
        text_raw = text_raw.split("```json", 1)[1].split("```", 1)[0].strip()
    elif text_raw.startswith("```"):
        text_raw = text_raw.split("```", 1)[1].split("```", 1)[0].strip()

    try:
        payload = json.loads(text_raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None

    mood = str(payload.get("mood") or "neutral").strip()[:48] or "neutral"
    summary = str(payload.get("summary") or "").strip()
    tags_raw = payload.get("tags")
    if not summary:
        return None
    tags: list[str] = []
    if isinstance(tags_raw, list):
        for tag in tags_raw:
            tag_text = str(tag or "").strip().lower()
            if tag_text:
                tags.append(tag_text[:40])
    return {
        "mood": mood,
        "summary": summary[:2000],
        "tags": tags[:8],
        "title": str(payload.get("title") or "").strip()[:240],
        "source_event": str(payload.get("source_event") or "").strip()[:2000],
        "outcomes": _coerce_string_list(payload.get("outcomes"), limit=12, item_limit=600),
        "entities": _coerce_string_list(payload.get("entities"), limit=20, item_limit=120),
        "key_messages": _coerce_string_list(payload.get("key_messages"), limit=12, item_limit=600),
        "importance_score": _coerce_float(payload.get("importance_score")),
        "importance_notes": str(payload.get("importance_notes") or "").strip()[:2000],
        "emotion_valence": str(payload.get("emotion_valence") or "").strip()[:120],
        "emotion_arousal": str(payload.get("emotion_arousal") or "").strip()[:120],
        "emotion_notes": str(payload.get("emotion_notes") or "").strip()[:1200],
        "relationships": str(payload.get("relationships") or "").strip()[:1200],
        "retrieval_cues": _coerce_string_list(payload.get("retrieval_cues"), limit=16, item_limit=200),
        "similarities": _coerce_string_list(payload.get("similarities"), limit=10, item_limit=400),
        "photo_descriptions": _coerce_string_list(payload.get("photo_descriptions"), limit=12, item_limit=500),
        "contradictions": _coerce_string_list(payload.get("contradictions"), limit=10, item_limit=400),
    }


def _fallback_summary(*, day: date, stats: dict[str, Any]) -> dict[str, Any]:
    total = int(stats.get("total_messages") or 0)
    by_transport = stats.get("by_transport") if isinstance(stats, dict) else {}
    by_role = stats.get("by_role") if isinstance(stats, dict) else {}
    tg_chats = int(stats.get("telegram_chats_touched") or 0)
    media_items = int(stats.get("media_items") or 0)

    summary = (
        f"{day.isoformat()}: processed {total} activity records. "
        f"Channels: {json.dumps(by_transport or {}, ensure_ascii=False)}. "
        f"Roles: {json.dumps(by_role or {}, ensure_ascii=False)}. "
        f"Telegram chats touched: {tg_chats}. Media items: {media_items}."
    )
    tags = ["daily", "activity", "autolog"]
    if (by_transport or {}).get("telegram", 0):
        tags.append("telegram")
    if media_items > 0:
        tags.append("media")
    return {
        "mood": "focused",
        "summary": summary[:2000],
        "tags": tags,
        "title": f"{day.isoformat()} | Daily Activity Summary",
        "source_event": (
            f"Observed {total} records across transports {json.dumps(by_transport or {}, ensure_ascii=False)}."
        )[:2000],
        "outcomes": [
            f"Processed {total} activity records for the day.",
            f"Telegram chats touched: {tg_chats}.",
            f"Media items seen: {media_items}.",
        ],
        "entities": list((by_transport or {}).keys())[:10],
        "key_messages": [],
        "importance_score": round(min(1.0, 0.2 + total / 120.0), 2),
        "importance_notes": "Fallback diary was generated from transport and role statistics.",
        "emotion_valence": "neutral",
        "emotion_arousal": "medium" if total >= 20 else "low",
        "emotion_notes": "No structured model summary available; using statistical fallback.",
        "relationships": "PAI acted as observer of the day's interaction flow.",
        "retrieval_cues": [f"day:{day.isoformat()}"] + [f"transport:{key}" for key in list((by_transport or {}).keys())[:6]],
        "similarities": [],
        "photo_descriptions": [],
        "contradictions": [],
    }


def _build_structured_payload(
    *,
    day: date,
    stats: dict[str, Any],
    summary_payload: dict[str, Any],
) -> dict[str, Any]:
    title = str(summary_payload.get("title") or "").strip() or f"{day.isoformat()} | Daily Activity"
    return {
        "title": title[:240],
        "source_event": str(summary_payload.get("source_event") or "").strip(),
        "outcomes": _coerce_string_list(summary_payload.get("outcomes"), limit=12, item_limit=600),
        "entities": _coerce_string_list(summary_payload.get("entities"), limit=20, item_limit=120),
        "key_messages": _coerce_string_list(summary_payload.get("key_messages"), limit=12, item_limit=600),
        "importance_score": (
            _coerce_float(summary_payload.get("importance_score"))
            if _coerce_float(summary_payload.get("importance_score")) is not None
            else _estimate_importance_score(stats)
        ),
        "importance_notes": str(summary_payload.get("importance_notes") or "").strip(),
        "emotion": {
            "valence": str(summary_payload.get("emotion_valence") or "").strip() or "neutral",
            "arousal": str(summary_payload.get("emotion_arousal") or "").strip() or "medium",
            "notes": str(summary_payload.get("emotion_notes") or "").strip(),
        },
        "relationships": str(summary_payload.get("relationships") or "").strip(),
        "retrieval_cues": _coerce_string_list(summary_payload.get("retrieval_cues"), limit=16, item_limit=200),
        "similarities": _coerce_string_list(summary_payload.get("similarities"), limit=10, item_limit=400),
        "photo_descriptions": _coerce_string_list(summary_payload.get("photo_descriptions"), limit=12, item_limit=500),
        "contradictions": _coerce_string_list(summary_payload.get("contradictions"), limit=10, item_limit=400),
    }


def _coerce_string_list(raw: Any, *, limit: int, item_limit: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    values: list[str] = []
    for item in raw:
        text_value = str(item or "").strip()
        if text_value:
            values.append(text_value[:item_limit])
        if len(values) >= limit:
            break
    return values


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return round(float(value), 3)
    except Exception:
        return None


def _estimate_importance_score(stats: dict[str, Any]) -> float:
    total_messages = int((stats or {}).get("total_messages") or 0)
    media_items = int((stats or {}).get("media_items") or 0)
    telegram_chats = int((stats or {}).get("telegram_chats_touched") or 0)
    score = 0.18 + min(total_messages / 120.0, 0.52) + min(media_items / 15.0, 0.12) + min(telegram_chats / 10.0, 0.1)
    return round(max(0.05, min(score, 1.0)), 2)


def _signature_text(value: str) -> str:
    text_raw = str(value or "").strip().lower()
    if not text_raw:
        return ""
    text_raw = re.sub(r"\s+", " ", text_raw)
    text_raw = re.sub(r"[^a-zа-я0-9\s]", " ", text_raw, flags=re.IGNORECASE)
    words = [word for word in text_raw.split(" ") if len(word) >= 3]
    if not words:
        return ""
    return " ".join(words[:40])


def _estimate_diary_confidence(entry: DiaryEntry) -> float:
    stats = dict(entry.stats or {})
    total_messages = int(stats.get("total_messages") or 0)
    media_items = int(stats.get("media_items") or 0)
    by_transport = stats.get("by_transport") if isinstance(stats, dict) else {}
    transport_hits = int((by_transport or {}).get("telegram", 0)) + int((by_transport or {}).get("main_chat", 0))

    summary_len = len(str(entry.summary or "").strip())
    tag_count = len(list(entry.tags or []))
    score = 0.25
    score += min(total_messages / 50.0, 0.35)
    score += min(transport_hits / 50.0, 0.15)
    if tag_count >= 3:
        score += 0.1
    if media_items > 0:
        score += 0.05
    if summary_len < 80:
        score -= 0.12
    if total_messages <= 1:
        score -= 0.08
    score = max(0.05, min(score, 0.99))
    return round(score, 3)


def _merge_tags(primary: list[str], secondary: list[str]) -> list[str]:
    merged: list[str] = []
    for src in (primary or []):
        tag = str(src or "").strip().lower()
        if tag and tag not in merged:
            merged.append(tag[:40])
    for src in (secondary or []):
        tag = str(src or "").strip().lower()
        if tag and tag not in merged:
            merged.append(tag[:40])
    return merged[:12]


def _upsert_diary_entry(
    *,
    character_id: str,
    day: date,
    mood: str,
    summary: str,
    tags: list[str],
    stats: dict[str, Any],
    payload: dict[str, Any],
) -> DiaryEntry:
    now_iso = datetime.now(timezone.utc).isoformat()
    existing = get_daily_activity_entry(character_id=character_id, target_day=day)
    row_id = existing.id if existing else str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO daily_activity_diary (
                    id, character_id, day, mood, summary, tags, stats, payload, created_at, updated_at
                ) VALUES (
                    :id, :character_id, :day, :mood, :summary, :tags, :stats, :payload, :created_at, :updated_at
                )
                ON CONFLICT(character_id, day) DO UPDATE SET
                    mood = excluded.mood,
                    summary = excluded.summary,
                    tags = excluded.tags,
                    stats = excluded.stats,
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """
            ),
            {
                "id": row_id,
                "character_id": character_id,
                "day": day.isoformat(),
                "mood": str(mood or "neutral")[:48],
                "summary": str(summary or "")[:2000],
                "tags": json.dumps(tags or [], ensure_ascii=False),
                "stats": json.dumps(stats or {}, ensure_ascii=False),
                "payload": json.dumps(payload or {}, ensure_ascii=False),
                "created_at": (existing.created_at if existing else now_iso),
                "updated_at": now_iso,
            },
        )
    return get_daily_activity_entry(character_id=character_id, target_day=day) or DiaryEntry(
        id=row_id,
        character_id=character_id,
        day=day.isoformat(),
        mood=str(mood or "neutral"),
        summary=str(summary or ""),
        tags=list(tags or []),
        stats=dict(stats or {}),
        payload=dict(payload or {}),
        created_at=now_iso,
        updated_at=now_iso,
    )


def _row_to_entry(row: Any) -> DiaryEntry:
    mapping = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    return DiaryEntry(
        id=str(mapping.get("id") or ""),
        character_id=str(mapping.get("character_id") or ""),
        day=str(mapping.get("day") or ""),
        mood=str(mapping.get("mood") or "neutral"),
        summary=str(mapping.get("summary") or ""),
        tags=_safe_json_list(mapping.get("tags")),
        stats=_safe_json_dict(mapping.get("stats")),
        payload=_safe_json_dict(mapping.get("payload")),
        created_at=str(mapping.get("created_at") or ""),
        updated_at=str(mapping.get("updated_at") or ""),
    )


def _parse_runtime_meta(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text_raw = str(raw or "").strip()
    if not text_raw:
        return {}
    try:
        parsed = json.loads(text_raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _safe_json_list(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item) for item in raw]
    text_raw = str(raw or "").strip()
    if not text_raw:
        return []
    try:
        parsed = json.loads(text_raw)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _safe_json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text_raw = str(raw or "").strip()
    if not text_raw:
        return {}
    try:
        parsed = json.loads(text_raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


__all__ = [
    "DiaryEntry",
    "generate_daily_activity_entry",
    "list_daily_activity_entries",
    "get_daily_activity_entry",
    "run_sleeping_consolidation",
]
