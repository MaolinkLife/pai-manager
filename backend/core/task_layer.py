from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


TASK_PENDING = "pending"
TASK_RUNNING = "running"
TASK_COMPLETE = "complete"
TASK_SKIPPED = "skipped"
TASK_UNAVAILABLE = "unavailable"
TASK_FAILED = "failed"

TERMINAL_TASK_STATUSES = {
    TASK_COMPLETE,
    TASK_SKIPPED,
    TASK_UNAVAILABLE,
    TASK_FAILED,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskResult:
    status: str
    reason: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"status": self.status}
        if self.reason:
            payload["reason"] = self.reason
        if self.details:
            payload["details"] = self.details
        return payload


@dataclass
class TaskItem:
    id: str
    module: str
    stage: str
    action: str
    reason: str = ""
    status: str = TASK_PENDING
    required: bool = False
    result: Optional[TaskResult] = None
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)

    def mark(
        self,
        status: str,
        *,
        reason: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.status = status
        self.updated_at = _utc_now_iso()
        if status in TERMINAL_TASK_STATUSES:
            self.result = TaskResult(status=status, reason=reason, details=details or {})

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": self.id,
            "module": self.module,
            "stage": self.stage,
            "action": self.action,
            "reason": self.reason,
            "status": self.status,
            "required": self.required,
        }
        if self.result:
            payload["result"] = self.result.to_dict()
        return payload


@dataclass
class TaskPlan:
    tasks: List[TaskItem] = field(default_factory=list)

    def add(
        self,
        module: str,
        stage: str,
        action: str,
        reason: str = "",
        *,
        required: bool = False,
    ) -> TaskItem:
        task = TaskItem(
            id=f"{len(self.tasks) + 1:02d}_{module}",
            module=module,
            stage=stage,
            action=action,
            reason=reason,
            required=required,
        )
        self.tasks.append(task)
        return task

    def first(self, module: str) -> Optional[TaskItem]:
        for task in self.tasks:
            if task.module == module:
                return task
        return None

    def mark(
        self,
        module: str,
        status: str,
        *,
        reason: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        task = self.first(module)
        if task:
            task.mark(status, reason=reason, details=details)

    def to_list(self) -> List[Dict[str, Any]]:
        return [task.to_dict() for task in self.tasks]
