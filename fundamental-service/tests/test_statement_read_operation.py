import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from fundamental_service import statement_mapping_evidence, statement_releases
from fundamental_service import automatic_mapping_evidence
from fundamental_service.automatic_mapping_batch import (
    StatementMappingBatchDecisionV1,
    StatementMappingBatchRequestV1,
)
from fundamental_service.automatic_mapping_evidence import (
    AutomaticMappingEvidenceChecks,
)
from fundamental_service.data_releases import ArtifactRefV1, DataReleaseError
from fundamental_service.metadata import (
    PostgresArtifactStore,
    PostgresContentStore,
    PostgresMetadataStore,
)
from fundamental_service.mapping_input_storage import (
    mapping_input_report_dependency,
    read_mapping_batch_input,
    resolve_mapping_input,
)
from fundamental_service.original_issuer import (
    OriginalIssuerEvidenceChecks,
    OriginalIssuerEvidenceV1,
)
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import SnapshotError
from test_automatic_source_mapping import statement_source_case
from test_statement_releases import release_case


def mapping_case(path, monkeypatch):
    request, authority, validated, artifacts, _ = statement_source_case(
        path, monkeypatch
    )
    result = authority.resolver_for(request).resolve(validated)
    record = artifacts.get(result.evidence_ref)
    reference = ArtifactRefV1(
        artifact_id=record.artifact_id,
        content_hash=record.content_hash,
        media_type=record.media_type,
        role="statement-mapping-batch-decision-v1",
    )
    expected = StatementMappingBatchDecisionV1.model_validate_json(
        artifacts.read(record.artifact_id)
    )
    input_ref, batch_request = read_mapping_batch_input(
        expected.input_digest, StatementMappingBatchRequestV1, artifacts=artifacts
    )
    report_ref, _ = mapping_input_report_dependency(
        artifacts.read(input_ref.artifact_id)
    )
    references = (
        reference,
        input_ref,
        report_ref,
        *batch_request.evidence_refs,
        *(
            outcome.decision
            for role in expected.roles
            for outcome in role.proposal_decisions()
            if outcome.decision is not None
        ),
    )
    retained = ArtifactStore(path / "retained")
    for ref in references:
        record = artifacts.get(ref.artifact_id)
        retained.put_bytes_with_receipt(
            record.artifact_id,
            artifacts.read(record.artifact_id),
            media_type=record.media_type,
            dependency_hashes=record.dependency_hashes,
        )
    return (
        reference,
        retained,
        expected,
        dict(
            original=validated.original,
            source_revision=request.source_revision,
            profile=request.statement_profile,
            mapping_version=request.mapping_version,
        ),
    )


def copy_artifacts(source, destination):
    for record in source._records.values():
        destination.put_bytes_with_receipt(
            record.artifact_id,
            source.read(record.artifact_id),
            media_type=record.media_type,
            dependency_hashes=record.dependency_hashes,
        )


def membership(release, statement, value, options, *, artifacts=None, facts=None):
    return statement_releases.verify_statement_release_membership(
        release.manifest,
        statement,
        originals=value.service,
        content=value.acquisition.content_store,
        snapshots=options["snapshots"],
        facts=facts or options["facts"],
        mappings=options["mappings"],
        artifacts=artifacts or value.artifacts,
        source_revision=options["source_revision"],
    )


def test_membership_reuses_checked_originals_only_in_its_own_read(
    tmp_path, monkeypatch
):
    value, release, statement, options = release_case(tmp_path, monkeypatch)
    expected = membership(release, statement, value, options)
    prepared_reports = {}
    original_read = value.service.read_with_validations
    mapping_read = statement_mapping_evidence.read_mapping_batch_input
    original_validate = OriginalIssuerEvidenceV1.validate_original_evidence
    semantic_checks = []
    reused_reports = []

    def prepared(*args, **kwargs):
        result = original_read(*args, **kwargs)
        prepared_reports.update(
            (item.request.filing.accession_number, item.original.report)
            for item in result[1]
            if item.original is not None
        )
        return result

    def mapped(*args, **kwargs):
        result = mapping_read(*args, **kwargs)
        original = result[1].original
        assert original.report is prepared_reports[original.source.accession_number]
        reused_reports.append(original.report)
        return result

    def validated(original):
        semantic_checks.append(original.output_digest)
        return original_validate(original)

    monkeypatch.setattr(value.service, "read_with_validations", prepared)
    monkeypatch.setattr(statement_mapping_evidence, "read_mapping_batch_input", mapped)
    monkeypatch.setattr(
        OriginalIssuerEvidenceV1, "validate_original_evidence", validated
    )
    for operation in range(2):
        assert membership(release, statement, value, options) == expected
        assert len(semantic_checks) == operation + 1
    assert len(reused_reports) == 2
    assert reused_reports[0] is not reused_reports[1]
    assert statement.statements.tables[0].rows[0].cells[0].fact.value == 140


@pytest.mark.parametrize(
    "limits",
    (
        {"max_report_bytes": 0},
        {"max_report_bytes": 1},
        {"max_reports": 1},
        {"max_verified_entries": 0},
    ),
)
def test_preparation_and_mapping_preserve_decisions_when_original_checks_evict(
    tmp_path, monkeypatch, limits
):
    from test_automatic_mapping import case

    value, release, statement, options = release_case(tmp_path, monkeypatch)
    expected = membership(release, statement, value, options)
    monkeypatch.setattr(
        automatic_mapping_evidence,
        "OriginalIssuerEvidenceChecks",
        lambda: OriginalIssuerEvidenceChecks(**limits),
    )
    checks = AutomaticMappingEvidenceChecks()
    _, validations = value.service.read_with_validations(
        statement.original_preparation.artifact_id, original_checks=checks.originals
    )
    other, *_ = case(tmp_path / "other", observation_changes={"value": "150"})
    checks.originals.validate(other.original)
    reference = next(
        ref
        for ref in statement.projection.facts[0].mapping_evidence_refs
        if ref.role == "statement-mapping-batch-decision-v1"
    )
    actual = statement_mapping_evidence.verify_statement_mapping_outcomes(
        reference,
        original=validations[0].original,
        artifacts=value.artifacts,
        source_revision=options["source_revision"],
        profile=statement.projection.profile,
        mapping_version=statement.mapping_version,
        evidence_checks=checks,
    )
    assert actual == StatementMappingBatchDecisionV1.model_validate_json(
        value.artifacts.read(reference.artifact_id)
    )
    assert membership(release, statement, value, options) == expected


@pytest.mark.parametrize("mutation", ("output_digest", "decision_at"))
def test_prepared_report_does_not_authorize_changed_mapping_headers(
    tmp_path, monkeypatch, mutation
):
    value, _, statement, _ = release_case(tmp_path, monkeypatch)
    checks = AutomaticMappingEvidenceChecks()
    value.service.read_with_validations(
        statement.original_preparation.artifact_id, original_checks=checks.originals
    )
    batch_ref = next(
        ref
        for ref in statement.projection.facts[0].mapping_evidence_refs
        if ref.role == "statement-mapping-batch-decision-v1"
    )
    batch = StatementMappingBatchDecisionV1.model_validate_json(
        value.artifacts.read(batch_ref.artifact_id)
    )
    input_ref, request = read_mapping_batch_input(
        batch.input_digest,
        StatementMappingBatchRequestV1,
        artifacts=value.artifacts,
        original_checks=checks.originals,
        input_digests=checks.identities,
    )
    changed = json.loads(value.artifacts.read(input_ref.artifact_id))
    changed["original"][mutation] = (
        "0" * 64
        if mutation == "output_digest"
        else request.original.decision_at.replace(tzinfo=None).isoformat()
    )
    with pytest.raises(ValidationError):
        resolve_mapping_input(
            canonical_bytes(changed),
            StatementMappingBatchRequestV1,
            artifacts=value.artifacts,
            original_checks=checks.originals,
            input_digests=checks.identities,
        )
    assert (
        read_mapping_batch_input(
            batch.input_digest,
            StatementMappingBatchRequestV1,
            artifacts=value.artifacts,
            original_checks=checks.originals,
            input_digests=checks.identities,
        )[1]
        == request
    )


def test_mapping_rechecks_report_bytes_after_preparation_has_checked_them(
    tmp_path, monkeypatch
):
    value, _, statement, options = release_case(tmp_path, monkeypatch)
    checks = AutomaticMappingEvidenceChecks()
    _, validations = value.service.read_with_validations(
        statement.original_preparation.artifact_id, original_checks=checks.originals
    )
    reference = next(
        ref
        for ref in statement.projection.facts[0].mapping_evidence_refs
        if ref.role == "statement-mapping-batch-decision-v1"
    )
    batch = StatementMappingBatchDecisionV1.model_validate_json(
        value.artifacts.read(reference.artifact_id)
    )
    input_ref, _ = read_mapping_batch_input(
        batch.input_digest,
        StatementMappingBatchRequestV1,
        artifacts=value.artifacts,
    )
    report_ref, _ = mapping_input_report_dependency(
        value.artifacts.read(input_ref.artifact_id)
    )
    path = next(value.artifacts.root.glob(report_ref.content_hash + ".*.artifact"))
    path.write_bytes(b"corrupt retained report")
    with pytest.raises(SnapshotError) as error:
        statement_mapping_evidence.verify_statement_mapping_outcomes(
            reference,
            original=validations[0].original,
            artifacts=value.artifacts,
            source_revision=options["source_revision"],
            profile=statement.projection.profile,
            mapping_version=statement.mapping_version,
            evidence_checks=checks,
        )
    assert error.value.code == "ARTIFACT_HASH_MISMATCH"


@pytest.mark.parametrize(
    "limits",
    ({}, {"max_retained_bytes": 0}, {"max_retained_artifacts": 1}),
)
def test_distinct_reports_share_source_checks_without_reusing_mapping_decisions(
    tmp_path, monkeypatch, limits
):
    from test_automatic_mapping import case
    import test_automatic_source_mapping

    first = mapping_case(tmp_path / "first", monkeypatch)
    with monkeypatch.context() as changed:
        changed.setattr(
            test_automatic_source_mapping,
            "case",
            lambda path, **kwargs: case(
                path, **(kwargs | {"observation_changes": {"value": "150"}})
            ),
        )
        second = mapping_case(tmp_path / "second", changed)
    assert first[2] != second[2]
    artifacts = ArtifactStore(tmp_path / "combined")
    for _, source, _, _ in (first, second):
        copy_artifacts(source, artifacts)
    checks = AutomaticMappingEvidenceChecks(**limits)
    source_checks = []
    verify_bytes = automatic_mapping_evidence.verify_original_bytes

    def observed(*args, **kwargs):
        source_checks.append(True)
        return verify_bytes(*args, **kwargs)

    monkeypatch.setattr(automatic_mapping_evidence, "verify_original_bytes", observed)
    for reference, _, expected, arguments in (first, second, first):
        actual = statement_mapping_evidence.verify_statement_mapping_outcomes(
            reference, artifacts=artifacts, evidence_checks=checks, **arguments
        )
        assert actual == expected
        revenue = next(
            role for role in actual.roles if role.normalized_field == "revenue"
        )
        assert revenue.status == "approved"
    assert len(source_checks) == 2
    reference, _, expected, arguments = first
    assert (
        statement_mapping_evidence.verify_statement_mapping_outcomes(
            reference, artifacts=artifacts, **arguments
        )
        == expected
    )
    assert len(source_checks) == 3


@pytest.mark.parametrize("role", ("statement-mapping-batch-decision-v1", "source"))
def test_next_membership_rechecks_corrupt_retained_bytes(tmp_path, monkeypatch, role):
    value, release, statement, options = release_case(tmp_path, monkeypatch)
    expected = membership(release, statement, value, options)
    assert expected.snapshot_ids and expected.fact_digests
    reference = next(
        reference
        for reference in statement.projection.facts[0].mapping_evidence_refs
        if reference.role == "statement-mapping-batch-decision-v1"
    )
    if role == "source":
        source_hash = statement.projection.facts[0].source.content_hash
        reference = next(
            reference
            for reference in release.manifest.artifact_refs
            if reference.content_hash == source_hash
        )
    path = next(value.artifacts.root.glob(reference.content_hash + ".*.artifact"))
    path.write_bytes(b"corrupt retained source")
    with pytest.raises((SnapshotError, DataReleaseError)):
        membership(release, statement, value, options)


@pytest.mark.parametrize("fallback", (False, True))
@pytest.mark.parametrize("body_failure", (False, True))
def test_membership_rechecks_mapping_source_after_later_fact_reads(
    tmp_path, monkeypatch, recovery_databases, fallback, body_failure
):
    value, release, statement, options = release_case(tmp_path, monkeypatch)
    expected = membership(release, statement, value, options)
    metadata = PostgresMetadataStore(recovery_databases[0], auto_migrate=True)
    metadata.start()
    try:
        artifacts = PostgresArtifactStore(
            metadata, PostgresContentStore(tmp_path / "pg-content", metadata)
        )
        copy_artifacts(value.artifacts, artifacts)
        assert (
            membership(release, statement, value, options, artifacts=artifacts)
            == expected
        )
        if fallback:
            operation = artifacts.retained_read_operation

            @contextmanager
            def bounded(ids):
                with operation(ids, max_entries=1) as reader:
                    yield reader

            monkeypatch.setattr(artifacts, "retained_read_operation", bounded)
        batch_ref = next(
            ref
            for ref in statement.projection.facts[0].mapping_evidence_refs
            if ref.role == "statement-mapping-batch-decision-v1"
        )
        batch = StatementMappingBatchDecisionV1.model_validate_json(
            value.artifacts.read(batch_ref.artifact_id)
        )
        _, batch_request = read_mapping_batch_input(
            batch.input_digest,
            StatementMappingBatchRequestV1,
            artifacts=value.artifacts,
        )
        consumed = next(
            ref
            for ref in batch_request.evidence_refs
            if ref.content_hash == statement.projection.facts[0].source.content_hash
        )
        changed = False

        async def withdraw():
            async with metadata._runner._engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE fundamental.artifact_references SET status='invalidated' "
                        "WHERE artifact_id=:id"
                    ),
                    {"id": consumed.artifact_id},
                )

        def read_fact(identity):
            nonlocal changed
            if not changed:
                metadata._runner.run(withdraw())
                changed = True
            if body_failure:
                raise DataReleaseError(
                    "LATER_FACT_UNAVAILABLE", "later fact read failed"
                )
            return options["facts"].get(identity)

        with pytest.raises(DataReleaseError) as error:
            membership(
                release,
                statement,
                value,
                options,
                artifacts=artifacts,
                facts=SimpleNamespace(get=read_fact),
            )
        assert changed
        assert error.value.code == (
            "LATER_FACT_UNAVAILABLE" if body_failure else "ARTIFACT_EVIDENCE_CHANGED"
        )
    finally:
        metadata.close()
