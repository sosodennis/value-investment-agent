from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from .data_releases import ActiveDataReleaseV1, ArtifactRefV1, ReleaseModel
from .serialization import canonical_bytes, sha256_digest
from .statement_contracts import StatementScopeV1

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def require_fiscal_ref(ref: ArtifactRefV1, role: str) -> None:
    if ref.role != role or ref.media_type != "application/json":
        raise ValueError("fiscal release requires its exact JSON artifact role")


class FiscalPublishV1(ReleaseModel):
    candidate_ref: ArtifactRefV1
    decision_ref: ArtifactRefV1

    @model_validator(mode="after")
    def exact_refs(self) -> FiscalPublishV1:
        require_fiscal_ref(self.candidate_ref, "fiscal-statement-candidate-v2")
        require_fiscal_ref(self.decision_ref, "fiscal-display-decision-v1")
        return self


class FiscalReleaseEnvelopeV1(ReleaseModel):
    protocol: Literal["fundamental.fiscal-release-envelope.v1"] = (
        "fundamental.fiscal-release-envelope.v1"
    )
    approved: FiscalPublishV1
    candidate_content_digest: Digest
    projection_ref: ArtifactRefV1

    @model_validator(mode="after")
    def exact_projection(self) -> FiscalReleaseEnvelopeV1:
        require_fiscal_ref(self.projection_ref, "fiscal-statement-projection-v1")
        return self

    @property
    def artifact_id(self) -> str:
        return "fiscal-release-envelope-v1:" + sha256_digest(self)


class FiscalReleaseManifestV1(ReleaseModel):
    protocol: Literal["fundamental.fiscal-release-manifest.v1"] = (
        "fundamental.fiscal-release-manifest.v1"
    )
    profile_id: str = Field(pattern=r"^fiscal-statements-v1:[0-9a-f]{64}$")
    release_id: str = Field(pattern=r"^fiscal-release-v1:[0-9a-f]{64}$")
    created_at: AwareDatetime
    scope: StatementScopeV1
    cutoff_at: AwareDatetime
    envelope_ref: ArtifactRefV1
    manifest_digest: Digest

    @model_validator(mode="after")
    def identity(self) -> FiscalReleaseManifestV1:
        require_fiscal_ref(self.envelope_ref, "fiscal-release-envelope-v1")
        if (
            sha256_digest(self.model_dump(exclude={"manifest_digest"}))
            != self.manifest_digest
        ):
            raise ValueError(
                "fiscal manifest digest differs from its canonical preimage"
            )
        return self


class FiscalReleaseChecksV1(ReleaseModel):
    protocol: Literal["fundamental.fiscal-release-checks.v1"] = (
        "fundamental.fiscal-release-checks.v1"
    )
    manifest_digest: Digest
    candidate_content_digest: Digest
    raw_source_closure_digest: Digest
    parser_resources_digest: Digest
    mapping_approvals_digest: Digest
    admission_scope_digest: Digest
    periods_and_dag_digest: Digest
    quality_and_policy_digest: Digest
    retained_refs: tuple[ArtifactRefV1, ...] = Field(min_length=1)

    @property
    def artifact_id(self) -> str:
        return "fiscal-release-checks-v1:" + sha256_digest(self)


class FiscalReleaseVerificationV1(ReleaseModel):
    protocol: Literal["fundamental.fiscal-release-verification.v1"] = (
        "fundamental.fiscal-release-verification.v1"
    )
    manifest_digest: Digest
    checked_ref: ArtifactRefV1
    verification_suite_digest: Digest
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    verification_run_id: str = Field(min_length=1)
    workflow_identity: str = Field(min_length=1)
    verifier_id: str = Field(min_length=1)
    verification_digest: Digest
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")

    @model_validator(mode="after")
    def identity(self) -> FiscalReleaseVerificationV1:
        require_fiscal_ref(self.checked_ref, "fiscal-release-checks-v1")
        if (
            sha256_digest(self.model_dump(exclude={"verification_digest", "signature"}))
            != self.verification_digest
        ):
            raise ValueError(
                "fiscal verification digest differs from its canonical preimage"
            )
        return self

    def signing_bytes(self) -> bytes:
        return canonical_bytes(self.model_dump(exclude={"signature"}))


class FiscalReleaseCanaryV1(ReleaseModel):
    protocol: Literal["fundamental.fiscal-release-canary.v1"] = (
        "fundamental.fiscal-release-canary.v1"
    )
    manifest_digest: Digest
    verification_digest: Digest
    checked_ref: ArtifactRefV1

    @model_validator(mode="after")
    def exact_checks(self) -> FiscalReleaseCanaryV1:
        require_fiscal_ref(self.checked_ref, "fiscal-release-checks-v1")
        return self

    @property
    def artifact_id(self) -> str:
        return "fiscal-release-canary-v1:" + sha256_digest(self)


class FiscalStoredVerificationV1(ReleaseModel):
    protocol: Literal["fundamental.fiscal-stored-verification.v1"] = (
        "fundamental.fiscal-stored-verification.v1"
    )
    signed: FiscalReleaseVerificationV1
    canary_ref: ArtifactRefV1

    @model_validator(mode="after")
    def exact_canary(self) -> FiscalStoredVerificationV1:
        require_fiscal_ref(self.canary_ref, "fiscal-release-canary-v1")
        return self

    @property
    def verification_digest(self) -> str:
        return self.signed.verification_digest

    @property
    def manifest_digest(self) -> str:
        return self.signed.manifest_digest


class FiscalReleaseCandidateReceiptV1(ReleaseModel):
    protocol: Literal["fundamental.fiscal-release-candidate-receipt.v1"] = (
        "fundamental.fiscal-release-candidate-receipt.v1"
    )
    profile_id: str
    release_id: str
    manifest_digest: Digest
    verification_digest: Digest
    envelope_ref: ArtifactRefV1
    canary_ref: ArtifactRefV1
    wrote: bool


class ActiveFiscalReleaseV1(ReleaseModel):
    active: ActiveDataReleaseV1
    manifest: FiscalReleaseManifestV1

    @model_validator(mode="after")
    def exact_pointer(self) -> ActiveFiscalReleaseV1:
        if (self.active.profile_id, self.active.manifest_digest) != (
            self.manifest.profile_id,
            self.manifest.manifest_digest,
        ):
            raise ValueError("active fiscal pointer differs from its manifest")
        return self


def fiscal_manifest(
    envelope: FiscalReleaseEnvelopeV1,
    envelope_ref: ArtifactRefV1,
    *,
    scope: StatementScopeV1,
    cutoff_at: datetime,
    display_profile_digest: str,
    created_at: datetime,
) -> FiscalReleaseManifestV1:
    fields = dict(
        protocol="fundamental.fiscal-release-manifest.v1",
        profile_id="fiscal-statements-v1:"
        + sha256_digest(
            (scope, cutoff_at, display_profile_digest, "quarter-and-ttm-v1")
        ),
        release_id="fiscal-release-v1:"
        + sha256_digest(("fiscal-release-identity-v1", envelope)),
        created_at=created_at,
        scope=scope,
        cutoff_at=cutoff_at,
        envelope_ref=envelope_ref,
    )
    return FiscalReleaseManifestV1.model_validate(
        {**fields, "manifest_digest": sha256_digest(fields)}
    )
