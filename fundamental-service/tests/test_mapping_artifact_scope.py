"""Mapping replay pins bounded source bytes inside one verifier operation."""

import json
from collections import Counter
from types import SimpleNamespace

import pytest

from fundamental_service.automatic_mapping import (
    AutomaticMappingDecisionV1,
    verify_automatic_mapping_replay,
)
from fundamental_service.automatic_mapping_evidence import (
    AutomaticMappingEvidenceChecks,
)
from fundamental_service.automatic_mapping_runner import approve_mapping
from fundamental_service.data_releases import (
    AutomaticMappingApprovalV1,
    DataReleaseError,
)
from fundamental_service.snapshots import SnapshotError
from test_automatic_mapping import MACHINE_KEY, case


def replay_case(tmp_path):
    request, store, roots, _ = case(tmp_path)
    requests = (request, request.model_copy(update={"source_revision": "b" * 40}))
    inputs = []
    for item in requests:
        receipt = approve_mapping(
            item, artifacts=store, trust_roots=roots, private_key=MACHINE_KEY
        )
        approval = AutomaticMappingApprovalV1.model_validate_json(
            store.read(receipt.approval_publication.artifact.artifact_id)
        )
        envelope = json.loads(
            store.read(receipt.input_publication.artifact.artifact_id)
        )
        decision = AutomaticMappingDecisionV1.model_validate_json(
            store.read(receipt.decision_publication.artifact.artifact_id)
        )
        inputs.append((approval, decision.mapping, item))
    return store, envelope["original_ref"]["artifact_id"], inputs


def tracking_reader(store):
    reads = Counter()

    def read(artifact_id):
        reads[artifact_id] += 1
        return store.read(artifact_id)

    return SimpleNamespace(get=store.get, read=read), reads


def test_distinct_mapping_replays_share_checked_bytes_but_new_operation_rereads(
    tmp_path,
):
    store, report_id, inputs = replay_case(tmp_path)
    reader, reads = tracking_reader(store)
    checks = AutomaticMappingEvidenceChecks()
    for approval, mapping, expected in inputs:
        assert (
            verify_automatic_mapping_replay(
                approval, mapping, artifacts=reader, evidence_checks=checks
            )
            == expected
        )
    assert reads[report_id] == 1
    assert all(count == 1 for count in reads.values())
    approval, mapping, expected = inputs[0]
    assert (
        verify_automatic_mapping_replay(
            approval,
            mapping,
            artifacts=reader,
            evidence_checks=AutomaticMappingEvidenceChecks(),
        )
        == expected
    )
    assert reads[report_id] == 2


def test_artifact_invalidation_is_observed_inside_a_successful_operation(tmp_path):
    store, report_id, inputs = replay_case(tmp_path)
    approval, mapping, expected = inputs[0]
    checks = AutomaticMappingEvidenceChecks()
    assert (
        verify_automatic_mapping_replay(
            approval, mapping, artifacts=store, evidence_checks=checks
        )
        == expected
    )
    store.invalidate(report_id)
    with pytest.raises(DataReleaseError, match="valid retained"):
        verify_automatic_mapping_replay(
            approval, mapping, artifacts=store, evidence_checks=checks
        )


def test_next_operation_rejects_corruption_after_prior_replay_succeeded(tmp_path):
    store, report_id, inputs = replay_case(tmp_path)
    approval, mapping, expected = inputs[0]
    assert (
        verify_automatic_mapping_replay(
            approval,
            mapping,
            artifacts=store,
            evidence_checks=AutomaticMappingEvidenceChecks(),
        )
        == expected
    )
    record = store.get(report_id)
    store._artifact_path(record.content_hash, record.media_type).write_bytes(b"corrupt")
    with pytest.raises(SnapshotError, match="failed verification"):
        verify_automatic_mapping_replay(
            approval,
            mapping,
            artifacts=store,
            evidence_checks=AutomaticMappingEvidenceChecks(),
        )


@pytest.mark.parametrize("limit", ("bytes", "entries", "disabled"))
def test_scoped_retention_limits_evict_and_oversized_bytes_still_validate(
    tmp_path, limit
):
    _, store, _, _ = case(tmp_path)
    ids = tuple(
        store.put_bytes_with_receipt(str(i), content).artifact.artifact_id
        for i, content in enumerate((b"1111", b"2222", b"3333", b"oversized"))
    )
    reader, reads = tracking_reader(store)
    checks = AutomaticMappingEvidenceChecks(
        max_retained_bytes=8 if limit != "entries" else 64,
        max_retained_artifacts=2 if limit != "disabled" else 0,
    )
    scoped = checks.reader(reader)
    for index in (0, 1, 0, 2, 1, 3, 3):
        assert scoped.read(ids[index]) == store.read(ids[index])
    assert reads[ids[0]] == (2 if limit == "disabled" else 1)
    assert reads[ids[1]] == 2
    assert reads[ids[3]] == (1 if limit == "entries" else 2)


def test_scope_refuses_metadata_changes_during_a_read(tmp_path):
    _, store, _, _ = case(tmp_path)
    publication = store.put_bytes_with_receipt("source", b"source bytes")
    record = publication.artifact
    reads = []

    def read(artifact_id):
        reads.append(artifact_id)
        return b"source bytes"

    def get(artifact_id):
        return record.model_copy(update={"status": "invalidated"}) if reads else record

    reader = SimpleNamespace(get=get, read=read)
    with pytest.raises(DataReleaseError) as error:
        AutomaticMappingEvidenceChecks().reader(reader).read(record.artifact_id)
    assert error.value.code == "MAPPING_SOURCE_ARTIFACT_CHANGED"


def test_unbound_bytes_are_never_retained_ahead_of_the_owning_validator(tmp_path):
    _, store, _, _ = case(tmp_path)
    publication = store.put_bytes_with_receipt("source", b"source bytes")
    calls = []

    def read(artifact_id):
        calls.append(artifact_id)
        return b"corrupt"

    scoped = AutomaticMappingEvidenceChecks().reader(
        SimpleNamespace(get=store.get, read=read)
    )
    for _ in range(2):
        assert scoped.read(publication.artifact.artifact_id) == b"corrupt"
    assert len(calls) == 2


def test_operation_cannot_silently_switch_artifact_stores(tmp_path):
    _, store, _, _ = case(tmp_path)
    reader, _ = tracking_reader(store)
    checks = AutomaticMappingEvidenceChecks()
    scoped = checks.reader(store)
    assert checks.reader(store) is scoped and checks.reader(scoped) is scoped
    with pytest.raises(ValueError, match="one artifact store"):
        checks.reader(reader)


@pytest.mark.parametrize("tamper", (False, True))
def test_issuer_integrity_checks_reference_bytes_independently_of_reader(
    tmp_path, tamper
):
    from fundamental_service.automatic_release_evidence import (
        require_automatic_release_sources,
    )
    from fundamental_service.data_releases import DataReleaseContentRequestV1
    from fundamental_service.replay import ArtifactRecordV1
    from test_issuer_operating_release import fixture as issuer_case

    bundle, _, evidence, _, _ = issuer_case(tmp_path)
    references = {ref.artifact_id: ref for ref in bundle.manifest.artifact_refs}
    integrity_id = next(
        ref.artifact_id
        for ref in references.values()
        if ref.role == "sec-issuer-integrity-v1"
    )

    def get(artifact_id):
        ref = references[artifact_id]
        return ArtifactRecordV1(
            artifact_id=artifact_id,
            content_hash=ref.content_hash,
            media_type=ref.media_type,
        )

    def read(artifact_id):
        raw = evidence.read(artifact_id)
        return raw + b" " if tamper and artifact_id == integrity_id else raw

    def validate():
        return require_automatic_release_sources(
            bundle.manifest,
            DataReleaseContentRequestV1(
                source_revision=bundle.verification.source_revision,
                evidence_refs=bundle.verification.evidence_refs,
            ),
            snapshots=SimpleNamespace(get=lambda _: bundle.sources[0]),
            mappings=SimpleNamespace(
                get_mapping=lambda _: pytest.fail("unused mapping")
            ),
            artifacts=SimpleNamespace(get=get, read=read),
            validation_profile_digest=bundle.sources[0]
            .originals[0]
            .report.validation_profile_digest,
        )

    if tamper:
        with pytest.raises(DataReleaseError) as error:
            validate()
        assert error.value.code == "AUTOMATIC_RELEASE_ORIGINAL_ARTIFACT_MISMATCH"
    else:
        assert len(validate()) == 1
