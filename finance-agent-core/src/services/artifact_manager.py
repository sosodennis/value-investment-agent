import uuid

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
        data: dict | list,
        artifact_type: str,
        key_prefix: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        """
        Save an artifact to the database.

        Args:
            data: The JSON-serializable data to store
            artifact_type: Type identifier (e.g., "news_items", "financial_statements")
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
                data=data,
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


# Singleton instance
artifact_manager = ArtifactManager()
