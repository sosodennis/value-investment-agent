from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from .contracts import StrictModel
from .data_releases import ArtifactRefV1
from .fiscal_admission_history import FiscalHistoryHeadV1
from .fiscal_candidate_contracts import Digest, FiscalCandidateContentV1
from .fiscal_candidate_preparation import CurrentFiscalCandidate
from .history_recovery_contracts import FiscalIssuanceContextV1
from .replay import ArtifactPublicationV1, ArtifactRecordV1
from .serialization import canonical_bytes, sha256_digest


class FiscalDisplayRequestV1(StrictModel):
    model_config = ConfigDict(frozen=True)
    protocol: Literal["fundamental.fiscal-display-request.v1"] = (
        "fundamental.fiscal-display-request.v1"
    )
    command_id: str = Field(min_length=1, max_length=128)
    authority_id: str = Field(min_length=1, max_length=256)
    candidate_ref: ArtifactRefV1
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def exact_candidate(self) -> FiscalDisplayRequestV1:
        if (
            self.candidate_ref.role != "fiscal-statement-candidate-v2"
            or self.candidate_ref.media_type != "application/json"
        ):
            raise ValueError("display requires an exact V2 candidate reference")
        return self

    @property
    def locator_digest(self) -> str:
        return sha256_digest((self.protocol, self.command_id))

    def artifact_id(self, role: str) -> str:
        return role + ":" + self.locator_digest


class FiscalDisplayReviewScopeV1(StrictModel):
    model_config = ConfigDict(frozen=True)
    candidate_ref: ArtifactRefV1
    candidate_digest: Digest
    content: FiscalCandidateContentV1
    projection_digest: Digest
    node_digests: tuple[tuple[str, Digest], ...] = Field(min_length=1)
    observation_digests: tuple[tuple[str, Digest], ...] = Field(min_length=1)
    display_policy_digest: Digest
    executable_digest: Digest


class FiscalDisplayReviewExecutionV1(StrictModel):
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
    def ordered(self) -> FiscalDisplayReviewExecutionV1:
        if self.completed_at < self.started_at:
            raise ValueError("display review clock reversed")
        return self


class FiscalDisplayReviewV1(StrictModel):
    model_config = ConfigDict(frozen=True)
    protocol: Literal["fundamental.fiscal-display-review.v1"] = (
        "fundamental.fiscal-display-review.v1"
    )
    request: FiscalDisplayRequestV1
    reviewed: FiscalDisplayReviewScopeV1
    execution: FiscalDisplayReviewExecutionV1


class FiscalDecideDisplayCommandV1(StrictModel):
    model_config = ConfigDict(frozen=True)
    protocol: Literal["fundamental.decide-fiscal-display.v1"] = (
        "fundamental.decide-fiscal-display.v1"
    )
    request: FiscalDisplayRequestV1
    release_review_ref: ArtifactRefV1

    @property
    def command_digest(self) -> str:
        return sha256_digest(self)


class FiscalDisplayDecisionBodyV1(StrictModel):
    model_config = ConfigDict(frozen=True)
    command: FiscalDecideDisplayCommandV1
    review: FiscalDisplayReviewV1
    signed_at: AwareDatetime

    @model_validator(mode="after")
    def exact_review(self) -> FiscalDisplayDecisionBodyV1:
        if (
            self.command.request != self.review.request
            or not self.review.execution.completed_at
            <= self.signed_at
            < self.review.request.expires_at
        ):
            raise ValueError("display decision differs from actual review")
        return self


class SignedFiscalDisplayDecisionV1(StrictModel):
    model_config = ConfigDict(frozen=True)
    protocol: Literal["fundamental.fiscal-display-decision.v1"] = (
        "fundamental.fiscal-display-decision.v1"
    )
    body: FiscalDisplayDecisionBodyV1
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")

    @property
    def artifact_id(self) -> str:
        return self.body.command.request.artifact_id("fiscal-display-decision-v1")

    def signing_bytes(self) -> bytes:
        return canonical_bytes(self.body)


@dataclass(frozen=True)
class CurrentFiscalDisplay:
    reference: ArtifactRefV1
    decision: SignedFiscalDisplayDecisionV1
    candidate: CurrentFiscalCandidate
    publication: ArtifactPublicationV1
    consumed_metadata: tuple[ArtifactRecordV1, ...]
    history_heads: tuple[FiscalHistoryHeadV1, ...]
    observed_at: datetime
