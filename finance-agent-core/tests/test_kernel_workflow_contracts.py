from dataclasses import FrozenInstanceError

import pytest

from src.shared.kernel.boundary_contracts import (
    CONTRACT_KIND_ARTIFACT_JSON,
    CONTRACT_KIND_INTERRUPT_PAYLOAD,
    CONTRACT_KIND_WORKFLOW_STATE,
)
from src.shared.kernel.tools.incident_logging import (
    CONTRACT_KIND_ARTIFACT_JSON as INCIDENT_ARTIFACT_JSON,
)
from src.shared.kernel.tools.incident_logging import (
    CONTRACT_KIND_INTERRUPT_PAYLOAD as INCIDENT_INTERRUPT_PAYLOAD,
)
from src.shared.kernel.tools.incident_logging import (
    CONTRACT_KIND_WORKFLOW_STATE as INCIDENT_WORKFLOW_STATE,
)
from src.shared.kernel.workflow_contracts import (
    WorkflowFanoutNodeResult,
    WorkflowNodeResult,
)
from src.shared.kernel.workflow_routing import (
    resolve_end_goto,
    resolve_end_goto_fanout,
)


def test_workflow_node_result_is_frozen_dataclass() -> None:
    result = WorkflowNodeResult(
        update={"node_statuses": {"intent": "running"}}, goto="END"
    )

    assert result.goto == "END"
    assert result.update["node_statuses"] == {"intent": "running"}

    with pytest.raises(FrozenInstanceError):
        result.goto = "searching"  # type: ignore[misc]


def test_workflow_fanout_node_result_accepts_list_goto() -> None:
    result = WorkflowFanoutNodeResult(
        update={"internal_progress": {"debate_aggregator": "done"}},
        goto=["fact_extractor", "r1_bull"],
    )

    assert result.goto == ["fact_extractor", "r1_bull"]


def test_boundary_contract_constants_are_stable_across_modules() -> None:
    assert CONTRACT_KIND_WORKFLOW_STATE == "workflow_state"
    assert CONTRACT_KIND_ARTIFACT_JSON == "artifact_json"
    assert CONTRACT_KIND_INTERRUPT_PAYLOAD == "interrupt_payload"

    assert INCIDENT_WORKFLOW_STATE == CONTRACT_KIND_WORKFLOW_STATE
    assert INCIDENT_ARTIFACT_JSON == CONTRACT_KIND_ARTIFACT_JSON
    assert INCIDENT_INTERRUPT_PAYLOAD == CONTRACT_KIND_INTERRUPT_PAYLOAD


def test_resolve_end_goto_maps_sentinel_to_framework_end() -> None:
    framework_end = "__end__"

    assert resolve_end_goto("END", end_node=framework_end) == "__end__"
    assert resolve_end_goto("search_node", end_node=framework_end) == "search_node"


def test_resolve_end_goto_fanout_maps_each_branch() -> None:
    framework_end = "__end__"

    assert resolve_end_goto_fanout("END", end_node=framework_end) == "__end__"
    assert resolve_end_goto_fanout(
        ["r1_bull", "END", "r1_bear"], end_node=framework_end
    ) == ["r1_bull", "__end__", "r1_bear"]
