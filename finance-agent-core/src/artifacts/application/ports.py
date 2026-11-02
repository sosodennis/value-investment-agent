from __future__ import annotations

from typing import Protocol

from src.artifacts.domain.envelope import ArtifactPayload
from src.artifacts.domain.record import ArtifactRecord


class ArtifactRepositoryPort(Protocol):
    async def save(self, artifact: ArtifactRecord) -> str: ...

    async def get_by_id(self, artifact_id: str) -> ArtifactRecord | None: ...

    async def get_thread_id(self, artifact_id: str) -> str | None: ...

    async def get_run_thread_id(
        self, *, run_id: str, organization_id: str
    ) -> str | None: ...

    async def belongs_to_organization(
        self, *, thread_id: str, organization_id: str, run_id: str | None = None
    ) -> bool: ...

    async def is_agent_output_reference(
        self, *, artifact_id: str, thread_id: str
    ) -> bool: ...

    async def is_agent_output_for_run(
        self, *, artifact_id: str, thread_id: str, run_id: str
    ) -> bool: ...

    async def is_referenced_artifact_reference(
        self, *, artifact_id: str, thread_id: str
    ) -> bool: ...

    async def is_referenced_artifact_for_run(
        self, *, artifact_id: str, thread_id: str, run_id: str
    ) -> bool: ...


class ArtifactStoragePort(Protocol):
    async def save_artifact(
        self,
        data: ArtifactPayload,
        artifact_type: str,
        produced_by: str,
        key_prefix: str | None = None,
        thread_id: str | None = None,
    ) -> str: ...

    async def get_artifact_data(
        self, artifact_id: str, expected_kind: str | None = None
    ) -> ArtifactPayload | None: ...
