from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from .contracts import StrictModel
from .data_releases import ArtifactRefV1
from .fiscal_admission_history import FiscalHistoryHeadV1
from .fiscal_candidate_contracts import Digest, FiscalCandidateContentV2
from .fiscal_candidate_preparation import CurrentFiscalCandidate
from .history_recovery_contracts import FiscalIssuanceContextV1
from .replay import ArtifactPublicationV1, ArtifactRecordV1
from .serialization import canonical_bytes, sha256_digest
from .fiscal_source_closure import FiscalArtifactReadSet, FiscalSourceContentReadSet


class FiscalDisplayRequestV2(StrictModel):
    model_config = ConfigDict(frozen=True)
    protocol: Literal["fundamental.fiscal-display-request.v2"] = (
        "fundamental.fiscal-display-request.v2"
    )
    command_id: str = Field(min_length=1, max_length=128)
    authority_id: str = Field(min_length=1, max_length=256)
    candidate_ref: ArtifactRefV1
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def exact_candidate(self) -> FiscalDisplayRequestV2:
        if (
            self.candidate_ref.role != "fiscal-statement-candidate-v3"
            or self.candidate_ref.media_type != "application/json"
        ):
            raise ValueError("display requires an exact V3 candidate reference")
        return self

    @property
    def locator_digest(self) -> str:
        return sha256_digest((self.protocol, self.command_id))

    def artifact_id(self, role: str) -> str:
        return role + ":" + self.locator_digest


class FiscalDisplayReviewScopeV2(StrictModel):
    model_config = ConfigDict(frozen=True)
    candidate_ref: ArtifactRefV1
    candidate_digest: Digest
    content: FiscalCandidateContentV2
    projection_digest: Digest
    node_digests: tuple[tuple[str, Digest], ...] = Field(min_length=1)
    observation_digests: tuple[tuple[str, Digest], ...] = Field(min_length=1)
    display_policy_digest: Digest
    executable_digest: Digest


class FiscalDisplayReviewExecutionV2(StrictModel):
    model_config = ConfigDict(frozen=True)
    authority_id: str
    grant_ref: ArtifactRefV1
    principal_id: str
    principal_kind: Literal["machine"] = "machine"
    key_id: Digest
    execution_id: str = Field(pattern=r"^display-job:[0-9a-f]{32}$")
    issuance: FiscalIssuanceContextV1
    started_at: AwareDatetime
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def ordered(self) -> FiscalDisplayReviewExecutionV2:
        if self.completed_at < self.started_at:
            raise ValueError("display review clock reversed")
        return self


class FiscalDisplayReviewV2(StrictModel):
    model_config = ConfigDict(frozen=True)
    protocol: Literal["fundamental.fiscal-display-review.v2"] = (
        "fundamental.fiscal-display-review.v2"
    )
    request: FiscalDisplayRequestV2
    reviewed: FiscalDisplayReviewScopeV2
    execution: FiscalDisplayReviewExecutionV2


class FiscalDecideDisplayCommandV2(StrictModel):
    model_config = ConfigDict(frozen=True)
    protocol: Literal["fundamental.decide-fiscal-display.v2"] = (
        "fundamental.decide-fiscal-display.v2"
    )
    request: FiscalDisplayRequestV2
    release_review_ref: ArtifactRefV1

    @property
    def command_digest(self) -> str:
        return sha256_digest(self)


class FiscalDisplayDecisionBodyV2(StrictModel):
    model_config = ConfigDict(frozen=True)
    command: FiscalDecideDisplayCommandV2
    review: FiscalDisplayReviewV2
    signed_at: AwareDatetime

    @model_validator(mode="after")
    def exact_review(self) -> FiscalDisplayDecisionBodyV2:
        if (
            self.command.request != self.review.request
            or not self.review.execution.completed_at
            <= self.signed_at
            < self.review.request.expires_at
        ):
            raise ValueError("display decision differs from actual review")
        return self


class SignedFiscalDisplayDecisionV2(StrictModel):
    model_config = ConfigDict(frozen=True)
    protocol: Literal["fundamental.fiscal-display-decision.v2"] = (
        "fundamental.fiscal-display-decision.v2"
    )
    body: FiscalDisplayDecisionBodyV2
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")

    @property
    def artifact_id(self) -> str:
        return self.body.command.request.artifact_id("fiscal-display-decision-v2")

    def signing_bytes(self) -> bytes:
        return canonical_bytes(self.body)


@dataclass(frozen=True)
class CurrentFiscalDisplay:
    reference: ArtifactRefV1
    decision: SignedFiscalDisplayDecisionV2
    candidate: CurrentFiscalCandidate
    publication: ArtifactPublicationV1
    consumed_metadata: tuple[ArtifactRecordV1, ...]
    history_heads: tuple[FiscalHistoryHeadV1, ...]
    observed_at: datetime
    artifact_readset: FiscalArtifactReadSet
    content_readsets: tuple[FiscalSourceContentReadSet, ...]
