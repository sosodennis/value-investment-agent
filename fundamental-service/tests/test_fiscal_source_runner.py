import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import asyncpg
import pytest
from fastapi import FastAPI
from sqlalchemy.engine import make_url

import fundamental_service.app as app_module
from fundamental_service.arelle_parser import ArelleParserError
from fundamental_service.fiscal_source_runner import main
from fundamental_service.fiscal_validation_contracts import (
    FiscalOriginalValidationEvidenceV1,
    FiscalOriginalValidationRequestV1,
    FiscalValidationMatchedV1,
)
from fundamental_service.metadata import (
    PostgresArtifactStore,
    PostgresContentStore,
    PostgresMetadataStore,
    _check_metadata_budget,
)
from fundamental_service.replay import ArtifactPublicationV1

import test_postgres_metadata
from test_fiscal_discovery import DiscoveryHarness
from test_fiscal_source_closure import SyntheticCompleteSource, _closure

postgres_metadata = test_postgres_metadata.metadata
DATABASE_URL = test_postgres_metadata.DATABASE_URL


def _install_acquisition(
    monkeypatch: pytest.MonkeyPatch,
    acquisition: object,
    *,
    annual: object | None = None,
) -> None:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.sec_acquisition = annual
        app.state.fiscal_sec_acquisition = acquisition
        app.state.application = SimpleNamespace(ready=True)
        yield

    monkeypatch.setattr(app_module, "app", FastAPI(lifespan=lifespan))


@pytest.mark.parametrize(
    "command",
    [
        [
            "discover",
            "--cik",
            "320193",
            "--valuation-timestamp",
            "2025-01-01T00:00:00Z",
        ],
        [
            "validate",
            "--discovery-artifact-id",
            "synthetic",
            "--accession",
            "0000320193-25-000057",
        ],
        ["read", "--artifact-id", "synthetic"],
        ["focus-witness", "--source-artifact-id", "synthetic"],
        ["read-focus-witness", "--artifact-id", "synthetic"],
    ],
)
def test_cli_selects_fiscal_owner(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: list[str],
) -> None:
    def refuse(owner: str) -> None:
        from fundamental_service.snapshots import SnapshotError

        raise SnapshotError(f"SYNTHETIC_{owner}_OWNER", "synthetic owner selected")

    _install_acquisition(
        monkeypatch,
        SimpleNamespace(
            fiscal_source_closure=lambda **_kwargs: refuse("FISCAL"),
            fiscal_focus_witness=lambda **_kwargs: refuse("FISCAL"),
        ),
        annual=SimpleNamespace(
            fiscal_source_closure=lambda **_kwargs: refuse("ANNUAL"),
            fiscal_focus_witness=lambda **_kwargs: refuse("ANNUAL"),
        ),
    )
    assert main(["--source-revision", "a" * 40, *command]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err)["error_code"] == "SYNTHETIC_FISCAL_OWNER"


@pytest.mark.parametrize(
    "command",
    [
        [
            "discover",
            "--cik",
            "320193",
            "--valuation-timestamp",
            "2025-01-01T00:00:00Z",
        ],
        [
            "validate",
            "--discovery-artifact-id",
            "synthetic",
            "--accession",
            "0000320193-25-000057",
        ],
        ["read", "--artifact-id", "synthetic"],
        ["focus-witness", "--source-artifact-id", "synthetic"],
        ["read-focus-witness", "--artifact-id", "synthetic"],
    ],
)
def test_cli_refuses_missing_fiscal_owner(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: list[str],
) -> None:
    annual = Mock()
    _install_acquisition(monkeypatch, None, annual=annual)
    assert main(["--source-revision", "a" * 40, *command]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err)["error_code"] == "FISCAL_VALIDATION_UNCONFIGURED"
    assert not annual.mock_calls


@pytest.mark.parametrize(
    ("error_code", "retryable"),
    [("PARSER_RESOURCE_POLICY_INVALID", False), ("REQUEST_DEADLINE_EXCEEDED", True)],
)
def test_cli_reports_parser_failures_as_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error_code: str,
    retryable: bool,
) -> None:
    def invalid_resource_policy(**_kwargs):
        raise ArelleParserError(error_code, "synthetic failure")

    _install_acquisition(
        monkeypatch, SimpleNamespace(fiscal_focus_witness=invalid_resource_policy)
    )
    assert (
        main(
            [
                "--source-revision",
                "a" * 40,
                "read-focus-witness",
                "--artifact-id",
                "synthetic",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err) == {
        "error_code": error_code,
        "retryable": retryable,
    }


def test_cli_applies_deadline_to_runtime_startup(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        time.sleep(1.05)
        _check_metadata_budget()
        yield

    monkeypatch.setattr(app_module, "app", FastAPI(lifespan=lifespan))
    assert (
        main(
            [
                "--source-revision",
                "a" * 40,
                "--timeout-seconds",
                "1",
                "read",
                "--artifact-id",
                "synthetic",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err) == {
        "error_code": "REQUEST_DEADLINE_EXCEEDED",
        "retryable": True,
    }


def test_cli_outputs_retained_fiscal_evidence_as_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = DiscoveryHarness(tmp_path)
    closure = _closure(harness, SyntheticCompleteSource(harness, blocked=False))
    request = harness.request

    def execute(
        selection: FiscalOriginalValidationRequestV1, *, deadline_at: datetime
    ) -> tuple[FiscalOriginalValidationEvidenceV1, ArtifactPublicationV1]:
        harness.deadline = deadline_at
        return closure.execute(selection, deadline_at=deadline_at)

    def read(
        artifact_id: str, *, deadline_at: datetime
    ) -> FiscalOriginalValidationEvidenceV1:
        harness.deadline = deadline_at
        return closure.read(artifact_id, deadline_at=deadline_at)

    _install_acquisition(
        monkeypatch,
        SimpleNamespace(
            capture_store=harness.artifacts,
            settings=SimpleNamespace(
                supported_filing_years=request.supported_filing_years
            ),
            fiscal_discovery=harness.discovery,
            fiscal_source_closure=lambda **_kwargs: SimpleNamespace(
                execute=execute, read=read
            ),
        ),
    )

    def run(*args: str) -> str:
        exit_code = main(["--source-revision", request.declared_source_revision, *args])
        captured = capsys.readouterr()
        assert (exit_code, captured.err) == (0, "")
        return captured.out

    discovered = json.loads(
        run(
            "discover",
            "--cik",
            request.cik,
            "--valuation-timestamp",
            request.valuation_timestamp.isoformat(),
        )
    )
    discovery_id = f"fiscal-discovery:{request.digest}"
    discovery_record = harness.artifacts.get(discovery_id)
    assert discovered == {
        "evidence": json.loads(harness.artifacts.read(discovery_id)),
        "publication": {
            "artifact": discovery_record.model_dump(mode="json"),
            "wrote": True,
        },
    }
    accession = discovered["evidence"]["selection"]["selected"][0]["accession_number"]
    validated = json.loads(
        run(
            "validate",
            "--discovery-artifact-id",
            discovery_id,
            "--accession",
            accession,
        )
    )
    validation_id = validated["publication"]["artifact"]["artifact_id"]
    report_evidence = closure.read(validation_id, deadline_at=harness.deadline)
    assert isinstance(report_evidence.outcome, FiscalValidationMatchedV1)
    report = report_evidence.outcome.claim.report
    raw_source = report_evidence.outcome.claim.source
    assert harness.content.get(raw_source.content_hash, media_type="text/html") == (
        b"synthetic primary"
    )
    retained = json.loads(harness.artifacts.read(report_evidence.artifact_id))
    assert validated == {
        "evidence": retained,
        "publication": {
            "artifact": harness.artifacts.get(report_evidence.artifact_id).model_dump(
                mode="json"
            ),
            "wrote": True,
        },
    }
    json_report = validated["evidence"]["outcome"]["claim"]["report"]
    ruleset = report.validation_profile.dqc_ruleset_path
    assert isinstance(ruleset, Path)
    assert json_report["validation_profile"]["dqc_ruleset_path"] == str(ruleset)
    assert datetime.fromisoformat(json_report["parsed_at"]) == report.parsed_at
    assert json.loads(run("read", "--artifact-id", validation_id)) == {
        "evidence": retained
    }


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

        _install_acquisition(monkeypatch, acquisition)
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
