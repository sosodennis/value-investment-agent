from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone

from src.analysis_runtime.application.ports import (
    ActivityRepository,
    GraphRunner,
    NotificationHub,
    OwnerPort,
    RuntimeSubscriber,
)
from src.analysis_runtime.domain.contracts import (
    Activity,
    ActivityEvent,
    AnalysisRunPage,
    InteractionIdentity,
    InteractionRequested,
    ReplayPage,
    RunStatus,
    TickerSelectionResponse,
    WorkflowEvent,
    WorkflowFailure,
    WorkflowSnapshot,
)
from src.analysis_runtime.domain.errors import (
    ActivityPersistenceError,
    RunAlreadyActiveError,
    RunNotFoundError,
    ThreadNotFoundError,
)
from src.analysis_runtime.infrastructure.notifications import (
    BoundedNotificationHub,
)

_SAFE_FAILURE_MESSAGES = {
    "schema_validation_failed": "The provider returned data that did not match the workflow contract.",
    "upstream_timeout": "The upstream provider timed out while the workflow was running.",
    "upstream_unavailable": "The upstream provider is unavailable.",
    "rate_limited": "The provider temporarily rate limited this workflow.",
    "authentication_failed": "The provider authentication configuration is unavailable.",
    "invalid_runner_interrupt": "The workflow produced an invalid interaction request.",
}


def _failure_from_exception(
    error: Exception, *, activity_id: str | None
) -> WorkflowFailure:
    raw_code = getattr(error, "code", None)
    code = getattr(raw_code, "value", raw_code)
    code = code if isinstance(code, str) and code else "workflow_runtime_error"
    owner = "llm_provider" if hasattr(error, "retryable") else "workflow.runtime"
    retryable = bool(getattr(error, "retryable", False))
    return WorkflowFailure(
        code=code,
        owner=owner,
        activity_id=activity_id,
        retryable=retryable,
        message=_SAFE_FAILURE_MESSAGES.get(
            code, "The workflow could not complete because an internal step failed."
        ),
    )


class AnalysisRuntimeService:
    """Coordinates runs while keeping persistence ahead of live delivery."""

    def __init__(
        self,
        *,
        repository: ActivityRepository,
        owner: OwnerPort,
        runner: GraphRunner,
        hub: NotificationHub | None = None,
        replay_limit: int = 200,
        heartbeat_seconds: float = 15.0,
    ) -> None:
        self.repository = repository
        self.owner = owner
        self.runner = runner
        self.hub = hub or BoundedNotificationHub()
        self.replay_limit = replay_limit
        self.heartbeat_seconds = heartbeat_seconds
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._subscription_gate = asyncio.Lock()

    async def _check_owner(self, *, principal_id: str, thread_id: str) -> None:
        if not await self.owner.owns(principal_id=principal_id, thread_id=thread_id):
            raise ThreadNotFoundError("thread was not found")

    async def start(
        self,
        *,
        principal_id: str,
        thread_id: str,
        input_data: Mapping[str, object],
        run_id: str | None = None,
    ) -> str:
        if not await self.owner.claim(principal_id=principal_id, thread_id=thread_id):
            raise ThreadNotFoundError("thread was not found")
        if thread_id in self._tasks and not self._tasks[thread_id].done():
            raise RunAlreadyActiveError("thread already has an active run")
        previous = await self.repository.get_run(thread_id=thread_id)
        if previous and previous.status in {"running", "waiting", "queued"}:
            raise RunAlreadyActiveError("thread already has an active run")
        selected_run_id = run_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        await self.repository.set_run(
            thread_id=thread_id,
            run_id=selected_run_id,
            status="queued",
            now=now,
            principal_id=principal_id,
            input_data=input_data,
        )
        task = asyncio.create_task(
            self._execute(
                principal_id=principal_id,
                thread_id=thread_id,
                run_id=selected_run_id,
                input_data=input_data,
            )
        )
        self._tasks[thread_id] = task
        return selected_run_id

    async def resume(
        self,
        *,
        principal_id: str,
        identity: InteractionIdentity,
        response: TickerSelectionResponse,
    ) -> str:
        await self._check_owner(principal_id=principal_id, thread_id=identity.thread_id)
        task = self._tasks.get(identity.thread_id)
        if task and not task.done():
            raise RunAlreadyActiveError("thread already has an active run")
        async with self._subscription_gate:
            claimed = await self.repository.claim_interaction_response(
                identity=identity,
                response=response,
                principal_id=principal_id,
                now=datetime.now(timezone.utc),
            )
            for event in claimed.events:
                await self.hub.publish(event)
        resume_input = {
            "interrupt_response": response.model_dump(mode="json"),
            "resuming_activity_id": identity.activity_id,
            "resuming_scope_path": list(claimed.scope_path),
            "resuming_attempt": claimed.attempt - 1,
        }
        self._tasks[identity.thread_id] = asyncio.create_task(
            self._execute(
                principal_id=principal_id,
                thread_id=identity.thread_id,
                run_id=identity.run_id,
                input_data=resume_input,
            )
        )
        return identity.run_id

    async def recover_pending_resumes(self) -> int:
        """Restart resume commands durably claimed before a process stopped."""
        pending = await self.repository.pending_resumes()
        recovered = 0
        for item in pending:
            thread_id = item.identity.thread_id
            if thread_id in self._tasks and not self._tasks[thread_id].done():
                continue
            resume_input = {
                "interrupt_response": item.response.model_dump(mode="json"),
                "resuming_activity_id": item.identity.activity_id,
                "resuming_scope_path": list(item.scope_path),
                "resuming_attempt": item.attempt - 1,
            }
            self._tasks[thread_id] = asyncio.create_task(
                self._execute(
                    principal_id=item.principal_id,
                    thread_id=thread_id,
                    run_id=item.identity.run_id,
                    input_data=resume_input,
                )
            )
            recovered += 1
        return recovered

    async def cancel(self, *, principal_id: str, thread_id: str, run_id: str) -> None:
        await self._check_owner(principal_id=principal_id, thread_id=thread_id)
        task = self._tasks.get(thread_id)
        async with self._subscription_gate:
            events = await self.repository.cancel_run_with_interaction(
                thread_id=thread_id,
                run_id=run_id,
                principal_id=principal_id,
                now=datetime.now(timezone.utc),
            )
            for event in events:
                await self.hub.publish(event)
        if not events:
            run = await self.repository.get_run(thread_id=thread_id)
            if run is None or run.run_id != run_id:
                raise RunNotFoundError("run was not found")
        if task and not task.done():
            task.cancel()

    async def snapshot(
        self, *, principal_id: str, thread_id: str, run_id: str | None = None
    ) -> WorkflowSnapshot:
        await self._check_owner(principal_id=principal_id, thread_id=thread_id)
        if run_id is None:
            run = await self.repository.get_run(thread_id=thread_id)
            if run is None:
                raise ThreadNotFoundError("thread was not found")
            run_id = run.run_id
        elif (
            await self.repository.get_run_history(
                principal_id=principal_id, thread_id=thread_id, run_id=run_id
            )
            is None
        ):
            raise RunNotFoundError("run was not found")
        return await self.repository.snapshot(thread_id=thread_id, run_id=run_id)

    async def list_run_history(
        self,
        *,
        principal_id: str,
        limit: int,
        before_started_at: datetime | None = None,
        before_thread_id: str | None = None,
        before_run_id: str | None = None,
    ) -> AnalysisRunPage:
        return await self.repository.list_run_history(
            principal_id=principal_id,
            limit=limit,
            before_started_at=before_started_at,
            before_thread_id=before_thread_id,
            before_run_id=before_run_id,
        )

    async def replay(
        self,
        *,
        principal_id: str,
        thread_id: str,
        after_seq: int,
        limit: int | None = None,
    ) -> ReplayPage:
        await self._check_owner(principal_id=principal_id, thread_id=thread_id)
        return await self.repository.replay(
            thread_id=thread_id,
            after_seq=after_seq,
            limit=min(limit or self.replay_limit, self.replay_limit),
        )

    async def subscribe(
        self,
        *,
        principal_id: str,
        thread_id: str,
        after_seq: int,
        limit: int | None = None,
    ) -> tuple[ReplayPage, RuntimeSubscriber]:
        await self._check_owner(principal_id=principal_id, thread_id=thread_id)
        async with self._subscription_gate:
            replay = await self.replay(
                principal_id=principal_id,
                thread_id=thread_id,
                after_seq=after_seq,
                limit=limit,
            )
            subscriber = await self.hub.subscribe(thread_id=thread_id)
        return replay, subscriber

    async def unsubscribe(self, subscriber: RuntimeSubscriber) -> None:
        await self.hub.unsubscribe(subscriber)

    async def _persist_and_publish(
        self, event: WorkflowEvent, *, run_status: RunStatus | None = None
    ) -> None:
        async with self._subscription_gate:
            try:
                inserted = await self.repository.append_atomic(
                    event, run_status=run_status
                )
            except Exception as exc:
                if isinstance(exc, ActivityPersistenceError):
                    raise
                raise ActivityPersistenceError(
                    "unable to persist activity event"
                ) from exc
            if inserted:
                await self.hub.publish(event)

    async def _execute(
        self,
        *,
        principal_id: str,
        thread_id: str,
        run_id: str,
        input_data: Mapping[str, object],
    ) -> None:
        try:
            await self.repository.set_run(
                thread_id=thread_id,
                run_id=run_id,
                status="running",
                now=datetime.now(timezone.utc),
                principal_id=principal_id,
            )
            suspended = False
            current_activity_id: str | None = None
            async for item in self.runner.run(
                thread_id=thread_id,
                run_id=run_id,
                input_data=input_data,
                principal_id=principal_id,
            ):
                if isinstance(item, InteractionRequested):
                    current_activity_id = item.activity.activity_id
                    suspended = True
                    async with self._subscription_gate:
                        events = await self.repository.record_waiting_interaction(
                            requested=item,
                            principal_id=principal_id,
                            now=datetime.now(timezone.utc),
                        )
                        for event in events:
                            await self.hub.publish(event)
                    break
                activity = (
                    item
                    if isinstance(item, Activity)
                    else Activity.model_validate(item)
                )
                current_activity_id = activity.activity_id
                if activity.status == "waiting":
                    raise ActivityPersistenceError(
                        "waiting activity requires a typed interaction request"
                    )
                current = await self.repository.replay(
                    thread_id=thread_id, after_seq=0, limit=1_000_000
                )
                next_seq = current.cursor + 1
                event = ActivityEvent(
                    event_id=str(uuid.uuid4()),
                    seq_id=next_seq,
                    thread_id=thread_id,
                    run_id=run_id,
                    occurred_at=datetime.now(timezone.utc),
                    payload=activity.model_copy(
                        update={"thread_id": thread_id, "run_id": run_id}
                    ),
                )
                await self._persist_and_publish(event)
            if suspended:
                return
            completion = Activity(
                activity_id="workflow",
                thread_id=thread_id,
                run_id=run_id,
                scope_path=("workflow",),
                kind="phase",
                status="completed",
                label="Workflow completed",
                progress=100,
                attempt=1,
            )
            current = await self.repository.replay(
                thread_id=thread_id, after_seq=0, limit=1_000_000
            )
            await self._persist_and_publish(
                ActivityEvent(
                    event_id=str(uuid.uuid4()),
                    seq_id=current.cursor + 1,
                    thread_id=thread_id,
                    run_id=run_id,
                    occurred_at=datetime.now(timezone.utc),
                    payload=completion,
                ),
                run_status="completed",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = _failure_from_exception(exc, activity_id=current_activity_id)
            await self._emit_terminal(
                thread_id=thread_id,
                run_id=run_id,
                status="failed",
                label="Workflow failed",
                failure=failure,
            )
            await self.repository.set_run(
                thread_id=thread_id,
                run_id=run_id,
                status="failed",
                now=datetime.now(timezone.utc),
                principal_id=principal_id,
            )
        finally:
            self._tasks.pop(thread_id, None)

    async def _emit_terminal(
        self,
        *,
        thread_id: str,
        run_id: str,
        status: str,
        label: str,
        failure: WorkflowFailure | None = None,
    ) -> None:
        try:
            current = await self.repository.replay(
                thread_id=thread_id, after_seq=0, limit=1_000_000
            )
            activity = Activity(
                activity_id="workflow",
                thread_id=thread_id,
                run_id=run_id,
                scope_path=("workflow",),
                kind="phase",
                status=status,
                label=label,
                attempt=1,
                failure=failure,
            )
            await self._persist_and_publish(
                ActivityEvent(
                    event_id=str(uuid.uuid4()),
                    seq_id=current.cursor + 1,
                    thread_id=thread_id,
                    run_id=run_id,
                    occurred_at=datetime.now(timezone.utc),
                    payload=activity,
                )
            )
        except Exception:
            # The run status remains the durable fallback when terminal event storage fails.
            return
