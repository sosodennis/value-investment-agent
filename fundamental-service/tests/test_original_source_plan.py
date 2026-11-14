"""Saved originals compile into executable plans without new source authority."""

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from fundamental_service.automatic_mapping import automatic_mapping_policy_digest
from fundamental_service.arelle_parser import ArelleParserError
from fundamental_service.operations import ServiceError
from fundamental_service.original_source_plan import (
    AutomaticSourcePlanConfigurationV1,
    OriginalSourcePlan,
    OriginalSourcePlanRequestV1,
)
from fundamental_service.preparation_runner import (
    SOURCE_PREPARATION_PLAN,
    SourcePreparationEvidenceV1,
    SourcePreparationRunner,
)
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_source import SecSourceError
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import SnapshotError
from test_annual_discovery_service import _inventory
from test_automatic_source_preparation import run
from test_original_preparation import case, execute


def configuration(model_id="fcff_dcf"):
    return AutomaticSourcePlanConfigurationV1(
        model_id=model_id,
        release_profile_id="automatic-original-fcff",
        coverage_profile="automatic-fcff-v1",
        evaluator_id="machine-evaluator",
        mapping_version="automatic-source-v1",
        policy_version="source-preparation-v1",
    )


def test_configuration_rejects_models_without_an_automatic_source_policy():
    with pytest.raises(ValueError):
        configuration("bank_excess_return")


def compiler_case(value, prepared, config=None):
    compiler = OriginalSourcePlan(
        originals=value.service,
        artifacts=value.artifacts,
        compilation_lock=value.locks,
    )
    request = OriginalSourcePlanRequestV1(
        original_preparation=value.service.reference(
            prepared.artifact_id, "sec-original-preparation-v1"
        ),
        configuration=config or configuration(),
        runtime_source_revision=value.annual_request.declared_source_revision,
    )
    return compiler, request


@pytest.mark.parametrize(
    ("model_id", "model_version"),
    [("fcff_dcf", "fcff_dcf-v2"), ("transition_fcff_dcf", "transition_fcff_dcf-v2")],
)
def test_saved_original_supplies_identity_and_installed_model_pins(
    tmp_path, monkeypatch, model_id, model_version
):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    compiler, request = compiler_case(value, prepared, configuration(model_id))
    calls = value.state.provider_calls, value.state.parser_calls
    result, publication = compiler.execute(request)
    assert publication.wrote and not result.issue_codes
    plan = result.plan
    assert SOURCE_PREPARATION_PLAN.validate_json(canonical_bytes(plan)) == plan
    ingestion = plan.ingestions[0]
    validated = value.service.read_validation(
        prepared.filings[0].validation.artifact_id
    )
    assert ingestion.identity == prepared.filings[0].identity == value.expected_identity
    assert ingestion.ticker == value.expected_identity.security_id
    assert (
        ingestion.filing.accession_number == validated.request.filing.accession_number
    )
    assert ingestion.valuation_timestamp == validated.request.valuation_timestamp
    assert ingestion.model_id == model_id and ingestion.model_version == model_version
    assert ingestion.mapping_policy_digest == automatic_mapping_policy_digest()
    assert ingestion.requirements_digest == plan.requirements_profile.digest
    assert ingestion.required_fields == plan.requirements_profile.required_fact_fields
    assert (
        ingestion.fiscal_period_selector.count
        == plan.requirements_profile.history_window_years
    )
    assert (
        ingestion.taxonomy_manifest_id == prepared.request.runtime.taxonomy_manifest_id
    )
    assert plan.source_revision == request.runtime_source_revision
    assert plan.source_revision == value.annual_request.declared_source_revision
    assert plan.requirements_profile.supported_history_threshold is None
    assert value.artifacts.read(result.plan_ref.artifact_id) == canonical_bytes(plan)
    assert (
        value.metadata.snapshots
        == value.metadata.mappings
        == value.metadata.acquisitions
        == {}
    )
    assert calls == (value.state.provider_calls, value.state.parser_calls)


def test_repeat_reopened_and_concurrent_compilers_publish_once_without_io(
    tmp_path, monkeypatch
):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    compiler, request = compiler_case(value, prepared)

    def forbidden(*args, **kwargs):
        pytest.fail("compilation must not contact provider/parser")

    monkeypatch.setattr(value.acquisition.adapter, "_request", forbidden)
    monkeypatch.setattr(value.acquisition.ingestion, "validate_filing", forbidden)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: compiler.execute(request), range(3)))
    assert sum(publication.wrote for _, publication in results) == 1
    assert len({result.digest for result, _ in results}) == 1
    expected = results[0][0]
    before = _inventory(tmp_path)
    reopened = OriginalSourcePlan(
        originals=value.service,
        artifacts=ArtifactStore(value.artifacts.root),
        compilation_lock=value.locks,
    )
    assert reopened.read(expected.artifact_id) == expected
    again, publication = reopened.execute(request)
    assert again == expected and not publication.wrote
    assert _inventory(tmp_path) == before


@pytest.mark.parametrize("stage", ["configuration", "plan", "evidence"])
def test_interrupted_publication_resumes_without_rewriting_completed_artifacts(
    tmp_path, monkeypatch, stage
):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    compiler, request = compiler_case(value, prepared)
    delegate = value.artifacts.put_with_receipt
    prefix = {
        "configuration": "source-plan-configuration:",
        "plan": "source-preparation-plan:",
        "evidence": "original-source-plan:",
    }[stage]
    interrupted = False

    def put(artifact_id, *args, **kwargs):
        nonlocal interrupted
        if artifact_id.startswith(prefix) and not interrupted:
            interrupted = True
            raise OSError("simulated interruption")
        return delegate(artifact_id, *args, **kwargs)

    monkeypatch.setattr(value.artifacts, "put_with_receipt", put)
    with pytest.raises(OSError):
        compiler.execute(request)
    before = _inventory(tmp_path)
    calls = value.state.provider_calls, value.state.parser_calls
    result, publication = compiler.execute(request)
    assert publication.wrote and result.plan
    after = _inventory(tmp_path)
    for path, (payload, mtime) in before.items():
        if path.endswith(".artifact-records.jsonl"):
            assert after[path][0].startswith(payload)
        else:
            assert after[path] == (payload, mtime)
    assert calls == (value.state.provider_calls, value.state.parser_calls)
    assert not compiler.execute(request)[1].wrote


def test_missing_original_blocks_instead_of_using_only_successful_original(
    tmp_path, monkeypatch
):
    value = case(tmp_path, monkeypatch, multiple_originals=True)
    delegate = value.acquisition.adapter._request

    def capture(uri, *, deadline_at=None):
        if "/000000000126999999/" in uri:
            raise SecSourceError("SEC_HTTP_NOT_FOUND", "missing selected original")
        return delegate(uri, deadline_at=deadline_at)

    monkeypatch.setattr(value.acquisition.adapter, "_request", capture)
    prepared, _ = execute(value)
    assert len(prepared.filings) == 2
    compiler, request = compiler_case(value, prepared)
    result, _ = compiler.execute(request)
    assert result.plan is result.plan_ref is None
    assert "SEC_HTTP_NOT_FOUND" in result.issue_codes
    assert "ORIGINAL_SOURCE_PLAN_IDENTITY_MISSING" in result.issue_codes
    assert "ORIGINAL_HISTORY_IDENTITY_CONFLICT" not in result.issue_codes
    assert value.service.read(request.original_preparation.artifact_id) == prepared
    assert value.metadata.snapshots == value.metadata.mappings == {}
    before = _inventory(tmp_path)
    assert not compiler.execute(request)[1].wrote
    assert _inventory(tmp_path) == before


def test_retryable_original_attempt_does_not_reserve_a_successful_plan_identity(
    tmp_path, monkeypatch
):
    from fundamental_service import ingestion

    value = case(tmp_path, monkeypatch)
    delegate = ingestion.parse_filing_offline
    exhausted = True

    def parse(*args, **kwargs):
        nonlocal exhausted
        if exhausted:
            exhausted = False
            raise ArelleParserError("PARSER_RESOURCE_EXHAUSTED", "temporary failure")
        return delegate(*args, **kwargs)

    monkeypatch.setattr(ingestion, "parse_filing_offline", parse)
    attempt, _ = execute(value)
    compiler, request = compiler_case(value, attempt)
    refused, publication = compiler.execute(request)
    assert publication.wrote and refused.retryable and refused.plan is None
    assert refused.artifact_id.startswith("original-source-plan-attempt:")
    assert "PARSER_RESOURCE_EXHAUSTED" in refused.issue_codes
    before = _inventory(tmp_path)
    assert not compiler.execute(request)[1].wrote
    assert _inventory(tmp_path) == before

    prepared, _ = execute(value)
    compiler, successful_request = compiler_case(value, prepared)
    success, publication = compiler.execute(successful_request)
    assert publication.wrote and success.plan and not success.retryable
    assert successful_request.digest != request.digest
    assert compiler.read(refused.artifact_id) == refused
    assert not compiler.execute(successful_request)[1].wrote


def test_identity_refusal_is_retained_and_new_configuration_has_new_identity(
    tmp_path, monkeypatch
):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value, value.request.model_copy(update={"ticker": "OTHER"}))
    compiler, request = compiler_case(value, prepared)
    result, _ = compiler.execute(request)
    assert result.plan is None and "HISTORICAL_IDENTITY_MISMATCH" in result.issue_codes
    changed = request.model_copy(
        update={
            "configuration": request.configuration.model_copy(
                update={"mapping_version": "next-version"}
            )
        }
    )
    again, publication = compiler.execute(changed)
    assert publication.wrote and again.artifact_id != result.artifact_id
    assert again.issue_codes == result.issue_codes


@pytest.mark.parametrize(
    "target", ["evidence", "request", "configuration", "plan", "original"]
)
def test_corrupt_dependency_refuses_without_repair_io(tmp_path, monkeypatch, target):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    compiler, request = compiler_case(value, prepared)
    result, _ = compiler.execute(request)
    artifact_id = {
        "evidence": result.artifact_id,
        "request": f"original-source-plan-request:{request.digest}",
        "configuration": f"source-plan-configuration:{request.configuration.digest}",
        "plan": result.plan_ref.artifact_id,
        "original": prepared.artifact_id,
    }[target]
    delegate = value.artifacts.read
    monkeypatch.setattr(
        value.artifacts,
        "read",
        lambda key: b"{}" if key == artifact_id else delegate(key),
    )
    calls = value.state.provider_calls, value.state.parser_calls
    with pytest.raises(SnapshotError):
        compiler.execute(request)
    assert calls == (value.state.provider_calls, value.state.parser_calls)


def test_compiled_plan_runs_existing_automatic_preparation_and_retains_missing_roles(
    tmp_path, monkeypatch
):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    # Match the fixture's configured trust identity; compilation itself grants none.
    source = value.acquisition.automatic_mapping_authority
    config = configuration().model_copy(
        update={
            "evaluator_id": next(iter(source.trust_roots.automatic_mapping_evaluators))
        }
    )
    compiler, request = compiler_case(value, prepared, config)
    result, _ = compiler.execute(request)

    def missing(_):
        raise ServiceError(
            "SNAPSHOT_NOT_FOUND", "empty store", status_code=404, retryable=False
        )

    def forbidden(*args, **kwargs):
        pytest.fail("incomplete real inputs must not release, compose or calculate")

    runner = SourcePreparationRunner(
        application=SimpleNamespace(
            resolve_snapshot=missing,
            artifact_store=value.artifacts,
            snapshot=value.metadata.snapshots.__getitem__,
            prepare_valuation=forbidden,
            calculate_valuation=forbidden,
        ),
        metadata=value.metadata,
        acquisition=value.acquisition,
        artifacts=value.artifacts,
        canary=SimpleNamespace(validate=forbidden),
    )
    publication = run(runner, result.plan)
    evidence = SourcePreparationEvidenceV1.model_validate_json(
        value.artifacts.read(publication.artifact.artifact_id)
    )
    assert evidence.status == "blocked"
    assert evidence.source_outcomes[0].mapping_evidence_ref
    assert evidence.source_plan_ref == result.plan_ref
    assert value.metadata.mappings
    before = _inventory(tmp_path)
    assert not run(runner, result.plan).wrote
    assert _inventory(tmp_path) == before


def test_cli_compiles_and_retrieves_saved_plan_and_checks_configuration_before_storage(
    tmp_path, monkeypatch, capsys
):
    from fundamental_service import annual_discovery_runner, app

    value = case(tmp_path, monkeypatch)

    @asynccontextmanager
    async def lifespan(_):
        yield

    monkeypatch.setattr(
        app,
        "app",
        SimpleNamespace(
            router=SimpleNamespace(lifespan_context=lifespan),
            state=SimpleNamespace(
                application=SimpleNamespace(
                    ready=True,
                    content_store=value.acquisition.content_store,
                    artifact_store=value.artifacts,
                ),
                sec_acquisition=value.acquisition,
                metadata_store=value.metadata,
            ),
        ),
    )
    monkeypatch.setattr(
        annual_discovery_runner, "PostgresPublicCaptureLock", lambda _: value.locks
    )
    config = configuration()
    config_path = tmp_path / "configuration.json"
    config_path.write_bytes(canonical_bytes(config))
    args = [
        "--cik",
        value.annual_request.cik,
        "--valuation-timestamp",
        value.annual_request.valuation_timestamp.isoformat(),
        "--source-revision",
        value.annual_request.declared_source_revision,
        "--original-count",
        "1",
        "--prepare-originals",
        "--source-plan-configuration",
        str(config_path),
        "--configuration-digest",
        config.digest,
    ]
    assert annual_discovery_runner.main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["wrote"] and first["plan_ref"]
    assert (
        first["evidence"]["plan"]["ingestions"][0]["identity"]["security_id"]
        == value.expected_identity.security_id
    )
    before = _inventory(tmp_path)
    assert annual_discovery_runner.main(args) == 0
    repeated = json.loads(capsys.readouterr().out)
    assert repeated == {
        **first,
        "wrote": False,
        "lineage": {
            stage: {**value, "wrote": False}
            for stage, value in first["lineage"].items()
        },
    }
    assert (
        annual_discovery_runner.main(
            ["--artifact-id", first["artifact"]["artifact_id"]]
        )
        == 0
    )
    retrieved = json.loads(capsys.readouterr().out)
    assert all(
        retrieved[field] == repeated[field]
        for field in ("input_digest", "output_digest", "evidence", "plan_ref")
    )
    assert retrieved["wrote"] is False
    assert _inventory(tmp_path) == before

    source_preparation_id = first["evidence"]["request"]["original_preparation"][
        "artifact_id"
    ]
    installed_revision = "e" * 40
    monkeypatch.setattr(
        value.acquisition.adapter,
        "_request",
        lambda *args, **kwargs: pytest.fail("saved plan compilation used SEC I/O"),
    )
    saved_plan_args = [
        "--artifact-id",
        source_preparation_id,
        "--source-revision",
        installed_revision,
        "--source-plan-configuration",
        str(config_path),
        "--configuration-digest",
        config.digest,
    ]
    assert annual_discovery_runner.main(saved_plan_args) == 0
    compiled_saved = json.loads(capsys.readouterr().out)
    assert compiled_saved["wrote"] and compiled_saved["plan_ref"]
    assert compiled_saved["evidence"]["plan"]["source_revision"] == installed_revision
    after_first_saved_compile = _inventory(tmp_path)
    assert annual_discovery_runner.main(saved_plan_args) == 0
    repeated_saved = json.loads(capsys.readouterr().out)
    assert repeated_saved == {
        **compiled_saved,
        "wrote": False,
        "lineage": {
            stage: {**value, "wrote": False}
            for stage, value in compiled_saved["lineage"].items()
        },
    }
    assert _inventory(tmp_path) == after_first_saved_compile

    def forbidden(_):
        pytest.fail("invalid configuration opened service storage")

    monkeypatch.setattr(annual_discovery_runner, "_run_command", forbidden)
    assert annual_discovery_runner.main(args[:-1] + ["0" * 64]) == 2
    assert "ANNUAL_DISCOVERY_INPUT_INVALID" in capsys.readouterr().err
