from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.artifacts.application.service import ArtifactService
from src.artifacts.domain.deduplication import artifact_content
from src.artifacts.domain.record import ArtifactRecord


class InMemoryArtifactRepository:
    def __init__(self) -> None:
        self.records: dict[str, ArtifactRecord] = {}
        self.dedupe_ids: dict[str, str] = {}

    async def save(self, artifact: ArtifactRecord) -> str:
        if artifact.dedupe_key is not None:
            existing_id = self.dedupe_ids.get(artifact.dedupe_key)
            if existing_id is not None:
                existing = self.records[existing_id]
                if artifact_content(existing.envelope) != artifact_content(
                    artifact.envelope
                ):
                    raise ValueError("artifact dedupe key has conflicting payload")
                return existing_id
            self.dedupe_ids[artifact.dedupe_key] = artifact.artifact_id
        self.records[artifact.artifact_id] = artifact
        return artifact.artifact_id

    async def get_by_id(self, artifact_id: str) -> ArtifactRecord | None:
        return self.records.get(artifact_id)


@pytest.fixture
def repository() -> InMemoryArtifactRepository:
    return InMemoryArtifactRepository()


@pytest.fixture
def service(repository: InMemoryArtifactRepository) -> ArtifactService:
    return ArtifactService(repository=repository)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_save_and_retrieve_artifact(service: ArtifactService) -> None:
    payload = {
        "ticker": "AAPL",
        "news_items": [{"title": "Headline", "sentiment": 0.8}],
    }

    artifact_id = await service.save_artifact(
        data=payload,
        artifact_type="news_items",
        produced_by="tests.artifact_service",
        key_prefix="AAPL",
        thread_id="thread-123",
    )

    record = await service.get_artifact(artifact_id)
    assert record is not None
    assert record.artifact_id == artifact_id
    assert record.kind == "news_items"
    assert record.envelope.data == payload
    assert record.envelope.version == "v1"
    assert record.thread_id == "thread-123"
    assert record.key == "news_items_AAPL"


@pytest.mark.anyio
async def test_save_without_optional_fields_keeps_them_empty(
    service: ArtifactService,
) -> None:
    artifact_id = await service.save_artifact(
        data={"result": 150.25},
        artifact_type="calculation_result",
        produced_by="tests.artifact_service",
    )

    record = await service.get_artifact(artifact_id)
    assert record is not None
    assert record.key is None
    assert record.thread_id is None


@pytest.mark.anyio
async def test_save_list_payload_and_read_distinguishes_missing_from_empty(
    service: ArtifactService,
) -> None:
    artifact_id = await service.save_artifact(
        data=[],
        artifact_type="news_items",
        produced_by="tests.artifact_service",
    )

    assert await service.get_artifact_data(artifact_id, "news_items") == []
    assert await service.get_artifact_data("missing", "news_items") is None


@pytest.mark.anyio
async def test_get_artifact_data_rejects_a_different_kind(
    service: ArtifactService,
) -> None:
    artifact_id = await service.save_artifact(
        data={"ticker": "AAPL"},
        artifact_type="news_items",
        produced_by="tests.artifact_service",
    )

    with pytest.raises(TypeError, match="expected 'financial_reports'"):
        await service.get_artifact_data(artifact_id, "financial_reports")


@pytest.mark.anyio
async def test_save_is_idempotent_for_same_workflow_context_and_payload(
    service: ArtifactService,
    repository: InMemoryArtifactRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = SimpleNamespace(
        thread_id="thread-123",
        run_id="run-456",
        source_run_id="source-run-123",
    )
    monkeypatch.setattr(
        "src.artifacts.application.service.get_workflow_execution_context",
        lambda: context,
    )

    first_id = await service.save_artifact(
        data={"ticker": "AAPL"},
        artifact_type="news_items",
        produced_by="news.fetch",
    )
    second_id = await service.save_artifact(
        data={"ticker": "AAPL"},
        artifact_type="news_items",
        produced_by="news.fetch",
    )

    assert first_id == second_id
    assert len(repository.records) == 1
    record = repository.records[first_id]
    assert record.thread_id == "thread-123"
    assert record.dedupe_key is not None


def test_artifact_dedupe_content_ignores_envelope_timestamp() -> None:
    from src.artifacts.public import ArtifactEnvelope

    first = ArtifactEnvelope(
        kind="news_items",
        produced_by="news.fetch",
        created_at="2026-10-30T10:00:00+00:00",
        data={"ticker": "AAPL"},
    )
    replay = first.model_copy(update={"created_at": "2026-10-30T10:01:00+00:00"})

    assert artifact_content(first) == artifact_content(replay)
