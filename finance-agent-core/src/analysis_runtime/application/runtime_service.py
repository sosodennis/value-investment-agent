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
    ActivitySnapshot,
    ReplayPage,
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
            thread_id=thread_id, run_id=selected_run_id, status="queued", now=now
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

    async def cancel(self, *, principal_id: str, thread_id: str, run_id: str) -> None:
        await self._check_owner(principal_id=principal_id, thread_id=thread_id)
        run = await self.repository.get_run(thread_id=thread_id)
        if run is None or run.run_id != run_id:
            raise RunNotFoundError("run was not found")
        task = self._tasks.get(thread_id)
        if task and not task.done():
            task.cancel()
        else:
            await self.repository.set_run(
                thread_id=thread_id,
                run_id=run_id,
                status="cancelled",
                now=datetime.now(timezone.utc),
            )

    async def snapshot(
        self, *, principal_id: str, thread_id: str, run_id: str | None = None
    ) -> ActivitySnapshot:
        await self._check_owner(principal_id=principal_id, thread_id=thread_id)
        run = await self.repository.get_run(thread_id=thread_id)
        if run is None:
            raise ThreadNotFoundError("thread was not found")
        if run_id is not None and run.run_id != run_id:
            raise RunNotFoundError("run was not found")
        return await self.repository.snapshot(thread_id=thread_id, run_id=run.run_id)

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

    async def _persist_and_publish(self, event: ActivityEvent) -> None:
        async with self._subscription_gate:
            try:
                inserted = await self.repository.append_atomic(event)
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
            )
            async for item in self.runner.run(
                thread_id=thread_id,
                run_id=run_id,
                input_data=input_data,
                principal_id=principal_id,
            ):
                activity = (
                    item
                    if isinstance(item, Activity)
                    else Activity.model_validate(item)
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
                )
            )
            await self.repository.set_run(
                thread_id=thread_id,
                run_id=run_id,
                status="completed",
                now=datetime.now(timezone.utc),
            )
        except asyncio.CancelledError:
            await self._emit_terminal(
                thread_id=thread_id,
                run_id=run_id,
                status="cancelled",
                label="Workflow cancelled",
            )
            await self.repository.set_run(
                thread_id=thread_id,
                run_id=run_id,
                status="cancelled",
                now=datetime.now(timezone.utc),
            )
            raise
        except Exception:
            await self._emit_terminal(
                thread_id=thread_id,
                run_id=run_id,
                status="failed",
                label="Workflow failed",
            )
            await self.repository.set_run(
                thread_id=thread_id,
                run_id=run_id,
                status="failed",
                now=datetime.now(timezone.utc),
            )
        finally:
            self._tasks.pop(thread_id, None)

    async def _emit_terminal(
        self, *, thread_id: str, run_id: str, status: str, label: str
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
