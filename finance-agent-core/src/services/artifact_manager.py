import uuid

from src.interface.artifact_envelope import (
    ArtifactEnvelope,
    ArtifactPayload,
    build_artifact_envelope,
    parse_artifact_envelope,
    parse_artifact_payload,
)

from ..infrastructure.database import AsyncSessionLocal
from ..infrastructure.models import Artifact


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
        artifact_id = str(uuid.uuid4())
        envelope = build_artifact_envelope(
            kind=artifact_type,
            produced_by=produced_by,
            data=data,
        )

        # Generate semantic key if prefix provided
        key = None
        if key_prefix:
            key = f"{artifact_type}_{key_prefix}_{artifact_id[:8]}"

        async with AsyncSessionLocal() as session:
            artifact = Artifact(
                id=artifact_id,
                key=key,
                thread_id=thread_id,
                type=artifact_type,
                data=envelope.model_dump(mode="json"),
            )
            session.add(artifact)
            await session.commit()
            await session.refresh(artifact)

        return artifact_id

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
