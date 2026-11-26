from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from .arelle_parser import ParsedXbrlFactV1
from .contracts import StrictModel
from .data_releases import ArtifactRefV1
from .fiscal_admission_history import FiscalHistoryHeadV1
from .fiscal_authority_contracts import PrincipalKind
from .fiscal_candidate_contracts import FiscalSourceUseScopeV1
from .fiscal_validation_contracts import FiscalValidationRuntimeV1
from .history_recovery_contracts import FiscalIssuanceContextV1
from .replay import ArtifactPublicationV1
from .serialization import canonical_bytes, sha256_digest

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identity = Annotated[str, Field(min_length=1, max_length=256)]
FiniteDecimal = Annotated[Decimal, Field(allow_inf_nan=False)]


class _ClassificationModel(StrictModel):
    model_config = ConfigDict(frozen=True)


class FiscalRecordClassificationCommandV1(_ClassificationModel):
    protocol: Literal["fundamental.record-fiscal-classification.v1"] = (
        "fundamental.record-fiscal-classification.v1"
    )
    command_id: Identity
    authority_id: Identity
    source_validation_ref: ArtifactRefV1
    witness_ref: ArtifactRefV1
    review_ref: ArtifactRefV1
    preparer_execution_ref: ArtifactRefV1
    security_id: Identity | None = None
    expires_at: AwareDatetime

    @property
    def command_digest(self) -> str:
        return sha256_digest(self)

    @property
    def artifact_id(self) -> str:
        return "fiscal-source-classification-v1:" + sha256_digest(
            {"authority_id": self.authority_id, "command_id": self.command_id}
        )


class FiscalReviewFactV1(_ClassificationModel):
    fact_id: Identity
    fact: ParsedXbrlFactV1
    table_index: int = Field(ge=0)
    row_index: int = Field(ge=0)
    table_sha256: Digest
    row_sha256: Digest
    raw_lexical: str = Field(min_length=1, max_length=1000)
    raw_sign: Literal["+", "-"] | None
    raw_scale: int = Field(ge=-1000, le=1000)
    raw_decimals: str = Field(min_length=1, max_length=32)
    value: FiniteDecimal


class FiscalReconciliationTermV1(_ClassificationModel):
    fact_id: Identity
    coefficient: int = Field(ge=-100, le=100)

    @model_validator(mode="after")
    def nonzero_coefficient(self) -> FiscalReconciliationTermV1:
        if self.coefficient == 0:
            raise ValueError("reconciliation coefficient cannot be zero")
        return self


class FiscalSourceReconciliationV1(_ClassificationModel):
    description: str = Field(min_length=1, max_length=2048)
    terms: tuple[FiscalReconciliationTermV1, ...] = Field(min_length=1, max_length=64)
    result_fact_id: Identity
    residual: FiniteDecimal
    precision_allowance: Annotated[FiniteDecimal, Field(ge=0)]

    @model_validator(mode="after")
    def unique_inputs(self) -> FiscalSourceReconciliationV1:
        ids = tuple(term.fact_id for term in self.terms)
        if len(set(ids)) != len(ids) or self.result_fact_id in ids:
            raise ValueError("reconciliation must use distinct input and output facts")
        return self


class FiscalSourceAccountingReviewV1(_ClassificationModel):
    protocol: Literal["fundamental.fiscal-source-accounting-review.v1"] = (
        "fundamental.fiscal-source-accounting-review.v1"
    )
    scope: FiscalSourceUseScopeV1
    opinion: Literal["source-as-disclosed"] = "source-as-disclosed"
    tagging: Literal["unresolved"] = "unresolved"
    facts: tuple[FiscalReviewFactV1, ...] = Field(min_length=1, max_length=128)
    reconciliations: tuple[FiscalSourceReconciliationV1, ...] = Field(
        min_length=1, max_length=64
    )
    limitations: tuple[str, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def exact_fact_set(self) -> FiscalSourceAccountingReviewV1:
        ids = tuple(fact.fact_id for fact in self.facts)
        if len(set(ids)) != len(ids):
            raise ValueError("review facts must be unique")
        referenced = {
            identity
            for item in self.reconciliations
            for identity in (
                item.result_fact_id,
                *(term.fact_id for term in item.terms),
            )
        }
        if not referenced <= set(ids) or any(
            not text.strip() for text in self.limitations
        ):
            raise ValueError(
                "review requires located reconciliation facts and limitations"
            )
        return self


class FiscalSourcePreparationExecutionV1(_ClassificationModel):
    protocol: Literal["fundamental.fiscal-source-preparation-execution.v1"] = (
        "fundamental.fiscal-source-preparation-execution.v1"
    )
    source_validation_ref: ArtifactRefV1
    source_binding_digest: Digest
    runtime: FiscalValidationRuntimeV1
    authority_id: Identity
    authority_grant_ref: ArtifactRefV1
    principal_id: Identity
    principal_kind: PrincipalKind
    key_id: Digest
    execution_id: Identity
    issuance: FiscalIssuanceContextV1
    started_at: AwareDatetime
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def ordered_execution(self) -> FiscalSourcePreparationExecutionV1:
        if self.completed_at < self.started_at:
            raise ValueError("preparation execution time is reversed")
        return self


class SignedFiscalSourcePreparationExecutionV1(_ClassificationModel):
    protocol: Literal["fundamental.signed-fiscal-source-preparation-execution.v1"] = (
        "fundamental.signed-fiscal-source-preparation-execution.v1"
    )
    execution: FiscalSourcePreparationExecutionV1
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")

    def signing_bytes(self) -> bytes:
        return canonical_bytes(self.model_dump(mode="json", exclude={"signature"}))


class FiscalClassifierActorV1(_ClassificationModel):
    authority_id: Identity
    principal_id: Identity
    principal_kind: PrincipalKind
    key_id: Digest
    execution_ref: ArtifactRefV1


class FiscalClassifierReviewExecutionV1(_ClassificationModel):
    protocol: Literal["fundamental.fiscal-classifier-review-execution.v1"] = (
        "fundamental.fiscal-classifier-review-execution.v1"
    )
    authority_id: Identity
    principal_id: Identity
    principal_kind: PrincipalKind
    key_id: Digest
    execution_id: Identity
    issuance: FiscalIssuanceContextV1
    command_digest: Digest
    scope_digest: Digest
    review_ref: ArtifactRefV1
    started_at: AwareDatetime
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def ordered_execution(self) -> FiscalClassifierReviewExecutionV1:
        if self.completed_at < self.started_at:
            raise ValueError("review execution time is reversed")
        return self


class SignedFiscalSourceClassificationV1(_ClassificationModel):
    protocol: Literal["fundamental.signed-fiscal-source-classification.v1"] = (
        "fundamental.signed-fiscal-source-classification.v1"
    )
    command: FiscalRecordClassificationCommandV1
    review: FiscalSourceAccountingReviewV1
    reviewer: FiscalClassifierActorV1
    authority_grant_ref: ArtifactRefV1
    issuance: FiscalIssuanceContextV1
    signed_at: AwareDatetime
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")

    @model_validator(mode="after")
    def exact_command(self) -> SignedFiscalSourceClassificationV1:
        scope = self.review.scope
        if (
            self.command.source_validation_ref != scope.source_validation_ref
            or self.command.witness_ref != scope.witness_ref
            or self.command.authority_id != self.reviewer.authority_id
            or self.signed_at >= self.command.expires_at
        ):
            raise ValueError("classification differs from command or expiry")
        return self

    def signing_bytes(self) -> bytes:
        return canonical_bytes(self.model_dump(mode="json", exclude={"signature"}))

    @property
    def artifact_id(self) -> str:
        return self.command.artifact_id


class FiscalClassificationPublicationV1(_ClassificationModel):
    signed_classification: SignedFiscalSourceClassificationV1
    publication: ArtifactPublicationV1
    history_heads: tuple[FiscalHistoryHeadV1, ...]


class FiscalRecordClassificationCommandV2(_ClassificationModel):
    protocol: Literal["fundamental.record-fiscal-classification.v2"] = (
        "fundamental.record-fiscal-classification.v2"
    )
    command_id: Identity
    authority_id: Identity
    source_validation_ref: ArtifactRefV1
    witness_ref: ArtifactRefV1
    review_ref: ArtifactRefV1
    preparer_execution_ref: ArtifactRefV1
    security_id: Identity | None = None
    expires_at: AwareDatetime

    @property
    def command_digest(self) -> str:
        return sha256_digest(self)

    @property
    def artifact_id(self) -> str:
        return "fiscal-source-classification-v2:" + sha256_digest(
            {"authority_id": self.authority_id, "command_id": self.command_id}
        )


class SignedFiscalSourceClassificationV2(_ClassificationModel):
    protocol: Literal["fundamental.signed-fiscal-source-classification.v2"] = (
        "fundamental.signed-fiscal-source-classification.v2"
    )
    command: FiscalRecordClassificationCommandV2
    review: FiscalSourceAccountingReviewV1
    reviewer: FiscalClassifierActorV1
    authority_grant_ref: ArtifactRefV1
    issuance: FiscalIssuanceContextV1
    signed_at: AwareDatetime
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")

    @model_validator(mode="after")
    def exact_command(self) -> SignedFiscalSourceClassificationV2:
        if (
            self.command.source_validation_ref
            != self.review.scope.source_validation_ref
            or self.command.witness_ref != self.review.scope.witness_ref
            or self.command.authority_id != self.reviewer.authority_id
            or self.signed_at >= self.command.expires_at
        ):
            raise ValueError("classification differs from command or expiry")
        return self

    def signing_bytes(self) -> bytes:
        return canonical_bytes(self.model_dump(mode="json", exclude={"signature"}))

    @property
    def artifact_id(self) -> str:
        return self.command.artifact_id


class FiscalClassificationPublicationV2(_ClassificationModel):
    signed_classification: SignedFiscalSourceClassificationV2
    publication: ArtifactPublicationV1
    history_heads: tuple[FiscalHistoryHeadV1, ...]
