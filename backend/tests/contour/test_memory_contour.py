"""Contour smoke tests for PAI memory: a whole turn on a throwaway PAI.

The expectations encode how memory is meant to behave, not how the current
implementation behaves, so some of these fail on purpose until the contour is
fixed. Each failure marks a gap. Run with:

    venv\\Scripts\\python.exe tests\\contour\\run_contour.py
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
from freezegun import freeze_time

pytestmark = pytest.mark.contour

# The test owner's timezone is Europe/Moscow (UTC+3, no DST): 12:00 UTC is 15:00 local.
MSK = timezone(timedelta(hours=3))


def test_contour_storage_is_not_the_live_database(pai):
    from constants import paths
    from modules.database import core as db_core

    live_db = os.path.abspath(os.path.join(paths.BASE_DIR, "storage", "database", "core.db"))
    assert os.path.abspath(db_core.DB_PATH) != live_db
    assert os.path.abspath(db_core.DB_PATH).startswith(
        os.path.abspath(os.environ["PAI_STORAGE_DIR"])
    )


def test_contour_logs_are_not_the_live_logs(pai):
    from modules.system import logger

    override = os.path.abspath(os.environ["PAI_STORAGE_DIR"])
    for path in (logger.TRACEBACK_FILE, logger.DEBUG_FILE_CURRENT, logger.DEBUG_FILE_PER_SESSION):
        assert os.path.abspath(path).startswith(override), path


# ---------------------------------------------------------------------------
# Thread of the conversation
# ---------------------------------------------------------------------------


_THREAD_PAIRS = [
    ("Разбирал сегодня старые фотографии.", "Нашёл что-нибудь интересное?"),
    ("Нашёл снимок с того похода на озеро.", "Это где палатку сдуло?"),
    ("Да, именно тот.", "Помню, ты тогда полночи её ловил."),
    ("Ладно, пойду пообедаю.", "Приятного аппетита."),
    ("Спасибо.", "Возвращайся."),
]


def test_thread_reaches_the_instructor_without_a_pause(pai):
    """Control for the test below: with no pause the thread must arrive, so a
    failure there is about the pause, not about the test setup."""
    now = datetime.now(timezone.utc)
    started = now - timedelta(minutes=30)
    for index, (user_text, assistant_text) in enumerate(_THREAD_PAIRS):
        at = started + timedelta(minutes=5 * index)
        pai.say("user", user_text, at)
        pai.say("assistant", assistant_text, at + timedelta(seconds=30))

    turn = pai.turn("Я вернулся.", at=now)

    dialogue = turn.dialogue_text()
    missing = [text for pair in _THREAD_PAIRS for text in pair if text not in dialogue]
    assert not missing, f"thread did not reach the instructor: {missing}"


def test_thread_survives_a_daytime_pause(pai):
    """The last pairs reach the instructor as the thread of the conversation.
    A pause of a few hours during the day must not cut the thread."""
    now = datetime.now(timezone.utc)
    started = now - timedelta(hours=4)
    pairs = _THREAD_PAIRS
    for index, (user_text, assistant_text) in enumerate(pairs):
        at = started + timedelta(minutes=10 * index)
        pai.say("user", user_text, at)
        pai.say("assistant", assistant_text, at + timedelta(seconds=30))

    # More than three hours of silence, then a new message.
    turn = pai.turn("Я вернулся.", at=now)

    dialogue = turn.dialogue_text()
    missing = [
        text
        for pair in pairs
        for text in pair
        if text not in dialogue
    ]
    assert not missing, f"thread lost after a daytime pause: {missing}"


# ---------------------------------------------------------------------------
# Session: the whole day
# ---------------------------------------------------------------------------


def test_session_is_the_whole_day_despite_a_pause(pai):
    """The session is the current day, from its first message. A pause of a
    few hours during the day does not start a new one, so something said in
    the morning is found in the session in the afternoon."""
    morning = datetime(2026, 3, 10, 9, 0, tzinfo=MSK)
    coffee = "Утром выпил уже третью чашку кофе, а сон так и не прошёл."
    pai.say("user", coffee, morning)
    pai.say("assistant", "Может, лучше прогуляться, чем четвёртую?", morning + timedelta(minutes=1))

    # Two hours of silence, then enough talk to push the morning out of the
    # last pairs.
    later = datetime(2026, 3, 10, 11, 30, tzinfo=MSK)
    for index in range(25):
        at = later + timedelta(minutes=5 * index)
        pai.say("user", f"Разбираю почту, осталось {60 - index} писем.", at)
        pai.say("assistant", f"Держись, {60 - index} — это уже немного.", at + timedelta(seconds=30))

    afternoon = datetime(2026, 3, 10, 15, 0, tzinfo=MSK)
    with freeze_time(afternoon.astimezone(timezone.utc), tick=True):
        turn = pai.turn("Помнишь, что я утром говорил про кофе?", at=afternoon)

    memory_block = turn.tool_content("memory.lookup")
    assert coffee in memory_block, memory_block


def test_conversation_past_midnight_stays_in_the_previous_day(pai):
    """A session closes only in the end-of-day window: from about 23:55, after
    20 minutes without new messages. A conversation that goes on past midnight
    belongs to the day it started in; what comes after the silence belongs to
    the new day. The nightly diary of that day is built from its session."""
    day = datetime(2026, 3, 10, 21, 0, tzinfo=MSK)
    evening_count = 0
    for index in range(18):  # 21:00 … 23:50, a pair every 10 minutes
        at = day + timedelta(minutes=10 * index)
        pai.say("user", f"Вечерний разговор, реплика {index + 1}.", at)
        pai.say("assistant", f"Слушаю, продолжай ({index + 1}).", at + timedelta(seconds=30))
        evening_count += 2

    after_midnight = datetime(2026, 3, 11, 0, 5, tzinfo=MSK)
    continuation = "Уже за полночь, но договорю мысль."
    pai.say("user", continuation, after_midnight)
    pai.say("assistant", "Договаривай, я здесь.", after_midnight + timedelta(seconds=30))
    pai.say("user", "Всё, теперь точно спать.", after_midnight + timedelta(minutes=10))
    pai.say("assistant", "Спокойной ночи.", after_midnight + timedelta(minutes=10, seconds=30))
    evening_count += 4

    # 55 minutes of silence inside the end-of-day window: the day is closed.
    new_day = datetime(2026, 3, 11, 1, 10, tzinfo=MSK)
    pai.say("user", "Не спится, решил написать.", new_day)
    pai.say("assistant", "Опять бессонница?", new_day + timedelta(seconds=30))

    from modules.memory.diary import generate_daily_activity_entry

    with freeze_time(datetime(2026, 3, 11, 1, 30, tzinfo=MSK).astimezone(timezone.utc), tick=True):
        result = generate_daily_activity_entry(
            character_id=pai.character_id,
            target_day=day.date(),
            force=True,
        )

    messages_used = result["entry"]["payload"]["messages_used"]
    assert messages_used == evening_count, (
        f"diary of {day.date()} used {messages_used} messages, "
        f"its session has {evening_count} (21:00 … 00:15)"
    )


# ---------------------------------------------------------------------------
# Recall through the day summaries
# ---------------------------------------------------------------------------


def test_recall_three_days_back_reaches_the_exact_message(pai):
    """Step 3 of the cascade: a day summary leads into that day, and the exact
    message from that day lands in the memory block."""
    now = datetime.now(timezone.utc)
    day = (now - timedelta(days=3)).replace(hour=12, minute=0, second=0, microsecond=0)
    exact = "В парсере вылез сегфолт из-за пустой строки во входе."
    day_ids = [
        pai.say("user", "Смотри, опять какая-то ерунда вылезла.", day),
        pai.say("assistant", "Показывай, что там.", day + timedelta(minutes=1)),
        pai.say("user", exact, day + timedelta(minutes=2)),
        pai.say("assistant", "Значит, проверку на пустую строку надо ставить раньше.", day + timedelta(minutes=3)),
    ]
    pai.add_day_summary(day, "Разбирали ерунду с кодом: сегфолт в парсере.", day_ids)

    # Newer days push that day out of the recent window.
    filler_start = now - timedelta(hours=30)
    for index in range(20):
        at = filler_start + timedelta(minutes=5 * index)
        pai.say("user", f"За окном опять дождь, уже {index + 1}-й раз за неделю.", at)
        pai.say("assistant", f"Тогда пледа и чая хватит на {index + 1} серий.", at + timedelta(seconds=30))

    turn = pai.turn("Помнишь, какая там была ерунда с кодом?", at=now)

    memory_block = turn.tool_content("memory.lookup")
    assert exact in memory_block, memory_block


def test_summaries_exist_for_past_days_with_messages(pai):
    """Step 3 needs a summary for every recent day that had messages. Nobody
    should create them by hand: once the system has started, they exist."""
    now = datetime.now(timezone.utc)
    day = (now - timedelta(days=2)).replace(hour=15, minute=0, second=0, microsecond=0)
    pai.say("user", "Слушал сегодня новую песню, залипла.", day)
    pai.say("assistant", "Скинешь потом? Интересно.", day + timedelta(minutes=1))

    pai.start_system()

    summary_days = {
        str(row[0])[:10]
        for row in pai.fetch("SELECT created_at FROM short_term_memory")
    }
    assert day.date().isoformat() in summary_days, summary_days


# ---------------------------------------------------------------------------
# Moral matrix: the verdict is what gets stored
# ---------------------------------------------------------------------------


def test_moral_matrix_state_follows_the_model_answer(pai, moral_answer):
    """The matrix decides what was said, why, and what effect it had. Its answer
    comes in the structure the matrix prompt asks for and must change the state;
    the stored trace keeps the verdict, not a preview of the message."""
    reason = "Он нагрубил без причины: мой ответ был верным, моей ошибки нет."
    pai.moral_response = json.dumps(
        moral_answer(dominant="hurt", strength=0.7, reason=reason),
        ensure_ascii=False,
    )

    turn = pai.turn("Ты тупая, ничего не понимаешь.", tone="angry")

    state = turn.processing["moral_state"]
    assert state["emotion_intensity"] >= 0.5, state
    assert state["trigger"] == reason, state
    causes = [row[0] for row in pai.fetch("SELECT cause FROM emotional_traces")]
    assert causes == [reason], causes


def test_moral_matrix_does_not_silently_accept_an_answer_it_cannot_use(pai):
    """An answer the matrix cannot read must fall back to the system heuristic,
    not collapse into a calm state with zero intensity."""
    pai.moral_response = json.dumps({"unexpected": "structure"})

    turn = pai.turn("Привет, как ты?")

    meta = turn.processing["moral_state"]["meta"]
    assert meta["transition_provider"] == "heuristic", meta


def test_moral_matrix_partial_answer_keeps_the_current_state(pai, moral_answer):
    """An answer that says nothing about the emotion must leave the state she is in
    untouched (it used to become calm with 0)."""
    pai.moral_response = json.dumps(
        moral_answer(dominant="joy", strength=0.7, reason="he thanked me"), ensure_ascii=False
    )
    pai.turn("Спасибо тебе, ты очень помогла.", tone="joy")

    summary = "Мне тепло от этих слов."
    pai.moral_response = json.dumps({"summary": summary}, ensure_ascii=False)

    turn = pai.turn("И вообще ты молодец.", tone="joy")

    state = turn.processing["moral_state"]
    assert state["meta"]["transition_provider"] == "ollama", state["meta"]
    # The state she came in with stays hers; the answer only adds its words.
    assert state["current_emotion"] == "joy", state
    assert state["emotion_intensity"] == pytest.approx(0.7, abs=0.01), state
    assert state["narrative"] == summary, state


def test_moral_matrix_falls_back_to_heuristic_when_the_model_is_silent(pai):
    pai.moral_response = "не JSON, модель сбилась"

    turn = pai.turn("Привет, как ты?")

    meta = turn.processing["moral_state"]["meta"]
    assert meta["transition_provider"] == "heuristic", meta


# ---------------------------------------------------------------------------
# Write time
# ---------------------------------------------------------------------------


def test_each_snapshot_and_trace_gets_its_own_write_time(pai):
    """"The latest snapshot" and "the recent traces" are picked by created_at,
    so every row must carry its real write time."""
    from modules.moral_matrix.repository import MoralMatrixRepository

    repository = MoralMatrixRepository()
    repository.store_snapshot(pai.character_id, None, {"current_emotion": "peace"})
    repository.store_emotional_trace(pai.character_id, message_id=None, payload={"primary_emotion": "peace"})
    time.sleep(0.05)
    repository.store_snapshot(pai.character_id, None, {"current_emotion": "joy"})
    repository.store_emotional_trace(pai.character_id, message_id=None, payload={"primary_emotion": "joy"})

    snapshot_times = {row[0] for row in pai.fetch("SELECT created_at FROM moral_state_snapshots")}
    trace_times = {row[0] for row in pai.fetch("SELECT created_at FROM emotional_traces")}
    assert len(snapshot_times) == 2, snapshot_times
    assert len(trace_times) == 2, trace_times
    assert repository.fetch_latest_snapshot(pai.character_id)["mood"] == "joy"
