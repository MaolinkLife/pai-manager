"""Honest module statuses in the scope: memory and lorebook.

The system knows what is happening to it. A module
block is data, "nothing found", "disabled" (left out while the instructor
excludes disabled modules) or "[ERROR]" when the module failed, which always goes
in. A guest gets no error details.
"""

import asyncio

import pytest

from core import decision_layer as decision_layer_module
from core import instructor as instructor_module
from core import interaction as interaction_module
from core.decision_layer import DecisionLayer
from core.instructor import Instructor
from core.interaction import InteractionPolicy
from core.task_layer import TASK_COMPLETE, TASK_FAILED, TASK_SKIPPED, TASK_UNAVAILABLE, TaskPlan
from modules.memory import service as memory_service
from modules.memory.service import MemoryContextResult, MemoryModule


def _use(monkeypatch, *, exclude=True, role="owner"):
    values = {
        "decision_layer.instructor.exclude_disabled_modules": exclude,
        "decision_layer.instructor.include_datetime": False,
        "memory.diary.context.enabled": False,
    }
    monkeypatch.setattr(
        instructor_module.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: values.get(path, default),
    )
    monkeypatch.setattr(
        interaction_module,
        "resolve_interaction_policy",
        lambda actor_user_uuid: InteractionPolicy(
            actor_role=role,
            can_affect_moral=role == "owner",
            can_affect_global_memory=role == "owner",
        ),
    )


def _blocks(memory_context):
    messages = Instructor()._build_dynamic_tool_messages(
        user_message={"id": "m1", "actor_user_uuid": "someone"},
        memory_context=memory_context,
    )
    return {message["name"]: message["content"] for message in messages if message.get("role") == "tool"}


# ---------------------------------------------------------------------------
# Instructor
# ---------------------------------------------------------------------------


def test_found_records_and_lore_come_as_data(monkeypatch):
    _use(monkeypatch)

    blocks = _blocks(
        {
            "memory_status": "ready",
            "key_facts": ["She likes rain."],
            "lore_matches": ["Lim: an AI companion"],
            "lore_status": "ok",
        }
    )

    assert blocks["memory.lookup"].startswith("[OK]: memory records found:")
    assert "She likes rain." in blocks["memory.lookup"]
    assert blocks["knowledge.lorebook"].startswith("[OK]: lorebook matches found:")


def test_a_lookup_that_found_nothing_says_so(monkeypatch):
    _use(monkeypatch)

    blocks = _blocks(
        {
            "memory_status": "not_found",
            # The memory module puts its fallback line into key_facts.
            "key_facts": ["За сегодня ничего не найдено."],
            "lore_matches": [],
            "lore_status": "empty",
        }
    )

    assert blocks["memory.lookup"].startswith("[OK]: no relevant memory records found.")
    assert blocks["knowledge.lorebook"] == "[OK]: no lorebook entries found."
    assert not any("[ERROR]" in content for content in blocks.values())


def test_disabled_memory_leaves_the_scope_while_excluded(monkeypatch):
    _use(monkeypatch, exclude=True)

    blocks = _blocks({"memory_status": "disabled", "key_facts": [], "lore_matches": []})

    assert "memory.lookup" not in blocks
    assert "knowledge.lorebook" not in blocks


def test_disabled_memory_is_named_when_not_excluded(monkeypatch):
    _use(monkeypatch, exclude=False)

    blocks = _blocks({"memory_status": "disabled", "key_facts": [], "lore_matches": []})

    assert blocks["memory.lookup"] == "[OK]: memory module is disabled."
    assert blocks["knowledge.lorebook"] == "[OK]: lorebook is disabled together with the memory module."


@pytest.mark.parametrize("status", ["module_unavailable", "embedding_failed", "failed"])
def test_failed_memory_always_reaches_the_owner_with_the_error(monkeypatch, status):
    _use(monkeypatch, exclude=True, role="owner")

    blocks = _blocks({"memory_status": status, "memory_error": r"db is locked at C:\pai\core.db", "lore_matches": []})

    assert blocks["memory.lookup"].startswith("[ERROR]: the memory module failed: db is locked")
    # The lorebook was not searched; the memory failure already says so.
    assert "knowledge.lorebook" not in blocks


@pytest.mark.parametrize("role", ["user", "anonymous"])
def test_a_guest_hears_only_that_something_went_wrong(monkeypatch, role):
    _use(monkeypatch, role=role)

    blocks = _blocks({"memory_status": "failed", "memory_error": r"db is locked at C:\pai\core.db"})

    assert blocks["memory.lookup"].startswith("[ERROR]:")
    assert "something went wrong" in blocks["memory.lookup"]
    assert "db is locked" not in blocks["memory.lookup"]
    assert "C:" not in blocks["memory.lookup"]


def test_a_failed_lorebook_is_an_error_while_memory_works(monkeypatch):
    _use(monkeypatch)

    blocks = _blocks(
        {
            "memory_status": "ready",
            "key_facts": ["She likes rain."],
            "lore_matches": [],
            "lore_status": "failed",
            "lore_error": "lorebook index is broken",
        }
    )

    assert blocks["memory.lookup"].startswith("[OK]: memory records found:")
    assert blocks["knowledge.lorebook"].startswith("[ERROR]: the lorebook failed: lorebook index is broken")


# ---------------------------------------------------------------------------
# Memory module: the lorebook search reports its own status
# ---------------------------------------------------------------------------


def _lore(monkeypatch, search):
    monkeypatch.setattr(
        memory_service.config_service,
        "get_config_value",
        lambda path, default=None, user_uuid=None: default,
    )
    monkeypatch.setattr(memory_service.lorebook, "search_entries", search)
    monkeypatch.setattr(memory_service, "log_audit_entry", lambda *args, **kwargs: None)
    return MemoryModule.__new__(MemoryModule)._collect_lore_context("who is Lim")


def test_lorebook_search_status_found_empty_failed(monkeypatch):
    found = _lore(monkeypatch, lambda **kwargs: [{"title": "Lim", "content": "an AI companion"}])
    empty = _lore(monkeypatch, lambda **kwargs: [])

    def broken(**kwargs):
        raise RuntimeError("lorebook index is broken")

    failed = _lore(monkeypatch, broken)

    assert found["lore_status"] == "ok"
    assert empty["lore_status"] == "empty"
    assert failed["lore_status"] == "failed"
    assert failed["lore_error"] == "lorebook index is broken"


# ---------------------------------------------------------------------------
# Decision layer: a failing memory module becomes a status, not a crashed turn
# ---------------------------------------------------------------------------


class _Memory:
    def __init__(self, *, raises=None, context=None):
        self.raises = raises
        self.context = context or {}

    async def collect_context(self, text, message):
        if self.raises:
            raise self.raises
        return MemoryContextResult(context=self.context, meta={})


def _collect(monkeypatch, *, module=None, init_error="", memory_enabled=True):
    monkeypatch.setattr(decision_layer_module, "log_audit_entry", lambda *args, **kwargs: None)
    layer = DecisionLayer.__new__(DecisionLayer)
    layer._memory_module = module
    layer._memory_module_failed = module is None
    layer._memory_module_error = init_error
    plan = TaskPlan()
    plan.add("memory", "memory", "collect_context")
    result = asyncio.run(
        layer._collect_memory_result(
            {"content": "hello"}, plan, {}, memory_enabled=memory_enabled
        )
    )
    return result.context, plan.first("memory")


def test_a_crashing_memory_module_becomes_a_failed_status(monkeypatch):
    context, task = _collect(monkeypatch, module=_Memory(raises=RuntimeError("db is locked")))

    assert context["memory_status"] == "failed"
    assert context["memory_error"] == "db is locked"
    assert task.status == TASK_FAILED


def test_a_memory_module_that_did_not_start_carries_its_error(monkeypatch):
    context, task = _collect(monkeypatch, module=None, init_error="no embeddings backend")

    assert context["memory_status"] == "module_unavailable"
    assert context["memory_error"] == "no embeddings backend"
    assert task.status == TASK_UNAVAILABLE


def test_disabled_and_working_memory_keep_their_statuses(monkeypatch):
    disabled, disabled_task = _collect(monkeypatch, module=_Memory(), memory_enabled=False)
    working, working_task = _collect(
        monkeypatch, module=_Memory(context={"memory_status": "ready", "matches": []})
    )

    assert disabled["memory_status"] == "disabled"
    assert disabled_task.status == TASK_SKIPPED
    assert working["memory_status"] == "ready"
    assert working_task.status == TASK_COMPLETE
