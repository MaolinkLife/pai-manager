from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class GenerateRequest:
    """Универсальный запрос на генерацию текста."""

    messages: Iterable[Dict[str, Any]]
    options: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Any] = None


@dataclass
class GenerateResult:
    """Результат генерации в универсальном формате."""

    provider: str
    content: str
    raw: Any = None
    reasoning: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class GenerateStreamChunk:
    """Универсальный кусок потоковой генерации."""

    provider: str
    content: str
    raw: Any = None
    done: bool = False
    reasoning: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
