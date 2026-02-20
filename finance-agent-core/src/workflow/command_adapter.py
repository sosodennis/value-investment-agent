from __future__ import annotations

from typing import Protocol

from langgraph.types import Command

from src.shared.kernel.workflow_routing import (
    resolve_end_goto,
    resolve_end_goto_fanout,
)


class _WorkflowResultLike(Protocol):
    update: dict[str, object]
    goto: str


class _WorkflowFanoutResultLike(Protocol):
    update: dict[str, object]
    goto: str | list[str]


def command_from_result(result: _WorkflowResultLike, *, end_node: str) -> Command:
    return Command(
        update=result.update,
        goto=resolve_end_goto(result.goto, end_node=end_node),
    )


def command_from_fanout_result(
    result: _WorkflowFanoutResultLike, *, end_node: str
) -> Command:
    return Command(
        update=result.update,
        goto=resolve_end_goto_fanout(result.goto, end_node=end_node),
    )


def command_from_update(
    update: dict[str, object], *, goto: str, end_node: str
) -> Command:
    return Command(update=update, goto=resolve_end_goto(goto, end_node=end_node))
