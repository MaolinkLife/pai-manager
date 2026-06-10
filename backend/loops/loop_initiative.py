import time
from datetime import datetime, timedelta, timezone, time as dt_time
from dateutil.parser import isoparse

from modules.database.service import get_last_messages
from modules.database import service as database_service
from modules.system.logger import log_error, log_audit_entry, AuditStatus
from modules.system.service import get_active_character_name
from modules.system import character as character_service
from modules.memory.diary import generate_daily_activity_entry, run_sleeping_consolidation

CHECK_EVERY = 60  # We check every minute
DIARY_TRIGGER_HOUR_UTC = 0
DIARY_TRIGGER_MINUTE_UTC = 0
DIARY_IDLE_WINDOW_MINUTES = 20
DIARY_WAIT_LOG_INTERVAL_SECONDS = 300

# Store state between iterations
last_triggered_phase = None
last_initiative_time = None
MIN_INTERVAL = timedelta(minutes=10)  # minimum time between initiatives

# Добавим флаг, чтобы отслеживать, был ли уже пропуск "no_messages"
last_skip_reason = None
last_daily_diary_for_day = None
last_diary_consolidation_for_day = None
pending_daily_diary_for_day = None
last_daily_diary_wait_log_at = None


def ensure_datetime(value):
    if isinstance(value, str):
        dt = isoparse(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    elif isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)  # fallback, just in case


def analyze_pattern(messages):
    pattern = [msg["role"] for msg in messages]
    timestamps = [ensure_datetime(msg["timestamp"]) for msg in messages]

    now = datetime.now(timezone.utc)

    if pattern[-2:] == ["user", "assistant"]:
        idle = now - timestamps[-1]
        if idle >= timedelta(minutes=30):
            return "беспокойство"

    elif pattern[-3:] == ["user", "assistant", "assistant"]:
        idle = now - timestamps[-1]
        if idle >= timedelta(minutes=60):
            return "раздражение + беспокойство"

    elif pattern[-4:] == ["user", "assistant", "assistant", "assistant"]:
        idle = now - timestamps[-1]
        if idle >= timedelta(hours=24):
            return "обида + злость"

    return None


def _get_last_activity_timestamp(char_name: str):
    rows = get_last_messages(char_name, limit=1) or []
    if not rows:
        return None
    last_row = rows[-1]
    return ensure_datetime(last_row.get("timestamp"))


def _run_emotional_decay(*, character_id: str, day_iso: str) -> None:
    """Apply nightly decay to unresolved EmotionalTrace rows.

    Reads `moral.decay.enabled` / `moral.decay.global_rate` from DB config.
    Disabled → quick exit with audit entry so the operator sees the skip.
    """
    try:
        from modules.system import config as config_service
        from modules.moral_matrix.repository import MoralMatrixRepository

        if not bool(config_service.get_config_value("moral.decay.enabled", True)):
            log_audit_entry(
                event_type="emotional_decay_skipped",
                msg="[Initiative] Emotional decay disabled by config.",
                status=AuditStatus.INFO,
                details={"day": day_iso, "character_id": character_id},
            )
            return

        global_rate = float(config_service.get_config_value("moral.decay.global_rate", 0.05) or 0.05)
        repo = MoralMatrixRepository()
        result = repo.decay_emotional_traces(
            character_id=character_id,
            global_rate=global_rate,
        )
        log_audit_entry(
            event_type="emotional_decay_completed",
            msg="[Initiative] Emotional decay pass completed.",
            status=AuditStatus.INFO,
            details={
                "day": day_iso,
                "character_id": character_id,
                "global_rate": global_rate,
                **(result or {}),
            },
        )
    except Exception as exc:
        log_audit_entry(
            event_type="emotional_decay_failed",
            msg="[Initiative] Emotional decay failed.",
            status=AuditStatus.WARNING,
            details={
                "day": day_iso,
                "character_id": character_id,
                "error": str(exc),
            },
        )


def _run_audit_log_retention(*, day_iso: str) -> None:
    """Apply audit_logs retention policy. Reads audit_logs.retention.enabled
    from DB config so the operator can pause cleanup without restarting."""
    try:
        from modules.system import config as config_service
        from modules.system.logger import prune_audit_logs

        if not bool(
            config_service.get_config_value("audit_logs.retention.enabled", True)
        ):
            log_audit_entry(
                event_type="audit_log_retention_skipped",
                msg="[Initiative] Audit log retention disabled by config.",
                status=AuditStatus.INFO,
                details={"day": day_iso},
            )
            return

        stats = prune_audit_logs()
        log_audit_entry(
            event_type="audit_log_retention_completed",
            msg="[Initiative] Audit log retention pass completed.",
            status=AuditStatus.INFO,
            details={"day": day_iso, "by_severity": stats},
        )
    except Exception as exc:
        log_audit_entry(
            event_type="audit_log_retention_failed",
            msg="[Initiative] Audit log retention failed.",
            status=AuditStatus.WARNING,
            details={"day": day_iso, "error": str(exc)},
        )


def _run_self_watcher_reflection(*, character_id: str, day_iso: str) -> None:
    """Run §3.7 nightly cluster reflection and stitch the prose into the
    diary entry's payload.self_reflection. Never raises.
    """
    try:
        from datetime import date as date_cls
        import json as _json

        from modules.self_watcher import record_nightly_reflection
        from modules.memory.diary import get_daily_activity_entry
        from modules.database.core import engine
        from sqlalchemy import text as _text

        try:
            day_obj = date_cls.fromisoformat(day_iso)
        except Exception:
            day_obj = date_cls.today()

        reflection = record_nightly_reflection(character_id=character_id, day=day_obj)
        if not reflection:
            return

        entry = get_daily_activity_entry(character_id=character_id, target_day=day_obj)
        if entry is None:
            return

        payload = dict(entry.payload or {})
        payload["self_reflection"] = reflection
        with engine.begin() as conn:
            conn.execute(
                _text(
                    "UPDATE daily_activity_diary SET payload = :payload "
                    "WHERE id = :id"
                ),
                {
                    "payload": _json.dumps(payload, ensure_ascii=False),
                    "id": entry.id,
                },
            )

        log_audit_entry(
            event_type="self_watcher_reflection_written",
            msg="[Initiative] Self-Watcher nightly reflection stitched into diary.",
            status=AuditStatus.INFO,
            details={"day": day_iso, "character_id": character_id, "length": len(reflection)},
        )
    except Exception as exc:
        log_audit_entry(
            event_type="self_watcher_reflection_failed",
            msg="[Initiative] Self-Watcher nightly reflection failed.",
            status=AuditStatus.WARNING,
            details={"day": day_iso, "character_id": character_id, "error": str(exc)},
        )


def _is_daily_diary_due(now: datetime, diary_day_iso: str | None) -> bool:
    trigger_dt = datetime.combine(
        now.date(),
        dt_time(DIARY_TRIGGER_HOUR_UTC, DIARY_TRIGGER_MINUTE_UTC),
        tzinfo=timezone.utc,
    )
    if now < trigger_dt:
        return False
    return bool(diary_day_iso)


def initiative_monitor():
    global last_triggered_phase
    global last_initiative_time
    global last_skip_reason
    global last_daily_diary_for_day
    global last_diary_consolidation_for_day
    global pending_daily_diary_for_day
    global last_daily_diary_wait_log_at
    log_audit_entry(
        event_type="loop_started",
        msg="[Initiative] Loop started",
        status=AuditStatus.INFO,
        details={"loop": "initiative_monitor"},
    )

    while True:
        try:
            now = datetime.now(timezone.utc)

            # §3.9-quinquies — fire due user reminders (every tick, before the
            # diary branch: «разбуди в 7» must not wait for nightly jobs).
            try:
                from modules.reminders import fire_due_reminders

                fire_summary = fire_due_reminders(now=now)
                if fire_summary.get("fired") or fire_summary.get("failed"):
                    log_audit_entry(
                        event_type="reminders_fired",
                        msg="[Initiative] Due reminders processed.",
                        status=AuditStatus.INFO,
                        details=fire_summary,
                    )
            except Exception as reminders_exc:
                log_audit_entry(
                    event_type="reminders_pass_error",
                    msg="[Initiative] Reminders pass failed.",
                    status=AuditStatus.WARNING,
                    details={"error": str(reminders_exc)},
                )

            diary_day = (now - timedelta(days=1)).date()
            diary_day_iso = diary_day.isoformat()
            if (
                last_daily_diary_for_day != diary_day_iso
                and pending_daily_diary_for_day is None
                and _is_daily_diary_due(now, diary_day_iso)
            ):
                pending_daily_diary_for_day = diary_day_iso
                log_audit_entry(
                    event_type="daily_diary_queued",
                    msg="[Initiative] Daily diary queued and waiting for idle window.",
                    status=AuditStatus.INFO,
                    details={
                        "day": diary_day_iso,
                        "idle_window_minutes": DIARY_IDLE_WINDOW_MINUTES,
                        "trigger_utc": f"{DIARY_TRIGGER_HOUR_UTC:02d}:{DIARY_TRIGGER_MINUTE_UTC:02d}",
                    },
                )

            if pending_daily_diary_for_day and pending_daily_diary_for_day == diary_day_iso:
                try:
                    char_name = get_active_character_name(default="default_waifu")
                    character = character_service.get_or_create_character(char_name)
                    last_activity_at = _get_last_activity_timestamp(char_name)
                    idle_minutes = None
                    if last_activity_at is not None:
                        idle_minutes = int(
                            max(
                                0.0,
                                (now - ensure_datetime(last_activity_at)).total_seconds() / 60.0,
                            )
                        )
                    if idle_minutes is not None and idle_minutes < DIARY_IDLE_WINDOW_MINUTES:
                        can_log_wait = (
                            last_daily_diary_wait_log_at is None
                            or (now - last_daily_diary_wait_log_at).total_seconds()
                            >= DIARY_WAIT_LOG_INTERVAL_SECONDS
                        )
                        if can_log_wait:
                            last_daily_diary_wait_log_at = now
                            log_audit_entry(
                                event_type="daily_diary_waiting_idle_window",
                                msg="[Initiative] Daily diary postponed due to active session.",
                                status=AuditStatus.INFO,
                                details={
                                    "day": diary_day_iso,
                                    "idle_minutes": idle_minutes,
                                    "required_idle_minutes": DIARY_IDLE_WINDOW_MINUTES,
                                },
                            )
                        time.sleep(CHECK_EVERY)
                        continue
                    result = generate_daily_activity_entry(
                        character_id=character.id,
                        target_day=diary_day,
                        force=False,
                    )
                    last_daily_diary_for_day = diary_day_iso
                    pending_daily_diary_for_day = None
                    last_daily_diary_wait_log_at = None
                    log_audit_entry(
                        event_type="daily_diary_generated",
                        msg="[Initiative] Daily diary generation check completed.",
                        status=AuditStatus.INFO,
                        details={
                            "day": diary_day_iso,
                            "generated": bool(result.get("generated")),
                            "character_id": character.id,
                            "entry_id": ((result.get("entry") or {}).get("id") if isinstance(result, dict) else None),
                        },
                    )
                    entry_payload = (result.get("entry") or {}) if isinstance(result, dict) else {}
                    if isinstance(entry_payload, dict) and entry_payload.get("summary"):
                        try:
                            database_service.add_tool_event_to_history(
                                character_name=char_name,
                                tool_name="daily_activity_diary",
                                content=(
                                    f"[OK]: daily diary entry prepared for {diary_day_iso}. "
                                    f"mood={entry_payload.get('mood') or 'neutral'}; "
                                    f"summary={str(entry_payload.get('summary') or '').strip()[:800]}"
                                ),
                                timestamp=now,
                                runtime_meta={
                                    "source": "initiative_monitor",
                                    "event": "daily_activity_diary",
                                    "tool": {
                                        "name": "daily_activity_diary",
                                        "status": "ok",
                                        "generated": bool(result.get("generated")),
                                        "entry_id": entry_payload.get("id"),
                                        "day": diary_day_iso,
                                    },
                                },
                                tags=["tool", "diary", "ok"],
                            )
                        except Exception as persist_exc:
                            log_audit_entry(
                                event_type="daily_diary_history_persist_failed",
                                msg="[Initiative] Daily diary history persist failed.",
                                status=AuditStatus.WARNING,
                                details={"error": str(persist_exc), "day": diary_day_iso},
                            )
                    if last_diary_consolidation_for_day != diary_day_iso:
                        consolidation = run_sleeping_consolidation(
                            character_id=character.id,
                            lookback_days=14,
                        )
                        last_diary_consolidation_for_day = diary_day_iso
                        log_audit_entry(
                            event_type="daily_diary_consolidation",
                            msg="[Initiative] Daily diary consolidation completed.",
                            status=AuditStatus.INFO,
                            details={
                                "day": diary_day_iso,
                                "character_id": character.id,
                                **(consolidation or {}),
                            },
                        )

                        # Emotional decay — same window as consolidation: nightly,
                        # idempotent (uses last_decayed_at), skipped when disabled.
                        _run_emotional_decay(character_id=character.id, day_iso=diary_day_iso)

                        # Audit log retention — runs once per nightly window
                        # (character_id-agnostic, but we piggyback on the
                        # diary slot so it never collides with active turns).
                        _run_audit_log_retention(day_iso=diary_day_iso)

                        # Finished reminders cleanup — same nightly slot.
                        try:
                            from modules.system import config as config_service
                            from modules.reminders import reminders_repository

                            retention_days = int(
                                config_service.get_config_value(
                                    "reminders.retention_days", 30
                                )
                                or 30
                            )
                            pruned = reminders_repository.prune_finished(
                                older_than_days=retention_days
                            )
                            if pruned:
                                log_audit_entry(
                                    event_type="reminders_pruned",
                                    msg="[Initiative] Finished reminders pruned.",
                                    status=AuditStatus.INFO,
                                    details={
                                        "deleted": pruned,
                                        "older_than_days": retention_days,
                                    },
                                )
                        except Exception as prune_exc:
                            log_audit_entry(
                                event_type="reminders_prune_failed",
                                msg="[Initiative] Reminders prune failed.",
                                status=AuditStatus.WARNING,
                                details={"error": str(prune_exc)},
                            )

                        # Self-Watcher nightly reflection (§3.7) — aggregates
                        # recent expectation_events into a short first-person
                        # passage and stitches it into the diary payload that
                        # was just (re)written above.
                        _run_self_watcher_reflection(
                            character_id=character.id, day_iso=diary_day_iso
                        )
                except Exception as diary_exc:
                    log_audit_entry(
                        event_type="daily_diary_generation_error",
                        msg="[Initiative] Daily diary generation failed.",
                        status=AuditStatus.WARNING,
                        details={"error": str(diary_exc), "day": diary_day_iso},
                    )

            char_name = get_active_character_name(default="default")
            messages = get_last_messages(char_name, limit=10)

            if not messages:
                # Проверяем, был ли уже лог с reason: "no_messages"
                if last_skip_reason != "no_messages":
                    log_audit_entry(
                        event_type="initiative_skip",
                        msg="[Initiative] Skip Initiative",
                        status=AuditStatus.INFO,
                        details={"reason": "no_messages"},
                    )
                    last_skip_reason = "no_messages"
                time.sleep(CHECK_EVERY)
                continue

            # Если сообщения появились, сбрасываем флаг
            if last_skip_reason == "no_messages":
                last_skip_reason = None

            emotion = analyze_pattern(messages)
            now = datetime.now(timezone.utc)

            if emotion:
                # Check for repetition and frequency
                if emotion != last_triggered_phase or (
                    last_initiative_time and now - last_initiative_time >= MIN_INTERVAL
                ):
                    log_audit_entry(
                        event_type="initiative_triggered",
                        msg="[Initiative] Emotion change",
                        status=AuditStatus.INFO,
                        details={"emotion": emotion},
                    )
                    # run_initiative(emotion=emotion)
                    last_triggered_phase = emotion
                    last_initiative_time = now
                else:
                    log_audit_entry(
                        event_type="initiative_repeat_skipped",
                        msg="[Initiative] Triggered Emotions",
                        status=AuditStatus.INFO,
                        details={
                            "emotion": emotion,
                            "last_triggered": (
                                last_initiative_time.isoformat()
                                if last_initiative_time
                                else None
                            ),
                        },
                    )
            time.sleep(CHECK_EVERY)

        except Exception as e:
            log_error("[Initiative] Initiative Error:", str(e))
            time.sleep(60)


