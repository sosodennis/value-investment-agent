from __future__ import annotations

import uuid

from src.analysis_runtime.application.execution_context import (
    get_workflow_execution_context,
)
from src.artifacts.domain.deduplication import artifact_dedupe_key
from src.artifacts.domain.envelope import (
    ArtifactEnvelope,
    ArtifactPayload,
    build_artifact_envelope,
    parse_artifact_payload,
)
from src.artifacts.domain.record import ArtifactRecord

from .ports import ArtifactRepositoryPort


class ArtifactService:
    def __init__(self, repository: ArtifactRepositoryPort) -> None:
        self._repository = repository

    async def save_artifact(
        self,
        data: ArtifactPayload,
        artifact_type: str,
        produced_by: str,
        key_prefix: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        envelope = build_artifact_envelope(
            kind=artifact_type,
            produced_by=produced_by,
            data=data,
        )
        context = get_workflow_execution_context()
        effective_thread_id = thread_id
        dedupe_key = None
        if context is not None:
            dedupe_key = artifact_dedupe_key(
                thread_id=context.thread_id,
                source_run_id=context.source_run_id or context.run_id,
                produced_by=produced_by,
                artifact_type=artifact_type,
                envelope=envelope,
            )
            effective_thread_id = effective_thread_id or context.thread_id

        key = f"{artifact_type}_{key_prefix}" if key_prefix else None
        record = ArtifactRecord(
            artifact_id=str(uuid.uuid4()),
            key=key,
            thread_id=effective_thread_id,
            kind=artifact_type,
            envelope=envelope,
            dedupe_key=dedupe_key,
        )
        return await self._repository.save(record)

    async def get_artifact(self, artifact_id: str) -> ArtifactRecord | None:
        return await self._repository.get_by_id(artifact_id)

    async def get_artifact_thread_id(self, artifact_id: str) -> str | None:
        return await self._repository.get_thread_id(artifact_id)

    async def get_run_thread_id(
        self, *, run_id: str, organization_id: str
    ) -> str | None:
        return await self._repository.get_run_thread_id(
            run_id=run_id,
            organization_id=organization_id,
        )

    async def belongs_to_organization(
        self,
        *,
        thread_id: str,
        organization_id: str,
        run_id: str | None = None,
    ) -> bool:
        return await self._repository.belongs_to_organization(
            thread_id=thread_id,
            organization_id=organization_id,
            run_id=run_id,
        )

    async def is_agent_output_reference(
        self, *, artifact_id: str, thread_id: str
    ) -> bool:
        return await self._repository.is_agent_output_reference(
            artifact_id=artifact_id,
            thread_id=thread_id,
        )

    async def is_agent_output_for_run(
        self, *, artifact_id: str, thread_id: str, run_id: str
    ) -> bool:
        return await self._repository.is_agent_output_for_run(
            artifact_id=artifact_id,
            thread_id=thread_id,
            run_id=run_id,
        )

    async def is_referenced_artifact_reference(
        self, *, artifact_id: str, thread_id: str
    ) -> bool:
        return await self._repository.is_referenced_artifact_reference(
            artifact_id=artifact_id,
            thread_id=thread_id,
        )

    async def is_referenced_artifact_for_run(
        self, *, artifact_id: str, thread_id: str, run_id: str
    ) -> bool:
        return await self._repository.is_referenced_artifact_for_run(
            artifact_id=artifact_id,
            thread_id=thread_id,
            run_id=run_id,
        )

    async def get_artifact_envelope(self, artifact_id: str) -> ArtifactEnvelope | None:
        record = await self._repository.get_by_id(artifact_id)
        return None if record is None else record.envelope

    async def get_artifact_data(
        self, artifact_id: str, expected_kind: str | None = None
    ) -> ArtifactPayload | None:
        record = await self._repository.get_by_id(artifact_id)
        if record is None:
            return None
        return parse_artifact_payload(
            record.envelope.model_dump(mode="json"),
            context=f"artifact {artifact_id}",
            expected_kind=expected_kind,
        )
