from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from fundamental_service.data_releases import (
    REQUIRED_DATA_RELEASE_GATES,
    DataReleaseError,
    DataReleaseTrustRootsV1,
    DataReleaseVerificationV1,
    DataReleaseVerifierV1,
    MappingReviewEvidenceV1,
    sign_data_release_verification,
    sign_mapping_review_evidence,
    verify_data_release_verification,
    verify_mapping_review_evidence,
)

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


def _verification() -> DataReleaseVerificationV1:
    return sign_data_release_verification(
        {
            "manifest_digest": "b" * 64,
            "verification_suite_digest": "a" * 64,
            "source_revision": "c" * 40,
            "verification_run_id": "release-run-42",
            "workflow_identity": "github://value-investment-agent/release.yml",
            "verifier_id": "release-ci",
            "passed_gate_ids": tuple(sorted(REQUIRED_DATA_RELEASE_GATES)),
            "evidence_refs": (EVIDENCE,),
            "mapping_reviews": (_mapping_review(),),
        },
        RUNNER_KEY,
    )


def test_trusted_runner_and_independent_mapping_review_signatures_verify():
    roots = _trust_roots()
    verification = _verification()

    verify_data_release_verification(verification, roots)
    verify_mapping_review_evidence(verification.mapping_reviews[0], roots)


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
