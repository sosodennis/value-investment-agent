from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from .contracts import StrictModel
from .data_releases import ArtifactRefV1
from .fiscal_admission_history import FiscalHistoryHeadV1
from .fiscal_classification_contracts import (
    Digest,
    FiscalClassifierReviewExecutionV1,
    FiscalSourcePreparationExecutionV1,
    Identity,
)
from .fiscal_source_accounting_policy import FiscalAccountingPolicyIdentityV1
from .fiscal_validation_contracts import FiscalOriginalValidationRequestV1
from .history_recovery_contracts import FiscalIssuanceContextV1
from .serialization import canonical_bytes


class _ProducerModel(StrictModel):
    model_config = ConfigDict(frozen=True)


class FiscalAccountingAccreditationV1(_ProducerModel):
    protocol: Literal["fundamental.fiscal-accounting-accreditation.v1"] = (
        "fundamental.fiscal-accounting-accreditation.v1"
    )
    policy: FiscalAccountingPolicyIdentityV1
    independent_review_ref: ArtifactRefV1
    classifier_executable_digest: Digest
    valid_from: AwareDatetime
    valid_until: AwareDatetime

    @model_validator(mode="after")
    def ordered_validity(self) -> FiscalAccountingAccreditationV1:
        if self.valid_from >= self.valid_until:
            raise ValueError("policy accreditation validity is reversed")
        return self


class FiscalProducerOrderV1(_ProducerModel):
    protocol: Literal["fundamental.fiscal-source-producer-order.v1"] = (
        "fundamental.fiscal-source-producer-order.v1"
    )
    order_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
    role: Literal["source_preparer", "classifier"]
    audience: Identity
    authority_id: Identity
    deployment_digest: Digest
    executable_digest: Digest
    issuance: FiscalIssuanceContextV1
    source_request: FiscalOriginalValidationRequestV1 | None = None
    preparation_ref: ArtifactRefV1 | None = None
    witness_ref: ArtifactRefV1 | None = None
    security_id: Identity | None = None
    expected_head: FiscalHistoryHeadV1 | None = None
    valid_from: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def exact_selection(self) -> FiscalProducerOrderV1:
        preparer = self.role == "source_preparer"
        if (
            self.valid_from >= self.expires_at
            or preparer != (self.source_request is not None)
            or preparer == (self.preparation_ref is not None)
            or preparer == (self.witness_ref is not None)
            or preparer
            and (self.security_id is not None or self.expected_head is not None)
        ):
            raise ValueError("producer order requires an exact role selection")
        return self


class FiscalProducerInvocationV1(_ProducerModel):
    protocol: Literal["fundamental.fiscal-source-producer-invocation.v1"] = (
        "fundamental.fiscal-source-producer-invocation.v1"
    )
    order_ref: ArtifactRefV1
    attempt_id: Identity
    executable_digest: Digest
    installation_digest: Digest
    deployment_digest: Digest
    issuance: FiscalIssuanceContextV1
    started_at: AwareDatetime


class FiscalSourcePreparationExecutionV2(_ProducerModel):
    protocol: Literal["fundamental.fiscal-source-preparation-execution.v2"] = (
        "fundamental.fiscal-source-preparation-execution.v2"
    )
    execution: FiscalSourcePreparationExecutionV1
    invocation_ref: ArtifactRefV1
    request: FiscalOriginalValidationRequestV1
    mode: Literal["captured_then_replayed", "retained_then_replayed"]
    consumed_refs: tuple[ArtifactRefV1, ...] = Field(min_length=1, max_length=256)
    source_content_refs: tuple[ArtifactRefV1, ...] = Field(min_length=1, max_length=256)


class SignedFiscalSourcePreparationExecutionV2(_ProducerModel):
    protocol: Literal["fundamental.signed-fiscal-source-preparation-execution.v2"] = (
        "fundamental.signed-fiscal-source-preparation-execution.v2"
    )
    preparation: FiscalSourcePreparationExecutionV2
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")

    def signing_bytes(self) -> bytes:
        return canonical_bytes(self.model_dump(mode="json", exclude={"signature"}))


class FiscalClassifierReviewExecutionV2(_ProducerModel):
    protocol: Literal["fundamental.fiscal-classifier-review-execution.v2"] = (
        "fundamental.fiscal-classifier-review-execution.v2"
    )
    execution: FiscalClassifierReviewExecutionV1
    invocation_ref: ArtifactRefV1
    accreditation_ref: ArtifactRefV1
    accounting_basis_ref: ArtifactRefV1
    preparation_ref: ArtifactRefV1
    classifier_grant_ref: ArtifactRefV1


class FiscalAccountingRefusalExecutionV1(_ProducerModel):
    protocol: Literal["fundamental.fiscal-accounting-refusal-execution.v1"] = (
        "fundamental.fiscal-accounting-refusal-execution.v1"
    )
    invocation_ref: ArtifactRefV1
    accreditation_ref: ArtifactRefV1
    accounting_basis_ref: ArtifactRefV1
    preparation_ref: ArtifactRefV1
    classifier_grant_ref: ArtifactRefV1
    completed_at: AwareDatetime
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")

    def signing_bytes(self) -> bytes:
        return canonical_bytes(self.model_dump(mode="json", exclude={"signature"}))
