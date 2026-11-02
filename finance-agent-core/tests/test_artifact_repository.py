from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from src.artifacts.domain.envelope import build_artifact_envelope
from src.artifacts.domain.record import ArtifactRecord
from src.artifacts.infrastructure.sqlalchemy_repository import (
    SqlAlchemyArtifactRepository,
)


def _session_context(session: AsyncMock | MagicMock) -> MagicMock:
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


def _record(
    *, artifact_id: str = "artifact-123", data: object = None
) -> ArtifactRecord:
    envelope = build_artifact_envelope(
        kind="news_items",
        produced_by="news.fetch",
        data=data if isinstance(data, dict | list) else {"ticker": "AAPL"},
    )
    return ArtifactRecord(
        artifact_id=artifact_id,
        key=None,
        thread_id="thread-123",
        kind="news_items",
        envelope=envelope,
        dedupe_key="dedupe-123",
    )


@pytest.mark.anyio
async def test_get_thread_id_reads_metadata_without_loading_payload() -> None:
    session = AsyncMock()
    session.scalar.return_value = "thread-123"

    with patch(
        "src.artifacts.infrastructure.sqlalchemy_repository.AsyncSessionLocal",
        return_value=_session_context(session),
    ):
        thread_id = await SqlAlchemyArtifactRepository().get_thread_id("artifact-123")

    assert thread_id == "thread-123"
    statement = session.scalar.await_args.args[0].compile()
    sql = str(statement)
    assert "artifacts.thread_id" in sql
    assert "artifacts.data" not in sql
    assert "artifact-123" in statement.params.values()


@pytest.mark.anyio
async def test_run_thread_resolution_requires_one_run_in_the_active_organization() -> (
    None
):
    result = MagicMock()
    result.all.return_value = ["thread-123"]
    session = MagicMock()
    session.scalars = AsyncMock(return_value=result)

    with patch(
        "src.artifacts.infrastructure.sqlalchemy_repository.AsyncSessionLocal",
        return_value=_session_context(session),
    ):
        thread_id = await SqlAlchemyArtifactRepository().get_run_thread_id(
            run_id="run-123",
            organization_id="org-123",
        )

    assert thread_id == "thread-123"
    statement = session.scalars.await_args.args[0].compile()
    assert "workflow_run_history.run_id" in str(statement)
    assert "workflow_run_history.organization_id" in str(statement)
    assert {"run-123", "org-123"}.issubset(set(statement.params.values()))


@pytest.mark.anyio
async def test_ambiguous_run_id_does_not_resolve_a_thread() -> None:
    result = MagicMock()
    result.all.return_value = ["thread-a", "thread-b"]
    session = MagicMock()
    session.scalars = AsyncMock(return_value=result)

    with patch(
        "src.artifacts.infrastructure.sqlalchemy_repository.AsyncSessionLocal",
        return_value=_session_context(session),
    ):
        thread_id = await SqlAlchemyArtifactRepository().get_run_thread_id(
            run_id="duplicate-run",
            organization_id="org-123",
        )

    assert thread_id is None


@pytest.mark.anyio
async def test_child_reference_lookup_is_scoped_to_owned_thread_and_run() -> None:
    output_event = SimpleNamespace(
        thread_id="thread-123",
        payload={"artifact_id": "parent-report"},
    )
    parent_artifact = SimpleNamespace(
        id="parent-report",
        data={"data": {"artifact_refs": {"chart_data_id": "child-chart"}}},
    )
    events_result = MagicMock()
    events_result.all.return_value = [output_event]
    artifacts_result = MagicMock()
    artifacts_result.all.return_value = [parent_artifact]
    session = MagicMock()
    session.scalars = AsyncMock(side_effect=[events_result, artifacts_result])

    with patch(
        "src.artifacts.infrastructure.sqlalchemy_repository.AsyncSessionLocal",
        return_value=_session_context(session),
    ):
        referenced = (
            await SqlAlchemyArtifactRepository().is_referenced_artifact_for_run(
                artifact_id="child-chart",
                thread_id="thread-123",
                run_id="run-123",
            )
        )

    assert referenced is True
    event_query = session.scalars.await_args_list[0].args[0].compile()
    assert "workflow_activity_events.thread_id" in str(event_query)
    assert "workflow_activity_events.run_id" in str(event_query)
    assert {"thread-123", "run-123"}.issubset(set(event_query.params.values()))


@pytest.mark.anyio
async def test_save_returns_existing_id_for_same_dedupe_content() -> None:
    artifact = _record()
    existing = SimpleNamespace(
        id="stored-id",
        data=artifact.envelope.model_dump(mode="json"),
    )
    session = MagicMock()
    session.scalar = AsyncMock(return_value=existing)
    session.commit = AsyncMock()

    with patch(
        "src.artifacts.infrastructure.sqlalchemy_repository.AsyncSessionLocal",
        return_value=_session_context(session),
    ):
        artifact_id = await SqlAlchemyArtifactRepository().save(artifact)

    assert artifact_id == "stored-id"
    session.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_save_rejects_conflicting_content_for_existing_dedupe_key() -> None:
    artifact = _record(data={"ticker": "AAPL"})
    existing = SimpleNamespace(
        id="stored-id",
        data={
            "kind": "news_items",
            "version": "v1",
            "produced_by": "news.fetch",
            "data": {"ticker": "MSFT"},
        },
    )
    session = MagicMock()
    session.scalar = AsyncMock(return_value=existing)

    with (
        patch(
            "src.artifacts.infrastructure.sqlalchemy_repository.AsyncSessionLocal",
            return_value=_session_context(session),
        ),
        pytest.raises(ValueError, match="conflicting payload"),
    ):
        await SqlAlchemyArtifactRepository().save(artifact)


@pytest.mark.anyio
async def test_save_recovers_from_concurrent_unique_key_insert() -> None:
    artifact = _record()
    existing = SimpleNamespace(
        id="stored-id",
        data=artifact.envelope.model_dump(mode="json"),
    )
    session = MagicMock()
    session.scalar = AsyncMock(side_effect=[None, existing])
    session.commit = AsyncMock(
        side_effect=IntegrityError("insert", None, RuntimeError("unique"))
    )
    session.rollback = AsyncMock()

    with patch(
        "src.artifacts.infrastructure.sqlalchemy_repository.AsyncSessionLocal",
        return_value=_session_context(session),
    ):
        artifact_id = await SqlAlchemyArtifactRepository().save(artifact)

    assert artifact_id == "stored-id"
    session.rollback.assert_awaited_once()
