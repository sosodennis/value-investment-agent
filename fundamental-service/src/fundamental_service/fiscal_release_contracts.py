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


class FiscalPublishV2(ReleaseModel):
    candidate_ref: ArtifactRefV1
    decision_ref: ArtifactRefV1

    @model_validator(mode="after")
    def exact_refs(self) -> FiscalPublishV2:
        require_fiscal_ref(self.candidate_ref, "fiscal-statement-candidate-v3")
        require_fiscal_ref(self.decision_ref, "fiscal-display-decision-v2")
        return self


class FiscalReleaseEnvelopeV2(ReleaseModel):
    protocol: Literal["fundamental.fiscal-release-envelope.v2"] = (
        "fundamental.fiscal-release-envelope.v2"
    )
    approved: FiscalPublishV2
    candidate_content_digest: Digest
    projection_ref: ArtifactRefV1

    @model_validator(mode="after")
    def exact_projection(self) -> FiscalReleaseEnvelopeV2:
        require_fiscal_ref(self.projection_ref, "fiscal-statement-projection-v1")
        return self

    @property
    def artifact_id(self) -> str:
        return "fiscal-release-envelope-v2:" + sha256_digest(self)


class FiscalReleaseManifestV2(ReleaseModel):
    protocol: Literal["fundamental.fiscal-release-manifest.v2"] = (
        "fundamental.fiscal-release-manifest.v2"
    )
    profile_id: str = Field(pattern=r"^fiscal-statements-v2:[0-9a-f]{64}$")
    release_id: str = Field(pattern=r"^fiscal-release-v2:[0-9a-f]{64}$")
    created_at: AwareDatetime
    scope: StatementScopeV1
    cutoff_at: AwareDatetime
    envelope_ref: ArtifactRefV1
    manifest_digest: Digest

    @model_validator(mode="after")
    def identity(self) -> FiscalReleaseManifestV2:
        require_fiscal_ref(self.envelope_ref, "fiscal-release-envelope-v2")
        if (
            sha256_digest(self.model_dump(exclude={"manifest_digest"}))
            != self.manifest_digest
        ):
            raise ValueError(
                "fiscal manifest digest differs from its canonical preimage"
            )
        return self


class FiscalReleaseChecksV2(ReleaseModel):
    protocol: Literal["fundamental.fiscal-release-checks.v2"] = (
        "fundamental.fiscal-release-checks.v2"
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
        return "fiscal-release-checks-v2:" + sha256_digest(self)


class FiscalReleaseVerificationV2(ReleaseModel):
    protocol: Literal["fundamental.fiscal-release-verification.v2"] = (
        "fundamental.fiscal-release-verification.v2"
    )
    manifest_digest: Digest
    checked_ref: ArtifactRefV1
    canary_ref: ArtifactRefV1
    candidate_correctness_digest: Digest
    replay_contract_digest: Digest
    replay_executable_digest: Digest
    verification_suite_digest: Digest
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    verification_run_id: str = Field(min_length=1)
    workflow_identity: str = Field(min_length=1)
    verifier_id: str = Field(min_length=1)
    verification_digest: Digest
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")

    @model_validator(mode="after")
    def identity(self) -> FiscalReleaseVerificationV2:
        require_fiscal_ref(self.checked_ref, "fiscal-release-checks-v2")
        require_fiscal_ref(self.canary_ref, "fiscal-release-canary-v2")
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


class FiscalReleaseCanaryV2(ReleaseModel):
    protocol: Literal["fundamental.fiscal-release-canary.v2"] = (
        "fundamental.fiscal-release-canary.v2"
    )
    manifest_digest: Digest
    checked_ref: ArtifactRefV1
    candidate_correctness_digest: Digest
    replay_contract_digest: Digest
    replay_executable_digest: Digest
    replay_result_digest: Digest

    @model_validator(mode="after")
    def exact_checks(self) -> FiscalReleaseCanaryV2:
        require_fiscal_ref(self.checked_ref, "fiscal-release-checks-v2")
        return self

    @property
    def artifact_id(self) -> str:
        return "fiscal-release-canary-v2:" + sha256_digest(self)


class FiscalStoredVerificationV2(ReleaseModel):
    protocol: Literal["fundamental.fiscal-stored-verification.v2"] = (
        "fundamental.fiscal-stored-verification.v2"
    )
    signed: FiscalReleaseVerificationV2
    canary_ref: ArtifactRefV1

    @model_validator(mode="after")
    def exact_canary(self) -> FiscalStoredVerificationV2:
        require_fiscal_ref(self.canary_ref, "fiscal-release-canary-v2")
        if self.canary_ref != self.signed.canary_ref:
            raise ValueError("stored canary differs from the workflow-signed canary")
        return self

    @property
    def verification_digest(self) -> str:
        return self.signed.verification_digest

    @property
    def manifest_digest(self) -> str:
        return self.signed.manifest_digest


class FiscalReleaseCandidateReceiptV2(ReleaseModel):
    protocol: Literal["fundamental.fiscal-release-candidate-receipt.v2"] = (
        "fundamental.fiscal-release-candidate-receipt.v2"
    )
    profile_id: str
    release_id: str
    manifest_digest: Digest
    verification_digest: Digest
    envelope_ref: ArtifactRefV1
    canary_ref: ArtifactRefV1
    wrote: bool


class ActiveFiscalReleaseV2(ReleaseModel):
    active: ActiveDataReleaseV1
    manifest: FiscalReleaseManifestV2

    @model_validator(mode="after")
    def exact_pointer(self) -> ActiveFiscalReleaseV2:
        if (self.active.profile_id, self.active.manifest_digest) != (
            self.manifest.profile_id,
            self.manifest.manifest_digest,
        ):
            raise ValueError("active fiscal pointer differs from its manifest")
        return self


def fiscal_manifest(
    envelope: FiscalReleaseEnvelopeV2,
    envelope_ref: ArtifactRefV1,
    *,
    scope: StatementScopeV1,
    cutoff_at: datetime,
    display_profile_digest: str,
    created_at: datetime,
) -> FiscalReleaseManifestV2:
    fields = dict(
        protocol="fundamental.fiscal-release-manifest.v2",
        profile_id="fiscal-statements-v2:"
        + sha256_digest(
            (scope, cutoff_at, display_profile_digest, "quarter-and-ttm-v1")
        ),
        release_id="fiscal-release-v2:"
        + sha256_digest(("fiscal-release-identity-v2", envelope)),
        created_at=created_at,
        scope=scope,
        cutoff_at=cutoff_at,
        envelope_ref=envelope_ref,
    )
    return FiscalReleaseManifestV2.model_validate(
        {**fields, "manifest_digest": sha256_digest(fields)}
    )
