from dataclasses import dataclass

from src.shared.kernel.workflow_contracts import (
    WorkflowFanoutNodeResult,
    WorkflowNodeResult,
)
from src.workflow.command_adapter import (
    command_from_fanout_result,
    command_from_result,
    command_from_update,
)


@dataclass(frozen=True)
class _ResultLike:
    update: dict[str, object]
    goto: str


def test_command_from_result_maps_end_sentinel() -> None:
    command = command_from_result(
        WorkflowNodeResult(update={"ok": True}, goto="END"),
        end_node="__end__",
    )

    assert command.update == {"ok": True}
    assert command.goto == "__end__"


def test_command_from_result_keeps_regular_goto() -> None:
    command = command_from_result(
        _ResultLike(update={"node": "search"}, goto="selector_node"),
        end_node="__end__",
    )

    assert command.update == {"node": "search"}
    assert command.goto == "selector_node"


def test_command_from_fanout_result_maps_end_for_each_branch() -> None:
    command = command_from_fanout_result(
        WorkflowFanoutNodeResult(
            update={"stage": "debate"},
            goto=["r1_bull", "END", "r1_bear"],
        ),
        end_node="__end__",
    )

    assert command.update == {"stage": "debate"}
    assert command.goto == ["r1_bull", "__end__", "r1_bear"]


def test_command_from_update_maps_end() -> None:
    command = command_from_update(
        {"status": "retry"},
        goto="END",
        end_node="__end__",
    )

    assert command.update == {"status": "retry"}
    assert command.goto == "__end__"
