"""Typed contracts for immutable Fundamental data releases."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .serialization import sha256_digest

DATA_RELEASE_CAPABILITY = "data-release-activation-v1"


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
    signature: str = Field(min_length=1)

    @model_validator(mode="after")
    def review_is_independent(self) -> MappingReviewEvidenceV1:
        if self.author_id == self.reviewer_id:
            raise ValueError("mapping author cannot review their own mapping")
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must include a timezone")
        return self


class DataReleaseVerificationV1(ReleaseModel):
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    verification_suite_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    passed_gate_ids: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[ArtifactRefV1, ...] = Field(min_length=1)
    mapping_reviews: tuple[MappingReviewEvidenceV1, ...] = ()
    verification_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verification_digest_matches(self) -> DataReleaseVerificationV1:
        if len(set(self.passed_gate_ids)) != len(self.passed_gate_ids):
            raise ValueError("passed gate IDs must be unique")
        payload = self.model_dump(mode="python", exclude={"verification_digest"})
        if sha256_digest(payload) != self.verification_digest:
            raise ValueError("verification_digest does not match its evidence")
        return self


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
    "ActiveDataReleaseV1",
    "ArtifactRefV1",
    "DataReleaseActivationCommandV1",
    "DataReleaseError",
    "DataReleaseManifestV1",
    "DataReleaseRepository",
    "DataReleaseVerificationV1",
    "FactRefV1",
    "MappingRefV1",
    "MappingReviewEvidenceV1",
    "SnapshotRefV1",
]
