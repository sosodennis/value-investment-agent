from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fundamental_service.app import create_app
from fundamental_service.automatic_data_release import AutomaticDataReleaseService
from fundamental_service.data_releases import DataReleaseError
from fundamental_service.dqc_rulesets import DQC_V18_PROFILE_ID
from fundamental_service.operations import OperationsConfig, ServiceError
from fundamental_service.statement_preparation import (
    AnnualStatementPreparationRequestV1,
    prepare_annual_statements,
    statement_validation_profile_id,
)
from fundamental_service.statement_preparation_runner import main
from test_issuer_operating_release import inventory
from test_statement_releases import release_case


def operator_case(tmp_path, monkeypatch):
    value, release, _, options = release_case(tmp_path, monkeypatch)
    original = value.service.read_validation(
        value.service.read(
            next(
                ref.artifact_id
                for ref in release.manifest.artifact_refs
                if ref.role == "sec-original-preparation-v1"
            )
        )
        .filings[0]
        .validation.artifact_id
    ).original
    runtime = value.request.runtime
    monkeypatch.setattr(
        value.acquisition, "original_validation_runtime", lambda **kwargs: runtime
    )
    monkeypatch.setattr(
        "fundamental_service.statement_preparation.statement_validation_profile_id",
        lambda *_: runtime.validation_profile_id,
    )
    manifests, verifications = {}, {}
    metadata = SimpleNamespace(
        get_data_release_manifest=lambda digest: manifests.get(digest),
        get_data_release_verification=lambda digest: verifications.get(digest),
        get_mapping=options["mappings"].get_mapping,
        publish_data_release_candidate=lambda manifest, verification: (
            manifests.setdefault(manifest.manifest_digest, manifest),
            verifications.setdefault(manifest.manifest_digest, verification),
        ),
    )
    app = create_app(
        snapshot_repository=options["snapshots"],
        fact_repository=options["facts"],
        artifact_store=value.artifacts,
        content_store=value.acquisition.content_store,
        metadata_store=metadata,
        statement_originals=value.service,
        config=OperationsConfig(
            release_publish_authorized_organizations=frozenset({"org"})
        ),
    )
    application = app.state.application
    request = AnnualStatementPreparationRequestV1(
        cik=original.source.cik,
        cutoff_at=original.decision_at,
        source_revision=release.content.source_revision,
        original_count=1,
        mapping_evaluator_id=next(
            iter(
                value.acquisition._automatic_authority().trust_roots.automatic_mapping_evaluators
            )
        ),
        mapping_version="automatic-source-v1",
    )
    return value, request, application, AutomaticDataReleaseService(**options)


def test_operator_reads_and_replays_statement_without_valuation_or_market_step(
    tmp_path, monkeypatch
):
    value, request, application, release_service = operator_case(tmp_path, monkeypatch)
    result = prepare_annual_statements(
        request,
        application=application,
        acquisition=value.acquisition,
        discovery=value.discovery,
        automatic_release=release_service,
        actor_id="operator",
        organization_id="org",
        deadline_at=value.deadline,
    )
    assert result.response.statements.valuation_eligibility == "not_evaluated"
    assert not result.activated
    assert all(len(table.columns) == 1 for table in result.response.statements.tables)
    before = inventory(value.artifacts.root)
    calls = value.state.provider_calls, value.state.parser_calls
    repeated = prepare_annual_statements(
        request,
        application=application,
        acquisition=value.acquisition,
        discovery=value.discovery,
        automatic_release=release_service,
        actor_id="operator",
        organization_id="org",
        deadline_at=value.deadline,
    )
    assert repeated == result
    assert inventory(value.artifacts.root) == before
    assert (value.state.provider_calls, value.state.parser_calls) == calls


def test_operator_rejects_unapproved_organization_before_source_work(
    tmp_path, monkeypatch
):
    value, request, application, release_service = operator_case(tmp_path, monkeypatch)
    before = inventory(value.artifacts.root)
    with pytest.raises(ServiceError) as error:
        prepare_annual_statements(
            request,
            application=application,
            acquisition=value.acquisition,
            discovery=value.discovery,
            automatic_release=release_service,
            actor_id="operator",
            organization_id="other",
            deadline_at=value.deadline,
        )
    assert error.value.code == "DATA_RELEASE_FORBIDDEN"
    assert inventory(value.artifacts.root) == before


def test_operator_rejects_publish_only_organization_before_sec_source_work(
    tmp_path, monkeypatch
):
    value, request, application, release_service = operator_case(tmp_path, monkeypatch)
    value.acquisition.authorized_organizations = frozenset()
    before = inventory(value.artifacts.root)
    calls = value.state.provider_calls, value.state.parser_calls

    def unauthorized_source_work(*args, **kwargs):
        pytest.fail("SEC source work started for an unauthorized organization")

    monkeypatch.setattr(value.discovery, "execute", unauthorized_source_work)
    monkeypatch.setattr(value.service, "execute", unauthorized_source_work)
    with pytest.raises(ServiceError) as error:
        prepare_annual_statements(
            request,
            application=application,
            acquisition=value.acquisition,
            discovery=value.discovery,
            automatic_release=release_service,
            actor_id="operator",
            organization_id="org",
            deadline_at=value.deadline,
        )
    assert error.value.code == "INGESTION_NOT_AUTHORIZED"
    assert inventory(value.artifacts.root) == before
    assert (value.state.provider_calls, value.state.parser_calls) == calls


@pytest.mark.parametrize(
    "namespace,expected",
    [
        ("http://fasb.org/us-gaap/2020-01-31", DQC_V18_PROFILE_ID),
        ("http://fasb.org/us-gaap/2024", "sec-efm-us-dqc-v31.0.3"),
    ],
)
def test_runtime_profile_selection_uses_exact_namespace_not_filing_year(
    namespace, expected
):
    acquisition = SimpleNamespace(
        settings=SimpleNamespace(
            dqc_v18_ruleset_catalog=SimpleNamespace(
                bindings=(
                    SimpleNamespace(
                        taxonomy_namespace="http://fasb.org/us-gaap/2020-01-31"
                    ),
                )
            ),
            dqc_ruleset_catalog=SimpleNamespace(
                bindings=(
                    SimpleNamespace(taxonomy_namespace="http://fasb.org/us-gaap/2024"),
                )
            ),
        )
    )
    assert statement_validation_profile_id(acquisition, namespace) == expected
    with pytest.raises(DataReleaseError) as error:
        statement_validation_profile_id(acquisition, "https://example.com/us-gaap/2024")
    assert error.value.code == "STATEMENT_VALIDATION_NAMESPACE_UNAVAILABLE"


def test_cli_help_and_missing_options_do_not_load_runtime(capsys):
    with pytest.raises(SystemExit) as error:
        main(["--help"])
    assert error.value.code == 0 and "--print-runtime-pins" in capsys.readouterr().out
    with pytest.raises(SystemExit) as error:
        main(["--source-revision", "a" * 40])
    assert error.value.code == 2 and "--release-policy" in capsys.readouterr().err


@pytest.mark.parametrize(
    "cutoff", ["2024-11-02T00:00:00Z", "2024-11-02T08:00:00+08:00"]
)
def test_cli_passes_aware_cutoff_to_strict_preparation_contract(
    monkeypatch, capsys, cutoff
):
    async def run(args):
        request = AnnualStatementPreparationRequestV1(
            cik=args.cik,
            cutoff_at=args.cutoff_at,
            source_revision=args.source_revision,
            mapping_evaluator_id=args.mapping_evaluator_id,
            mapping_version=args.mapping_version,
        )
        assert request.cutoff_at == datetime(2024, 11, 2, tzinfo=UTC)
        return {"cutoff_at": request.cutoff_at}

    monkeypatch.setattr("fundamental_service.statement_preparation_runner._run", run)
    assert main(_cli_options(cutoff)) == 0
    assert "cutoff_at" in capsys.readouterr().out


@pytest.mark.parametrize("cutoff", ["2024-11-02T00:00:00", "not-a-date"])
def test_cli_rejects_invalid_cutoff_before_loading_runtime(monkeypatch, capsys, cutoff):
    async def run(args):
        pytest.fail("invalid cutoff must be rejected before runtime composition")

    monkeypatch.setattr("fundamental_service.statement_preparation_runner._run", run)
    with pytest.raises(SystemExit) as error:
        main(_cli_options(cutoff))
    assert error.value.code == 2
    assert "--cutoff-at" in capsys.readouterr().err


def _cli_options(cutoff):
    return [
        "--source-revision",
        "a" * 40,
        "--cik",
        "0000320193",
        "--cutoff-at",
        cutoff,
        "--mapping-evaluator-id",
        "mapper",
        "--mapping-version",
        "annual-statements-v1",
        "--mapping-private-key",
        "/keys/mapping.pem",
        "--release-policy",
        "/config/policy.json",
        "--release-private-key",
        "/keys/release.pem",
        "--actor",
        "operator",
        "--organization",
        "org",
    ]
