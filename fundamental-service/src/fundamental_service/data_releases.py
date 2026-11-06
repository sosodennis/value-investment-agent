"""Typed contracts for immutable Fundamental data releases."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .serialization import canonical_bytes, sha256_digest

DATA_RELEASE_CAPABILITY = "data-release-activation-v1"
REQUIRED_DATA_RELEASE_GATES = frozenset(
    {
        "manifest-integrity-v1",
        "snapshot-fact-membership-v1",
        "mapping-review-v1",
        "taxonomy-parser-compatibility-v1",
        "quality-policy-v1",
        "offline-replay-v1",
        "regulatory-validation-v1",
        "read-only-canary-v1",
    }
)


class DataReleaseError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class ReleaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class FactRefV1(ReleaseModel):
    fact_id: str = Field(min_length=1)
    fact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class SnapshotRefV1(ReleaseModel):
    snapshot_id: str = Field(min_length=1)
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    facts: tuple[FactRefV1, ...] = Field(min_length=1)
    fact_set_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def fact_set_matches(self) -> SnapshotRefV1:
        if sha256_digest(self.facts) != self.fact_set_digest:
            raise ValueError("fact_set_digest does not match the declared facts")
        if len({fact.fact_id for fact in self.facts}) != len(self.facts):
            raise ValueError("snapshot fact references must be unique")
        return self


class MappingRefV1(ReleaseModel):
    mapping_id: str = Field(min_length=1)
    mapping_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ArtifactRefV1(ReleaseModel):
    artifact_id: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str = Field(min_length=1)
    role: str = Field(min_length=1)


class DataReleaseManifestV1(ReleaseModel):
    profile_id: str = Field(min_length=1)
    release_id: str = Field(min_length=1)
    created_at: datetime
    snapshot_refs: tuple[SnapshotRefV1, ...] = Field(min_length=1)
    mapping_refs: tuple[MappingRefV1, ...] = Field(min_length=1)
    taxonomy_refs: tuple[ArtifactRefV1, ...] = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    quality_profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    required_fields: tuple[str, ...] = Field(min_length=1)
    artifact_refs: tuple[ArtifactRefV1, ...] = Field(min_length=1)
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("created_at")
    @classmethod
    def created_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value

    @model_validator(mode="after")
    def manifest_digest_matches(self) -> DataReleaseManifestV1:
        if len({snapshot.snapshot_id for snapshot in self.snapshot_refs}) != len(
            self.snapshot_refs
        ):
            raise ValueError("snapshot references must be unique")
        if len({mapping.mapping_id for mapping in self.mapping_refs}) != len(
            self.mapping_refs
        ):
            raise ValueError("mapping references must be unique")
        if len(set(self.required_fields)) != len(self.required_fields):
            raise ValueError("required fields must be unique")
        payload = self.model_dump(mode="python", exclude={"manifest_digest"})
        if sha256_digest(payload) != self.manifest_digest:
            raise ValueError("manifest_digest does not match the release manifest")
        return self


class MappingReviewEvidenceV1(ReleaseModel):
    mapping_id: str = Field(min_length=1)
    mapping_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    author_id: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)
    reviewed_at: datetime
    evidence_refs: tuple[ArtifactRefV1, ...] = Field(min_length=1)
    fixture_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")

    @model_validator(mode="after")
    def review_is_independent(self) -> MappingReviewEvidenceV1:
        if self.author_id == self.reviewer_id:
            raise ValueError("mapping author cannot review their own mapping")
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must include a timezone")
        return self

    def signing_bytes(self) -> bytes:
        return canonical_bytes(self.model_dump(mode="python", exclude={"signature"}))


class DataReleaseVerificationV1(ReleaseModel):
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    verification_suite_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    verification_run_id: str = Field(min_length=1)
    workflow_identity: str = Field(min_length=1)
    verifier_id: str = Field(min_length=1)
    passed_gate_ids: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[ArtifactRefV1, ...] = Field(min_length=1)
    mapping_reviews: tuple[MappingReviewEvidenceV1, ...] = ()
    verification_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")

    @model_validator(mode="after")
    def verification_digest_matches(self) -> DataReleaseVerificationV1:
        if (
            set(self.passed_gate_ids) != REQUIRED_DATA_RELEASE_GATES
            or tuple(sorted(self.passed_gate_ids)) != self.passed_gate_ids
        ):
            raise ValueError(
                "verification must pass the complete ordered release gate set"
            )
        payload = self.model_dump(
            mode="python", exclude={"verification_digest", "signature"}
        )
        if sha256_digest(payload) != self.verification_digest:
            raise ValueError("verification_digest does not match its evidence")
        return self

    def signing_bytes(self) -> bytes:
        return canonical_bytes(self.model_dump(mode="python", exclude={"signature"}))


class DataReleaseVerifierV1(ReleaseModel):
    workflow_identity: str = Field(min_length=1)
    public_key_ed25519_base64: str = Field(min_length=1)
    verification_suite_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("public_key_ed25519_base64")
    @classmethod
    def public_key_is_ed25519(cls, value: str) -> str:
        try:
            key = base64.b64decode(value, validate=True)
            Ed25519PublicKey.from_public_bytes(key)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("data release trust root must be an Ed25519 key") from exc
        return value

    def public_key(self) -> bytes:
        return base64.b64decode(self.public_key_ed25519_base64, validate=True)


class DataReleaseTrustRootsV1(ReleaseModel):
    verifiers: dict[str, DataReleaseVerifierV1] = Field(min_length=1)
    mapping_reviewers: dict[str, str] = Field(min_length=1)

    @field_validator("verifiers")
    @classmethod
    def verifier_ids_are_valid(
        cls, value: dict[str, DataReleaseVerifierV1]
    ) -> dict[str, DataReleaseVerifierV1]:
        if any(not verifier_id.strip() for verifier_id in value):
            raise ValueError("data release verifier IDs cannot be empty")
        return value

    @field_validator("mapping_reviewers")
    @classmethod
    def reviewer_keys_are_valid(cls, value: dict[str, str]) -> dict[str, str]:
        for reviewer_id, encoded_key in value.items():
            if not reviewer_id.strip():
                raise ValueError("mapping reviewer IDs cannot be empty")
            try:
                Ed25519PublicKey.from_public_bytes(
                    base64.b64decode(encoded_key, validate=True)
                )
            except (binascii.Error, ValueError) as exc:
                raise ValueError("mapping reviewer key must be an Ed25519 key") from exc
        return value

    @classmethod
    def from_file(cls, path: Path) -> DataReleaseTrustRootsV1:
        return cls.model_validate_json(path.read_bytes())

    def mapping_reviewer_public_key(self, reviewer_id: str) -> bytes | None:
        encoded_key = self.mapping_reviewers.get(reviewer_id)
        return (
            None
            if encoded_key is None
            else base64.b64decode(encoded_key, validate=True)
        )


def sign_mapping_review_evidence(
    payload: Mapping[str, object], private_key: Ed25519PrivateKey
) -> MappingReviewEvidenceV1:
    unsigned = MappingReviewEvidenceV1.model_validate(
        {**payload, "signature": "0" * 128}
    )
    signature = private_key.sign(unsigned.signing_bytes()).hex()
    return unsigned.model_copy(update={"signature": signature})


def sign_data_release_verification(
    payload: Mapping[str, object], private_key: Ed25519PrivateKey
) -> DataReleaseVerificationV1:
    verification_payload = dict(payload)
    verification_payload.pop("signature", None)
    verification_payload.pop("verification_digest", None)
    verification_payload["verification_digest"] = sha256_digest(verification_payload)
    unsigned = DataReleaseVerificationV1.model_validate(
        {**verification_payload, "signature": "0" * 128}
    )
    signature = private_key.sign(unsigned.signing_bytes()).hex()
    return unsigned.model_copy(update={"signature": signature})


def verify_data_release_verification(
    verification: DataReleaseVerificationV1,
    trust_roots: DataReleaseTrustRootsV1,
) -> None:
    verifier = trust_roots.verifiers.get(verification.verifier_id)
    if verifier is None:
        raise DataReleaseError(
            "DATA_RELEASE_VERIFIER_UNTRUSTED", "data release verifier is not trusted"
        )
    if (
        verification.workflow_identity != verifier.workflow_identity
        or verification.verification_suite_digest != verifier.verification_suite_digest
    ):
        raise DataReleaseError(
            "DATA_RELEASE_VERIFIER_MISMATCH",
            "verification workflow or suite does not match deployment trust roots",
        )
    try:
        Ed25519PublicKey.from_public_bytes(verifier.public_key()).verify(
            bytes.fromhex(verification.signature), verification.signing_bytes()
        )
    except (InvalidSignature, ValueError) as exc:
        raise DataReleaseError(
            "DATA_RELEASE_VERIFICATION_SIGNATURE_INVALID",
            "data release verification signature is invalid",
        ) from exc
    payload = verification.model_dump(
        mode="python", exclude={"verification_digest", "signature"}
    )
    if sha256_digest(payload) != verification.verification_digest:
        raise DataReleaseError(
            "DATA_RELEASE_VERIFICATION_DIGEST_INVALID",
            "data release verification digest is invalid",
        )


def verify_mapping_review_evidence(
    review: MappingReviewEvidenceV1,
    trust_roots: DataReleaseTrustRootsV1,
) -> None:
    public_key = trust_roots.mapping_reviewer_public_key(review.reviewer_id)
    if public_key is None:
        raise DataReleaseError(
            "DATA_RELEASE_MAPPING_REVIEWER_UNTRUSTED",
            "mapping reviewer is not trusted",
        )
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            bytes.fromhex(review.signature), review.signing_bytes()
        )
    except (InvalidSignature, ValueError) as exc:
        raise DataReleaseError(
            "DATA_RELEASE_MAPPING_REVIEW_SIGNATURE_INVALID",
            "mapping review signature is invalid",
        ) from exc


class DataReleaseActivationCommandV1(ReleaseModel):
    profile_id: str = Field(min_length=1)
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_revision: int = Field(ge=0)
    expected_manifest_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    operation: Literal["activate", "rollback"]
    command_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    organization_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def expected_pointer_is_coherent(self) -> DataReleaseActivationCommandV1:
        if (self.expected_revision == 0) != (self.expected_manifest_digest is None):
            raise ValueError(
                "revision zero requires a missing digest; later revisions require one"
            )
        return self


class ActiveDataReleaseV1(ReleaseModel):
    profile_id: str = Field(min_length=1)
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision: int = Field(ge=1)
    activated_at: datetime


class DataReleaseRepository(Protocol):
    def publish_candidate(
        self,
        manifest: DataReleaseManifestV1,
        verification: DataReleaseVerificationV1,
    ) -> None: ...

    def get_active(self, profile_id: str) -> ActiveDataReleaseV1 | None: ...

    def compare_and_swap(
        self, command: DataReleaseActivationCommandV1
    ) -> ActiveDataReleaseV1: ...


__all__ = [
    "DATA_RELEASE_CAPABILITY",
    "REQUIRED_DATA_RELEASE_GATES",
    "ActiveDataReleaseV1",
    "ArtifactRefV1",
    "DataReleaseActivationCommandV1",
    "DataReleaseError",
    "DataReleaseManifestV1",
    "DataReleaseRepository",
    "DataReleaseTrustRootsV1",
    "DataReleaseVerificationV1",
    "DataReleaseVerifierV1",
    "FactRefV1",
    "MappingRefV1",
    "MappingReviewEvidenceV1",
    "SnapshotRefV1",
    "sign_data_release_verification",
    "sign_mapping_review_evidence",
    "verify_data_release_verification",
    "verify_mapping_review_evidence",
]
