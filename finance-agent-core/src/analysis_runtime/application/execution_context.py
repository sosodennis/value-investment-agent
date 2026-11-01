from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass

from src.analysis_runtime.domain.contracts import CheckpointIdentity


@dataclass(frozen=True)
class WorkflowExecutionContext:
    thread_id: str
    run_id: str
    principal_id: str = "unscoped"
    organization_id: str = "unscoped"
    membership_id: str = "unscoped"
    source_run_id: str | None = None
    checkpoint: CheckpointIdentity | None = None


_current_context: ContextVar[WorkflowExecutionContext | None] = ContextVar(
    "workflow_execution_context", default=None
)


def set_workflow_execution_context(
    context: WorkflowExecutionContext,
) -> Token[WorkflowExecutionContext | None]:
    return _current_context.set(context)


def reset_workflow_execution_context(
    token: Token[WorkflowExecutionContext | None],
) -> None:
    _current_context.reset(token)


def get_workflow_execution_context() -> WorkflowExecutionContext | None:
    return _current_context.get()
