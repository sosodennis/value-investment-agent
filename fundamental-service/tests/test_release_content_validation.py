"""Content checks run before signing and cannot authorize release publication."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from fundamental_service.data_releases import (
    DataReleaseCandidatePublishRequestV1,
    DataReleaseContentRequestV1,
    DataReleaseError,
    DataReleaseTrustRootsV1,
)
from fundamental_service.release_runner import DataReleaseCanaryRunner
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_conditional_capital_release import _conditional_fixture
from test_preparation_runner import _reviewed_candidate
from test_release_runner import _candidate, _history_candidate


def _request(verification):
    return DataReleaseContentRequestV1(
        source_revision=verification.source_revision,
        evidence_refs=verification.evidence_refs,
        mapping_reviews=verification.mapping_reviews,
    )


def _case(*, without_verifier=False):
    manifest, verification, snapshots, facts, mappings, artifacts, roots = _candidate()
    if without_verifier:
        roots = DataReleaseTrustRootsV1(
            verifiers={"another-verifier": roots.verifiers[verification.verifier_id]},
            mapping_reviewers=roots.mapping_reviewers,
        )
    runner = DataReleaseCanaryRunner(
        snapshot_repository=snapshots,
        fact_repository=facts,
        mapping_reader=mappings,
        artifact_reader=artifacts,
        trust_roots=roots,
    )
    return runner, manifest, verification, artifacts


def test_content_checks_replay_and_preserve_existing_signed_canary_bytes():
    runner, manifest, verification, _ = _case()
    request = _request(verification)
    first = runner.validate_content(manifest, request)
    assert canonical_bytes(first) == canonical_bytes(
        runner.validate_content(manifest, request)
    )
    assert first.request_digest == sha256_digest(request)
    assert first.candidate_manifest_digest == manifest.manifest_digest
    signed = runner.validate(manifest, verification)
    assert first.checked_fact_digests == signed.checked_fact_digests
    assert first.checked_artifact_digests == signed.checked_artifact_digests
    assert signed.canary_digest == (
        "7f02c9154f5bd771661cb36955608af07936d9d53942c47eaa6388374454e5d4"
    )
    assert (
        not {"signature", "passed_gate_ids", "verification"} & first.model_dump().keys()
    )
    with pytest.raises(ValidationError):
        DataReleaseCandidatePublishRequestV1.model_validate(
            {"manifest": manifest, "verification": first.model_dump()}
        )


def test_content_validation_does_not_invent_verifier_authority():
    runner, manifest, verification, _ = _case(without_verifier=True)
    assert runner.validate_content(
        manifest, _request(verification)
    ).checked_snapshot_ids
    with pytest.raises(DataReleaseError, match="verifier is not trusted"):
        runner.validate(manifest, verification)


@pytest.mark.parametrize("fault", ("missing", "duplicate", "signature", "untrusted"))
def test_unsigned_validation_still_requires_exact_trusted_mapping_approvals(fault):
    runner, manifest, verification, _ = _case()
    request = _request(verification)
    review = request.mapping_reviews[0]
    reviews = {
        "missing": (),
        "duplicate": (review, review),
        "signature": (review.model_copy(update={"signature": "0" * 128}),),
        "untrusted": (review.model_copy(update={"reviewer_id": "unknown"}),),
    }[fault]
    with pytest.raises(DataReleaseError) as caught:
        runner.validate_content(
            manifest, request.model_copy(update={"mapping_reviews": reviews})
        )
    assert (
        caught.value.code
        == {
            "missing": "DATA_RELEASE_MAPPING_REVIEW_MISMATCH",
            "duplicate": "DATA_RELEASE_MAPPING_REVIEW_DUPLICATE",
            "signature": "DATA_RELEASE_MAPPING_REVIEW_SIGNATURE_INVALID",
            "untrusted": "DATA_RELEASE_MAPPING_REVIEWER_UNTRUSTED",
        }[fault]
    )


def test_corrupt_content_refuses_before_a_report_can_be_signed():
    runner, manifest, verification, artifacts = _case()
    artifacts.content = b"corrupted"
    with pytest.raises(DataReleaseError) as caught:
        runner.validate_content(manifest, _request(verification))
    assert caught.value.code == "DATA_RELEASE_ARTIFACT_HASH_MISMATCH"


@pytest.mark.parametrize("fault", ("future", "conflict", "digest"))
def test_unsigned_history_validation_retains_existing_rejections(tmp_path, fault):
    transform = (
        (
            lambda fact, snapshot: fact.model_copy(
                update={
                    "available_at": snapshot.valuation_timestamp + timedelta(days=1)
                }
            )
        )
        if fault == "future"
        else None
    )
    runner, manifest, verification, _ = _history_candidate(
        tmp_path,
        transform=transform,
        conflicting=fault == "conflict",
        wrong_digest=fault == "digest",
    )
    with pytest.raises(DataReleaseError) as unsigned:
        runner.validate_content(manifest, _request(verification))
    with pytest.raises(DataReleaseError) as signed:
        runner.validate(manifest, verification)
    assert unsigned.value.code == signed.value.code


def test_conditional_source_quote_and_capital_use_same_content_gates(tmp_path):
    fixture = _conditional_fixture(tmp_path)
    candidate, runner = _reviewed_candidate(fixture)
    content = runner.validate_content(
        candidate.manifest, _request(candidate.verification)
    )
    signed = runner.validate(candidate.manifest, candidate.verification)
    assert content.checked_fact_digests == signed.checked_fact_digests
    assert content.checked_snapshot_ids == (fixture.snapshot.snapshot_id,)


def test_unsigned_request_rejects_injected_passed_gate_claims():
    _, _, verification, _ = _case()
    with pytest.raises(ValidationError):
        DataReleaseContentRequestV1.model_validate(
            _request(verification).model_dump()
            | {"passed_gate_ids": ("read-only-canary-v1",)}
        )
