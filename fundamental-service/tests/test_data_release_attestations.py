from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from fundamental_service.data_releases import (
    REQUIRED_DATA_RELEASE_GATES,
    DataReleaseError,
    DataReleaseManifestV1,
    DataReleaseTrustRootsV1,
    DataReleaseVerificationV1,
    DataReleaseVerifierV1,
    MappingReviewEvidenceV1,
    sign_data_release_verification,
    sign_mapping_review_evidence,
    verify_data_release_verification,
    verify_data_release_candidate,
    verify_mapping_review_evidence,
)
from fundamental_service.serialization import sha256_digest

RUNNER_KEY = Ed25519PrivateKey.from_private_bytes(b"r" * 32)
REVIEWER_KEY = Ed25519PrivateKey.from_private_bytes(b"v" * 32)
EVIDENCE = {
    "artifact_id": "mapping-fixture-evidence",
    "content_hash": "d" * 64,
    "media_type": "application/json",
    "role": "mapping-review",
}


def _trust_roots() -> DataReleaseTrustRootsV1:
    return DataReleaseTrustRootsV1(
        verifiers={
            "release-ci": DataReleaseVerifierV1(
                workflow_identity="github://value-investment-agent/release.yml",
                public_key_ed25519_base64=base64.b64encode(
                    RUNNER_KEY.public_key().public_bytes_raw()
                ).decode("ascii"),
                verification_suite_digest="a" * 64,
            )
        },
        mapping_reviewers={
            "reviewer-1": base64.b64encode(
                REVIEWER_KEY.public_key().public_bytes_raw()
            ).decode("ascii")
        },
    )


def _mapping_review() -> MappingReviewEvidenceV1:
    return sign_mapping_review_evidence(
        {
            "mapping_id": "mapping-revenue-extension-v1",
            "mapping_digest": "b" * 64,
            "author_id": "analyst-1",
            "reviewer_id": "reviewer-1",
            "reviewed_at": datetime(2026, 10, 1, tzinfo=UTC),
            "evidence_refs": (EVIDENCE,),
            "fixture_digest": "c" * 64,
        },
        REVIEWER_KEY,
    )


def _manifest() -> DataReleaseManifestV1:
    fact_refs = ({"fact_id": "fact-1", "fact_digest": "d" * 64},)
    payload = {
        "profile_id": "sec-public-pit",
        "release_id": "release-1",
        "created_at": datetime(2026, 10, 1, tzinfo=UTC),
        "snapshot_refs": (
            {
                "snapshot_id": "snapshot-1",
                "manifest_digest": "e" * 64,
                "facts": fact_refs,
                "fact_set_digest": sha256_digest(fact_refs),
            },
        ),
        "mapping_refs": (
            {
                "mapping_id": "mapping-revenue-extension-v1",
                "mapping_digest": "b" * 64,
            },
        ),
        "taxonomy_refs": (
            {
                "artifact_id": "taxonomy-1",
                "content_hash": "c" * 64,
                "media_type": "application/zip",
                "role": "taxonomy",
            },
        ),
        "parser_version": "arelle-release==2.47.4",
        "quality_profile_digest": "d" * 64,
        "required_fields": ("revenue",),
        "artifact_refs": (EVIDENCE,),
    }
    return DataReleaseManifestV1(**payload, manifest_digest=sha256_digest(payload))


def _verification(
    manifest_digest: str = "b" * 64,
    mapping_reviews: tuple[MappingReviewEvidenceV1, ...] | None = None,
) -> DataReleaseVerificationV1:
    return sign_data_release_verification(
        {
            "manifest_digest": manifest_digest,
            "verification_suite_digest": "a" * 64,
            "source_revision": "c" * 40,
            "verification_run_id": "release-run-42",
            "workflow_identity": "github://value-investment-agent/release.yml",
            "verifier_id": "release-ci",
            "passed_gate_ids": tuple(sorted(REQUIRED_DATA_RELEASE_GATES)),
            "evidence_refs": (EVIDENCE,),
            "mapping_reviews": (
                (_mapping_review(),) if mapping_reviews is None else mapping_reviews
            ),
        },
        RUNNER_KEY,
    )


def test_trusted_runner_and_independent_mapping_review_signatures_verify():
    roots = _trust_roots()
    verification = _verification()

    verify_data_release_verification(verification, roots)
    verify_mapping_review_evidence(verification.mapping_reviews[0], roots)


def test_candidate_requires_signed_review_for_each_matching_mapping():
    manifest = _manifest()
    roots = _trust_roots()
    verification = _verification(manifest.manifest_digest)

    verify_data_release_candidate(manifest, verification, roots)

    with pytest.raises(DataReleaseError) as missing_review:
        verify_data_release_candidate(
            manifest, _verification(manifest.manifest_digest, ()), roots
        )
    assert missing_review.value.code == "DATA_RELEASE_MAPPING_REVIEW_MISMATCH"

    mismatched_review = sign_mapping_review_evidence(
        {
            **_mapping_review().model_dump(mode="python", exclude={"signature"}),
            "mapping_digest": "e" * 64,
        },
        REVIEWER_KEY,
    )
    with pytest.raises(DataReleaseError) as mismatched:
        verify_data_release_candidate(
            manifest,
            _verification(manifest.manifest_digest, (mismatched_review,)),
            roots,
        )
    assert mismatched.value.code == "DATA_RELEASE_MAPPING_REVIEW_MISMATCH"

    with pytest.raises(DataReleaseError) as duplicate:
        verify_data_release_candidate(
            manifest,
            _verification(
                manifest.manifest_digest,
                (_mapping_review(), _mapping_review()),
            ),
            roots,
        )
    assert duplicate.value.code == "DATA_RELEASE_MAPPING_REVIEW_DUPLICATE"


def test_verification_signature_binds_manifest_and_required_gate_set():
    verification = _verification()
    altered = verification.model_copy(update={"manifest_digest": "e" * 64})

    with pytest.raises(DataReleaseError) as invalid:
        verify_data_release_verification(altered, _trust_roots())
    assert invalid.value.code == "DATA_RELEASE_VERIFICATION_SIGNATURE_INVALID"

    with pytest.raises(ValidationError):
        sign_data_release_verification(
            {
                "manifest_digest": "b" * 64,
                "verification_suite_digest": "a" * 64,
                "source_revision": "c" * 40,
                "verification_run_id": "release-run-43",
                "workflow_identity": "github://value-investment-agent/release.yml",
                "verifier_id": "release-ci",
                "passed_gate_ids": ("offline-replay-v1",),
                "evidence_refs": (EVIDENCE,),
                "mapping_reviews": (),
            },
            RUNNER_KEY,
        )


def test_mapping_review_signature_binds_reviewer_and_fixture_evidence():
    review = _mapping_review()
    altered = review.model_copy(update={"fixture_digest": "e" * 64})

    with pytest.raises(DataReleaseError) as invalid:
        verify_mapping_review_evidence(altered, _trust_roots())
    assert invalid.value.code == "DATA_RELEASE_MAPPING_REVIEW_SIGNATURE_INVALID"

    with pytest.raises(ValidationError, match="cannot review their own mapping"):
        sign_mapping_review_evidence(
            {
                "mapping_id": "mapping-revenue-extension-v1",
                "mapping_digest": "b" * 64,
                "author_id": "reviewer-1",
                "reviewer_id": "reviewer-1",
                "reviewed_at": datetime(2026, 10, 1, tzinfo=UTC),
                "evidence_refs": (EVIDENCE,),
                "fixture_digest": "c" * 64,
            },
            REVIEWER_KEY,
        )
