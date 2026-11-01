import hashlib
import json
import uuid
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.analysis_runtime.application.execution_context import (
    get_workflow_execution_context,
)
from src.interface.artifacts.artifact_envelope import (
    ArtifactEnvelope,
    ArtifactPayload,
    build_artifact_envelope,
    parse_artifact_envelope,
    parse_artifact_payload,
)

from ..infrastructure.database import AsyncSessionLocal
from ..infrastructure.models import Artifact, WorkflowActivityEvent, WorkflowRunHistory


class ArtifactManager:
    """
    Service for managing artifact storage and retrieval.
    Artifacts are large JSON payloads (e.g., news items, financial statements)
    that are stored separately from the main state to optimize checkpoint size.
    """

    @staticmethod
    async def save_artifact(
        data: ArtifactPayload,
        artifact_type: str,
        produced_by: str,
        key_prefix: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        """
        Save an artifact to the database.

        Args:
            data: Canonical artifact payload (stored inside ArtifactEnvelope.data)
            artifact_type: Artifact kind identifier
            produced_by: Node identity that produced this artifact
            key_prefix: Optional semantic key prefix for debugging (e.g., "AAPL")
            thread_id: Optional thread ID to associate with this artifact

        Returns:
            The artifact ID (UUID string) for reference

        Example:
            artifact_id = await artifact_manager.save_artifact(
                data={"news": [...]},
                artifact_type="news_items",
                key_prefix="AAPL",
                thread_id="thread_123"
            )
        """
        envelope = build_artifact_envelope(
            kind=artifact_type,
            produced_by=produced_by,
            data=data,
        )
        context = get_workflow_execution_context()
        dedupe_key = None
        effective_thread_id = thread_id
        if context is not None:
            serialized_content = json.dumps(
                _artifact_content(envelope),
                sort_keys=True,
                separators=(",", ":"),
            )
            dedupe_key = _artifact_dedupe_key(
                thread_id=context.thread_id,
                source_run_id=context.source_run_id or context.run_id,
                produced_by=produced_by,
                artifact_type=artifact_type,
                payload_hash=hashlib.sha256(
                    serialized_content.encode("utf-8")
                ).hexdigest(),
            )
            effective_thread_id = effective_thread_id or context.thread_id

        # Generate semantic key if prefix provided
        key = None
        if key_prefix:
            key = f"{artifact_type}_{key_prefix}"

        async with AsyncSessionLocal() as session:
            if dedupe_key is not None:
                existing = await session.scalar(
                    select(Artifact)
                    .where(Artifact.dedupe_key == dedupe_key)
                    .with_for_update()
                )
                if existing is not None:
                    if _artifact_content(existing.data) != _artifact_content(envelope):
                        raise ValueError("artifact dedupe key has conflicting payload")
                    return existing.id
            artifact = Artifact(
                id=str(uuid.uuid4()),
                key=key,
                thread_id=effective_thread_id,
                type=artifact_type,
                data=envelope.model_dump(mode="json"),
                dedupe_key=dedupe_key,
            )
            session.add(artifact)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                if dedupe_key is None:
                    raise
                existing = await session.scalar(
                    select(Artifact).where(Artifact.dedupe_key == dedupe_key)
                )
                if existing is None or _artifact_content(
                    existing.data
                ) != _artifact_content(envelope):
                    raise
                return existing.id
            await session.refresh(artifact)

        return artifact.id

    @staticmethod
    async def get_artifact(artifact_id: str) -> Artifact | None:
        """
        Retrieve an artifact by its ID.

        Args:
            artifact_id: The UUID of the artifact to retrieve

        Returns:
            The Artifact model instance, or None if not found
        """
        async with AsyncSessionLocal() as session:
            artifact = await session.get(Artifact, artifact_id)
            return artifact

    @staticmethod
    async def get_artifact_thread_id(artifact_id: str) -> str | None:
        async with AsyncSessionLocal() as session:
            return await session.scalar(
                select(Artifact.thread_id).where(Artifact.id == artifact_id)
            )

    @staticmethod
    async def belongs_to_organization(
        *,
        thread_id: str,
        organization_id: str,
        run_id: str | None = None,
    ) -> bool:
        """Verify the resolved artifact thread belongs to the active organization."""
        async with AsyncSessionLocal() as session:
            statement = (
                select(WorkflowRunHistory.thread_id)
                .where(WorkflowRunHistory.thread_id == thread_id)
                .where(WorkflowRunHistory.organization_id == organization_id)
            )
            if run_id is not None:
                statement = statement.where(WorkflowRunHistory.run_id == run_id)
            return await session.scalar(statement) is not None

    @staticmethod
    async def get_agent_output_thread_id(
        *, artifact_id: str, run_id: str
    ) -> str | None:
        async with AsyncSessionLocal() as session:
            return await session.scalar(
                select(WorkflowActivityEvent.thread_id)
                .where(WorkflowActivityEvent.run_id == run_id)
                .where(WorkflowActivityEvent.event_name == "workflow.agent_output")
                .where(
                    WorkflowActivityEvent.payload["artifact_id"].as_string()
                    == artifact_id
                )
                .limit(1)
            )

    @staticmethod
    async def get_referenced_artifact_thread_id(
        *, artifact_id: str, run_id: str
    ) -> str | None:
        """Resolve a child artifact through a same-run agent output.

        Some report producers persist their parent report and its supplementary
        artifacts without an ``artifacts.thread_id``. The parent output event
        is still the durable run boundary, so a child is accessible only when
        its ID appears in the parent's explicit artifact-reference section.
        """
        return await ArtifactManager._find_referenced_artifact_thread_id(
            artifact_id=artifact_id,
            run_id=run_id,
        )

    @staticmethod
    async def is_referenced_artifact_reference(
        *, artifact_id: str, thread_id: str
    ) -> bool:
        """Report whether an artifact is referenced by an output in this thread.

        The no-run guard must reject referenced children, while unrelated
        artifacts in other threads must not affect this lookup.
        """
        return (
            await ArtifactManager._find_referenced_artifact_thread_id(
                artifact_id=artifact_id,
                thread_id=thread_id,
            )
        ) is not None

    @staticmethod
    async def is_agent_output_reference_any_thread(*, artifact_id: str) -> bool:
        async with AsyncSessionLocal() as session:
            event_id = await session.scalar(
                select(WorkflowActivityEvent.event_id)
                .where(WorkflowActivityEvent.event_name == "workflow.agent_output")
                .where(
                    WorkflowActivityEvent.payload["artifact_id"].as_string()
                    == artifact_id
                )
            )
        return event_id is not None

    @staticmethod
    async def _find_referenced_artifact_thread_id(
        *, artifact_id: str, run_id: str | None = None, thread_id: str | None = None
    ) -> str | None:
        async with AsyncSessionLocal() as session:
            statement = select(WorkflowActivityEvent).where(
                WorkflowActivityEvent.event_name == "workflow.agent_output"
            )
            if run_id is not None:
                statement = statement.where(WorkflowActivityEvent.run_id == run_id)
            if thread_id is not None:
                statement = statement.where(
                    WorkflowActivityEvent.thread_id == thread_id
                )
            output_events = (await session.scalars(statement)).all()
            parent_ids = {
                payload_artifact_id
                for event in output_events
                if isinstance(event.payload, Mapping)
                and isinstance(
                    payload_artifact_id := event.payload.get("artifact_id"), str
                )
                and payload_artifact_id != artifact_id
            }
            if not parent_ids:
                return None

            parent_artifacts = (
                await session.scalars(
                    select(Artifact).where(Artifact.id.in_(parent_ids))
                )
            ).all()
            artifacts_by_id = {artifact.id: artifact for artifact in parent_artifacts}
            for event in output_events:
                if not isinstance(event.payload, Mapping):
                    continue
                parent_id = event.payload.get("artifact_id")
                parent = artifacts_by_id.get(parent_id)
                if parent is not None and _references_artifact(
                    parent.data, artifact_id
                ):
                    return event.thread_id
        return None

    @staticmethod
    async def is_agent_output_for_run(
        *, artifact_id: str, thread_id: str, run_id: str
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

    @staticmethod
    async def is_referenced_artifact_for_run(
        *, artifact_id: str, thread_id: str, run_id: str
    ) -> bool:
        return (
            await ArtifactManager.get_referenced_artifact_thread_id(
                artifact_id=artifact_id,
                run_id=run_id,
            )
        ) == thread_id

    @staticmethod
    async def is_agent_output_reference(*, artifact_id: str, thread_id: str) -> bool:
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

    @staticmethod
    async def get_artifact_envelope(artifact_id: str) -> ArtifactEnvelope | None:
        artifact = await ArtifactManager.get_artifact(artifact_id)
        if artifact is None:
            return None
        return parse_artifact_envelope(artifact.data, f"artifact {artifact_id}")

    @staticmethod
    async def get_artifact_data(
        artifact_id: str, expected_kind: str | None = None
    ) -> ArtifactPayload | None:
        artifact = await ArtifactManager.get_artifact(artifact_id)
        if artifact is None:
            return None
        return parse_artifact_payload(
            artifact.data,
            context=f"artifact {artifact_id}",
            expected_kind=expected_kind,
        )


# Singleton instance
artifact_manager = ArtifactManager()


def _artifact_dedupe_key(
    *,
    thread_id: str,
    source_run_id: str,
    produced_by: str,
    artifact_type: str,
    payload_hash: str,
) -> str:
    payload = {
        "version": "workflow-artifact-v1",
        "thread_id": thread_id,
        "source_run_id": source_run_id,
        "produced_by": produced_by,
        "artifact_type": artifact_type,
        "payload_hash": payload_hash,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _artifact_content(
    value: ArtifactEnvelope | Mapping[str, object],
) -> dict[str, object]:
    if isinstance(value, ArtifactEnvelope):
        return {
            "kind": value.kind,
            "version": value.version,
            "produced_by": value.produced_by,
            "data": value.data,
        }
    return {
        "kind": value.get("kind"),
        "version": value.get("version"),
        "produced_by": value.get("produced_by"),
        "data": value.get("data"),
    }


def _references_artifact(value: object, artifact_id: str) -> bool:
    """Check only explicit artifact-reference fields in a stored payload."""
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key == "artifact_refs":
                if _contains_string(nested, artifact_id):
                    return True
            elif key == "artifact_id" or key.endswith("_artifact_id"):
                if nested == artifact_id:
                    return True
            elif _references_artifact(nested, artifact_id):
                return True
    elif isinstance(value, list):
        return any(_references_artifact(item, artifact_id) for item in value)
    return False


def _contains_string(value: object, target: str) -> bool:
    if isinstance(value, str):
        return value == target
    if isinstance(value, Mapping):
        return any(_contains_string(item, target) for item in value.values())
    if isinstance(value, list):
        return any(_contains_string(item, target) for item in value)
    return False
