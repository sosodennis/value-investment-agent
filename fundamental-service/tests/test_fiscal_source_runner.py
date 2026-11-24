import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import asyncpg
import pytest
from fastapi import FastAPI
from sqlalchemy.engine import make_url

import fundamental_service.app as app_module
from fundamental_service.fiscal_source_runner import main
from fundamental_service.metadata import (
    PostgresArtifactStore,
    PostgresContentStore,
    PostgresMetadataStore,
    _check_metadata_budget,
)

import test_postgres_metadata

postgres_metadata = test_postgres_metadata.metadata
DATABASE_URL = test_postgres_metadata.DATABASE_URL


@pytest.fixture
def validation_execute() -> Mock:
    return Mock(return_value=({}, {}))


@pytest.fixture
def run_validation(
    monkeypatch: pytest.MonkeyPatch, validation_execute: Mock
) -> Callable[[str, object], int]:
    def run(artifact_id: str, store: object) -> int:
        closure = SimpleNamespace(execute=validation_execute)
        acquisition = SimpleNamespace(
            capture_store=store,
            fiscal_source_closure=lambda **_kwargs: closure,
        )

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            app.state.sec_acquisition = acquisition
            app.state.application = SimpleNamespace(ready=True)
            yield

        monkeypatch.setattr(app_module, "app", FastAPI(lifespan=lifespan))
        return main(
            [
                "--source-revision",
                "a" * 40,
                "--timeout-seconds",
                "1",
                "validate",
                "--discovery-artifact-id",
                artifact_id,
                "--accession",
                "0000320193-25-000057",
            ]
        )

    return run


def test_validate_applies_deadline_to_discovery_record_lookup(
    run_validation: Callable[[str, object], int], capsys: pytest.CaptureFixture[str]
) -> None:
    def get(artifact_id: str) -> SimpleNamespace:
        time.sleep(1.05)
        _check_metadata_budget()
        return SimpleNamespace(
            artifact_id=artifact_id,
            media_type="application/json",
            content_hash="a" * 64,
        )

    assert run_validation("fiscal-discovery-test", SimpleNamespace(get=get)) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err) == {
        "error_code": "REQUEST_DEADLINE_EXCEEDED",
        "retryable": True,
    }


@pytest.mark.skipif(not DATABASE_URL, reason="requires PostgreSQL acceptance storage")
def test_validate_cancels_postgres_discovery_record_lookup(
    run_validation: Callable[[str, object], int],
    postgres_metadata: PostgresMetadataStore,
    validation_execute: Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = PostgresArtifactStore(
        postgres_metadata, PostgresContentStore(tmp_path, postgres_metadata)
    )
    artifact_id = f"fiscal-discovery-{uuid4().hex}"
    record = store.put_with_receipt(artifact_id, {"value": "discovery"}).artifact
    assert DATABASE_URL is not None
    url = make_url(DATABASE_URL).set(drivername="postgresql")

    async def check_blocked_lookup() -> None:
        blocker = await asyncpg.connect(url.render_as_string(hide_password=False))
        try:
            async with blocker.transaction():
                await blocker.execute(
                    "LOCK TABLE fundamental.artifact_references IN ACCESS EXCLUSIVE MODE"
                )
                blocked_query = """
                    SELECT pid FROM pg_stat_activity
                    WHERE wait_event_type = 'Lock'
                    AND $1 = ANY(pg_blocking_pids(pid))
                    AND query LIKE '%FROM fundamental.artifact_references%'
                """

                async def blocked_pid() -> int | None:
                    await blocker.execute("SELECT pg_stat_clear_snapshot()")
                    return await blocker.fetchval(
                        blocked_query, blocker.get_server_pid()
                    )

                command = asyncio.create_task(
                    asyncio.to_thread(run_validation, artifact_id, store)
                )
                async with asyncio.timeout(3):
                    while await blocked_pid() is None:
                        assert not command.done(), (
                            "CLI finished before the lookup waited"
                        )
                        await asyncio.sleep(0.01)
                    assert await asyncio.shield(command) == 2
                    while await blocked_pid() is not None:
                        await asyncio.sleep(0.01)
        finally:
            await blocker.close()

    asyncio.run(check_blocked_lookup())
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err) == {
        "error_code": "REQUEST_DEADLINE_EXCEEDED",
        "retryable": True,
    }
    validation_execute.assert_not_called()
    assert store.get(artifact_id) == record
