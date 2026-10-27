from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from src.analysis_runtime.domain.contracts import (
    Activity,
    ActivityEvent,
    InteractionIdentity,
    TickerCandidate,
    TickerSelectionRequest,
    TickerSelectionResponse,
    WorkflowAgentOutput,
    WorkflowAgentOutputEvent,
    WorkflowEvent,
    WorkflowInteraction,
    WorkflowInteractionEvent,
)

_EVENTS = TypeAdapter(WorkflowEvent)
_NOW = datetime(2026, 10, 26, tzinfo=timezone.utc)


def _identity() -> InteractionIdentity:
    return InteractionIdentity(
        thread_id="thread-1",
        run_id="run-1",
        activity_id="intent.clarifying",
        interaction_id="interaction-1",
    )


def _request() -> TickerSelectionRequest:
    return TickerSelectionRequest(
        type="ticker_selection",
        title="Choose a company",
        description="Select the intended company.",
        candidates=[TickerCandidate(symbol="AAPL", name="Apple Inc.", confidence=0.99)],
    )


def test_activity_contract_has_no_interaction_fields() -> None:
    activity = Activity(
        activity_id="intent.clarifying",
        thread_id="thread-1",
        run_id="run-1",
        scope_path=("intent", "clarifying"),
        kind="node",
        status="waiting",
        label="Ticker resolution",
        attempt=1,
    )
    event = ActivityEvent(
        event_id="event-1",
        seq_id=1,
        thread_id="thread-1",
        run_id="run-1",
        occurred_at=_NOW,
        payload=activity,
    )

    assert event.event_version == "v2"
    assert _EVENTS.validate_python(event.model_dump(mode="json")) == event
    with pytest.raises(ValidationError):
        Activity.model_validate(
            {**activity.model_dump(), "interruption": {"interaction_id": "old"}}
        )
    with pytest.raises(ValidationError, match="identity"):
        ActivityEvent.model_validate({**event.model_dump(), "run_id": "another-run"})


def test_interaction_event_enforces_lifecycle_identity_and_candidate() -> None:
    pending = WorkflowInteraction(
        identity=_identity(),
        kind="ticker_selection",
        status="pending",
        request=_request(),
    )
    event = WorkflowInteractionEvent(
        event_id="event-2",
        seq_id=2,
        thread_id="thread-1",
        run_id="run-1",
        occurred_at=_NOW,
        payload=pending,
    )

    assert _EVENTS.validate_python(event.model_dump(mode="json")) == event
    with pytest.raises(ValidationError, match="responded"):
        WorkflowInteraction(
            identity=_identity(),
            kind="ticker_selection",
            status="pending",
            request=_request(),
            response=TickerSelectionResponse(
                type="ticker_selection", selected_symbol="AAPL"
            ),
        )
    with pytest.raises(ValidationError, match="stored candidates"):
        WorkflowInteraction(
            identity=_identity(),
            kind="ticker_selection",
            status="responded",
            request=_request(),
            response=TickerSelectionResponse(
                type="ticker_selection", selected_symbol="MSFT"
            ),
        )
    with pytest.raises(ValidationError, match="identity"):
        WorkflowInteractionEvent.model_validate(
            {**event.model_dump(), "thread_id": "another-thread"}
        )


def test_agent_output_bounds_serialized_utf8_preview_and_keeps_artifact_reference() -> (
    None
):
    identity = _identity().model_dump(exclude={"interaction_id"})
    exact_limit = WorkflowAgentOutput(
        identity=identity,
        agent_id="intent",
        output_kind="ticker_selection",
        output_version="v1",
        summary="Ticker selected.",
        preview={"value": "é" * 8186},
        artifact_id="artifact-1",
    )
    event = WorkflowAgentOutputEvent(
        event_id="event-3",
        seq_id=3,
        thread_id="thread-1",
        run_id="run-1",
        occurred_at=_NOW,
        payload=exact_limit,
    )

    assert _EVENTS.validate_python(event.model_dump(mode="json")) == event
    with pytest.raises(ValidationError, match="16 KiB"):
        WorkflowAgentOutput(
            identity=identity,
            agent_id="intent",
            output_kind="ticker_selection",
            output_version="v1",
            summary="Ticker selected.",
            preview={"value": "é" * 8187},
            artifact_id="artifact-1",
        )
