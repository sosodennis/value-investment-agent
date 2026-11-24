"""The production statement operator uses source owners without an Agent run."""

from types import SimpleNamespace

import pytest

from fundamental_service.app import create_app
from fundamental_service.automatic_data_release import AutomaticDataReleaseService
from fundamental_service.dqc_rulesets import DQC_V18_PROFILE_ID
from fundamental_service.operations import OperationsConfig, ServiceError
from fundamental_service.statement_preparation import (
    AnnualStatementPreparationRequestV1,
    prepare_annual_statements,
    statement_validation_profile_id,
)
from fundamental_service.statement_preparation_runner import main
from fundamental_service.data_releases import DataReleaseError
from test_statement_releases import release_case
from test_issuer_operating_release import inventory


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
