from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowNodeResult:
    """Canonical single-target workflow node result contract."""

    update: dict[str, object]
    goto: str


@dataclass(frozen=True)
class WorkflowFanoutNodeResult:
    """Canonical workflow node result contract with fan-out goto support."""

    update: dict[str, object]
    goto: str | list[str]
