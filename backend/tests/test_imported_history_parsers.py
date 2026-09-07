"""§7.3.17 Interaction-history import — parser unit tests.

Covers:
  * format detection for both known shapes, and honest 'unknown'
  * chatgpt_script: roles, unix time -> occurred_at, missing time -> unknown
  * tool entries never become messages; only image captions are kept
  * "[object Object]" is counted as lost at export, never stored
  * qa_pairs: one pair -> two turns, order preserved, no time invented
"""

from __future__ import annotations

import pytest

from modules.imported_history import detect_format, parse_archive
from modules.imported_history.parsers import (
    FORMAT_CHATGPT_SCRIPT,
    FORMAT_QA_PAIRS,
    FORMAT_UNKNOWN,
    PRECISION_EXACT,
    PRECISION_UNKNOWN,
)

pytestmark = pytest.mark.regression


def test_detect_format_recognises_both_shapes_and_rejects_the_rest():
    assert detect_format([{"role": "user", "time": 1, "text": "hi"}]) == FORMAT_CHATGPT_SCRIPT
    assert detect_format([{"question": "q", "answer": "a"}]) == FORMAT_QA_PAIRS
    assert detect_format([]) == FORMAT_UNKNOWN
    assert detect_format({"role": "user"}) == FORMAT_UNKNOWN
    assert detect_format([{"whatever": 1}]) == FORMAT_UNKNOWN


def test_chatgpt_script_keeps_roles_and_converts_time():
    archive = parse_archive([
        {"role": "user", "time": 1778686947.331, "text": "привет"},
        {"role": "assistant", "time": 1778686950.0, "text": "и тебе"},
    ])

    assert [m.role for m in archive.messages] == ["user", "assistant"]
    assert [m.sequence for m in archive.messages] == [0, 1]
    assert all(m.time_precision == PRECISION_EXACT for m in archive.messages)
    assert archive.messages[0].occurred_at is not None
    assert archive.stats["without_time"] == 0


def test_missing_time_is_unknown_and_never_invented():
    archive = parse_archive([{"role": "user", "time": None, "text": "когда-то"}])

    message = archive.messages[0]
    assert message.occurred_at is None
    assert message.time_precision == PRECISION_UNKNOWN
    assert archive.stats["without_time"] == 1


def test_tool_entries_never_become_messages():
    archive = parse_archive([
        {"role": "user", "time": 1, "text": "нарисуй"},
        {"role": "tool", "time": 2, "text": "[object Object]"},
        {"role": "assistant", "time": 3, "text": "вот"},
    ])

    assert [m.role for m in archive.messages] == ["user", "assistant"]
    assert all(m.role != "tool" for m in archive.messages)


def test_lost_parts_are_counted_and_not_stored():
    archive = parse_archive([
        {"role": "tool", "time": 1, "text": "[object Object]"},
        {"role": "tool", "time": 2, "text": "[object Object]\n[object Object]"},
    ])

    assert archive.artifacts == []
    assert archive.stats["artifacts_lost_at_export"] == 2


def test_image_caption_is_kept_and_linked_to_the_assistant_turn():
    archive = parse_archive([
        {"role": "user", "time": 1, "text": "нарисуй кота"},
        {"role": "assistant", "time": 2, "text": "готово"},
        {"role": "tool", "time": 3, "text": "[object Object]\nModel caption: A grey cat on a windowsill."},
    ])

    assert len(archive.artifacts) == 1
    artifact = archive.artifacts[0]
    assert artifact.kind == "image_caption"
    assert artifact.content == "A grey cat on a windowsill."
    # linked to the assistant turn that produced it, by sequence
    assert artifact.message_sequence == 1
    assert archive.stats["artifacts_kept"] == 1


def test_saved_paths_and_service_chatter_are_dropped():
    archive = parse_archive([
        {"role": "tool", "time": 1, "text": "Generated images from the last `image_gen.text2im` call were saved at:\n- /mnt/data/x.png"},
        {"role": "tool", "time": 2, "text": "[convo search]\nAn error occurred while searching."},
    ])

    assert archive.artifacts == []
    assert archive.stats["artifacts_dropped"] == 2


def test_qa_pairs_expand_into_two_turns_in_order():
    archive = parse_archive([
        {"question": "а как называются кольца?", "answer": "это радужка"},
        {"question": "точно?", "answer": "точно"},
    ])

    assert archive.source_format == FORMAT_QA_PAIRS
    assert [m.role for m in archive.messages] == ["user", "assistant", "user", "assistant"]
    assert [m.sequence for m in archive.messages] == [0, 1, 2, 3]
    assert archive.stats["pairs"] == 2


def test_qa_pairs_never_invent_a_timestamp():
    archive = parse_archive([{"question": "q", "answer": "a"}])

    assert all(m.occurred_at is None for m in archive.messages)
    assert all(m.time_precision == PRECISION_UNKNOWN for m in archive.messages)
    assert archive.stats["without_time"] == 2


def test_blank_question_is_skipped_but_the_answer_survives():
    archive = parse_archive([{"question": "   ", "answer": "ответ есть"}])

    assert len(archive.messages) == 1
    assert archive.messages[0].role == "assistant"
    assert archive.stats["skipped_empty"] == 1


def test_blank_turn_in_script_format_is_skipped():
    archive = parse_archive([
        {"role": "user", "time": 1, "text": ""},
        {"role": "assistant", "time": 2, "text": "есть"},
    ])

    assert [m.role for m in archive.messages] == ["assistant"]
    assert archive.stats["skipped_empty"] == 1


def test_unknown_format_returns_empty_archive_without_raising():
    archive = parse_archive([{"totally": "unexpected"}])

    assert archive.source_format == FORMAT_UNKNOWN
    assert archive.messages == []
