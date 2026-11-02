from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.artifacts.domain.deduplication import artifact_content, references_artifact
from src.artifacts.domain.envelope import parse_artifact_envelope
from src.artifacts.domain.record import ArtifactRecord
from src.infrastructure.database import AsyncSessionLocal
from src.infrastructure.models import (
    Artifact,
    WorkflowActivityEvent,
    WorkflowRunHistory,
)


class SqlAlchemyArtifactRepository:
    async def save(self, artifact: ArtifactRecord) -> str:
        async with AsyncSessionLocal() as session:
            if artifact.dedupe_key is not None:
                existing = await session.scalar(
                    select(Artifact)
                    .where(Artifact.dedupe_key == artifact.dedupe_key)
                    .with_for_update()
                )
                if existing is not None:
                    self._assert_same_content(existing.data, artifact)
                    return existing.id

            stored = Artifact(
                id=artifact.artifact_id,
                key=artifact.key,
                thread_id=artifact.thread_id,
                type=artifact.kind,
                data=artifact.envelope.model_dump(mode="json"),
                dedupe_key=artifact.dedupe_key,
            )
            session.add(stored)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                if artifact.dedupe_key is None:
                    raise
                existing = await session.scalar(
                    select(Artifact).where(Artifact.dedupe_key == artifact.dedupe_key)
                )
                if existing is None:
                    raise
                self._assert_same_content(existing.data, artifact)
                return existing.id
            await session.refresh(stored)
            return stored.id

    async def get_by_id(self, artifact_id: str) -> ArtifactRecord | None:
        async with AsyncSessionLocal() as session:
            stored = await session.get(Artifact, artifact_id)
        if stored is None:
            return None
        envelope = parse_artifact_envelope(stored.data, f"artifact {artifact_id}")
        return ArtifactRecord(
            artifact_id=stored.id,
            key=stored.key,
            thread_id=stored.thread_id,
            kind=stored.type,
            envelope=envelope,
            dedupe_key=stored.dedupe_key,
        )

    async def get_thread_id(self, artifact_id: str) -> str | None:
        async with AsyncSessionLocal() as session:
            return await session.scalar(
                select(Artifact.thread_id).where(Artifact.id == artifact_id)
            )

    async def get_run_thread_id(
        self, *, run_id: str, organization_id: str
    ) -> str | None:
        async with AsyncSessionLocal() as session:
            thread_ids = await session.scalars(
                select(WorkflowRunHistory.thread_id)
                .where(WorkflowRunHistory.run_id == run_id)
                .where(WorkflowRunHistory.organization_id == organization_id)
                .distinct()
            )
            matches = thread_ids.all()
        if len(matches) != 1:
            return None
        return matches[0]

    async def belongs_to_organization(
        self,
        *,
        thread_id: str,
        organization_id: str,
        run_id: str | None = None,
    ) -> bool:
        async with AsyncSessionLocal() as session:
            statement = (
                select(WorkflowRunHistory.thread_id)
                .where(WorkflowRunHistory.thread_id == thread_id)
                .where(WorkflowRunHistory.organization_id == organization_id)
            )
            if run_id is not None:
                statement = statement.where(WorkflowRunHistory.run_id == run_id)
            return await session.scalar(statement) is not None

    async def is_agent_output_reference(
        self, *, artifact_id: str, thread_id: str
    ) -> bool:
        async with AsyncSessionLocal() as session:
            event_id = await session.scalar(
                select(WorkflowActivityEvent.event_id)
                .where(WorkflowActivityEvent.thread_id == thread_id)
                .where(WorkflowActivityEvent.event_name == "workflow.agent_output")
                .where(
                    WorkflowActivityEvent.payload["artifact_id"].as_string()
                    == artifact_id
                )
            )
        return event_id is not None

    async def is_agent_output_for_run(
        self, *, artifact_id: str, thread_id: str, run_id: str
    ) -> bool:
        async with AsyncSessionLocal() as session:
            event_id = await session.scalar(
                select(WorkflowActivityEvent.event_id)
                .where(WorkflowActivityEvent.thread_id == thread_id)
                .where(WorkflowActivityEvent.run_id == run_id)
                .where(WorkflowActivityEvent.event_name == "workflow.agent_output")
                .where(
                    WorkflowActivityEvent.payload["artifact_id"].as_string()
                    == artifact_id
                )
            )
        return event_id is not None

    async def is_referenced_artifact_reference(
        self, *, artifact_id: str, thread_id: str
    ) -> bool:
        return (
            await self._find_referenced_artifact_thread_id(
                artifact_id=artifact_id,
                thread_id=thread_id,
            )
            is not None
        )

    async def is_referenced_artifact_for_run(
        self, *, artifact_id: str, thread_id: str, run_id: str
    ) -> bool:
        return (
            await self._find_referenced_artifact_thread_id(
                artifact_id=artifact_id,
                thread_id=thread_id,
                run_id=run_id,
            )
            is not None
        )

    async def _find_referenced_artifact_thread_id(
        self,
        *,
        artifact_id: str,
        thread_id: str,
        run_id: str | None = None,
    ) -> str | None:
        async with AsyncSessionLocal() as session:
            statement = select(WorkflowActivityEvent).where(
                WorkflowActivityEvent.event_name == "workflow.agent_output",
                WorkflowActivityEvent.thread_id == thread_id,
            )
            if run_id is not None:
                statement = statement.where(WorkflowActivityEvent.run_id == run_id)
            output_events = (await session.scalars(statement)).all()
            parent_ids = {
                parent_id
                for event in output_events
                if isinstance(event.payload, Mapping)
                and isinstance(parent_id := event.payload.get("artifact_id"), str)
                and parent_id != artifact_id
            }
            if not parent_ids:
                return None

            parent_artifacts = (
                await session.scalars(
                    select(Artifact).where(Artifact.id.in_(parent_ids))
                )
            ).all()
            parent_data_by_id = {
                artifact.id: artifact.data for artifact in parent_artifacts
            }
            for event in output_events:
                if not isinstance(event.payload, Mapping):
                    continue
                parent_id = event.payload.get("artifact_id")
                parent_data = parent_data_by_id.get(parent_id)
                if parent_data is not None and references_artifact(
                    parent_data, artifact_id
                ):
                    return event.thread_id
        return None

    @staticmethod
    def _assert_same_content(existing_data: object, artifact: ArtifactRecord) -> None:
        existing_content = (
            artifact_content(existing_data)
            if isinstance(existing_data, Mapping)
            else {}
        )
        if existing_content != artifact_content(artifact.envelope):
            raise ValueError("artifact dedupe key has conflicting payload")
