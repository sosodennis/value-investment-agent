"""Authenticated automatic caller execution using pinned deployment policy."""

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .application.service import FundamentalApplication
from .automatic_approval import (
    AutomaticValuationApprovalPolicyV1,
    automatic_approval_issues,
)
from .contracts import (
    ArtifactReferenceV1,
    CalculationArtifactV1,
    CallerApprovalEnvelopeV1,
    StrictModel,
    ValuationEvidenceReadRequestV1,
)
from .data_releases import ArtifactRefV1
from .operations import ServiceError, guard_execution_deadline
from .replay import ArtifactPublicationV1
from .serialization import sha256_digest
from .snapshots import SnapshotError
from .uncertainty import UncertaintyReportV1


class AutomaticValuationRequestV1(StrictModel):
    preparation: ValuationEvidenceReadRequestV1
    expected_input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class AutomaticApprovalDecisionV1(StrictModel):
    protocol: Literal["automatic-valuation-approval-v1"] = (
        "automatic-valuation-approval-v1"
    )
    decision: Literal["approved", "rejected"]
    caller_id: str = Field(min_length=1)
    organization_id: str = Field(min_length=1)
    policy_ref: ArtifactRefV1
    preparation_ref: ArtifactRefV1
    expected_input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    requested_policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_use_policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    issue_codes: tuple[str, ...]


class AutomaticValuationExecutionEvidenceV1(StrictModel):
    protocol: Literal["automatic-valuation-execution-v1"] = (
        "automatic-valuation-execution-v1"
    )
    approval_ref: ArtifactRefV1
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_references: tuple[ArtifactReferenceV1, ...] = Field(min_length=1)


class AutomaticValuationResponseV1(StrictModel):
    decision: AutomaticApprovalDecisionV1
    policy_publication: ArtifactPublicationV1
    preparation_publication: ArtifactPublicationV1
    decision_publication: ArtifactPublicationV1
    execution_publication: ArtifactPublicationV1 | None = None
    calculation: CalculationArtifactV1 | UncertaintyReportV1 | None = None

    @model_validator(mode="after")
    def decision_matches_execution(self) -> "AutomaticValuationResponseV1":
        decision = self.decision
        if (decision.decision == "approved") != (not decision.issue_codes):
            raise ValueError("automatic decision must preserve its refusal reasons")
        for reference, publication in (
            (decision.policy_ref, self.policy_publication),
            (decision.preparation_ref, self.preparation_publication),
        ):
            if (
                reference.artifact_id != publication.artifact.artifact_id
                or reference.content_hash != publication.artifact.content_hash
                or reference.media_type != publication.artifact.media_type
            ):
                raise ValueError(
                    "automatic decision publication differs from reference"
                )
        if sha256_digest(decision) != self.decision_publication.artifact.content_hash:
            raise ValueError("automatic decision publication content differs")
        if (self.execution_publication is None) != (self.calculation is None):
            raise ValueError("automatic execution must retain its calculation")
        if self.calculation is not None and (
            decision.decision != "approved"
            or self.calculation.input_digest != decision.input_digest
            or decision.input_digest != decision.expected_input_digest
        ):
            raise ValueError("automatic calculation requires its exact approved input")
        if decision.decision == "approved" and (
            decision.policy_ref.content_hash != decision.requested_policy_digest
        ):
            raise ValueError("automatic approval requires the requested policy")
        if self.calculation is not None:
            execution = AutomaticValuationExecutionEvidenceV1(
                approval_ref=_reference(self.decision_publication, decision.protocol),
                input_digest=self.calculation.input_digest,
                result_digest=sha256_digest(self.calculation),
                result_references=self.calculation.artifact_references,
            )
            assert self.execution_publication is not None
            if (
                sha256_digest(execution)
                != self.execution_publication.artifact.content_hash
            ):
                raise ValueError("automatic execution publication content differs")
        return self


def load_runtime_automatic_approval_policy() -> (
    AutomaticValuationApprovalPolicyV1 | None
):
    file_value = os.getenv("FUNDAMENTAL_AUTOMATIC_APPROVAL_POLICY_FILE")
    expected_digest = os.getenv("FUNDAMENTAL_AUTOMATIC_APPROVAL_POLICY_DIGEST")
    if file_value is None and expected_digest is None:
        return None
    if not file_value or not expected_digest:
        raise ValueError("automatic approval requires deployment file and digest")
    try:
        policy = AutomaticValuationApprovalPolicyV1.model_validate_json(
            Path(file_value).read_bytes()
        )
    except (OSError, ValueError):
        raise ValueError("automatic approval policy is unreadable or invalid") from None
    if policy.digest != expected_digest:
        raise ValueError("automatic approval deployment policy digest differs")
    return policy


def _reference(publication: ArtifactPublicationV1, role: str) -> ArtifactRefV1:
    record = publication.artifact
    return ArtifactRefV1(
        artifact_id=record.artifact_id,
        content_hash=record.content_hash,
        media_type=record.media_type,
        role=role,
    )


class AutomaticValuationExecutor:
    """Recompose before every decision; never accept a caller-supplied input."""

    def __init__(
        self,
        application: FundamentalApplication,
        policy: AutomaticValuationApprovalPolicyV1 | None,
    ) -> None:
        self._application = application
        self._policy = policy

    def _publish(
        self,
        artifact_id: str,
        value: object,
        dependency_hashes: tuple[str, ...] = (),
    ) -> ArtifactPublicationV1:
        try:
            return self._application.artifact_store.put_with_receipt(
                artifact_id, value, dependency_hashes=dependency_hashes
            )
        except SnapshotError as error:
            raise ServiceError(
                error.code, str(error), status_code=422, retryable=False
            ) from error

    def execute(
        self,
        request: AutomaticValuationRequestV1,
        *,
        caller_id: str,
        organization_id: str,
        deadline_at: datetime,
    ) -> AutomaticValuationResponseV1:
        policy = self._policy
        if policy is None:
            raise ServiceError(
                "AUTOMATIC_APPROVAL_NOT_CONFIGURED",
                "deployment has not authorized an automatic valuation caller",
                status_code=403,
                retryable=False,
            )
        application = self._application
        artifacts = application.artifact_store
        if artifacts is None:
            raise ServiceError(
                "ARTIFACT_UNAVAILABLE",
                "automatic approval requires retained decision evidence",
                status_code=503,
                retryable=True,
            )
        source_policy = application.source_use_policy
        if source_policy is None:
            raise ServiceError(
                "AUTOMATIC_APPROVAL_SOURCE_POLICY_MISSING",
                "automatic approval requires a deployed source-use policy",
                status_code=403,
                retryable=False,
            )
        operation = application.prepare_valuation_operation(
            request.preparation, deadline_at=deadline_at
        )
        preparation = operation.preparation
        guard_execution_deadline(deadline_at)
        issues = automatic_approval_issues(
            policy,
            preparation,
            caller_id=caller_id,
            organization_id=organization_id,
            expected_input_digest=request.expected_input_digest,
            source_use_policy_digest=source_policy.digest,
            received_at=datetime.now(UTC),
        )
        if request.approval_policy_digest != policy.digest:
            issues = tuple(sorted({*issues, "AUTOMATIC_APPROVAL_POLICY_MISMATCH"}))
        policy_publication = self._publish(
            f"automatic-valuation-policy:{policy.digest}", policy
        )
        preparation_publication = self._publish(
            f"automatic-valuation-preparation:{sha256_digest(preparation)}",
            preparation,
            dependency_hashes=(
                request.preparation.data_release_manifest_digest,
                preparation.preparation_digest,
            ),
        )
        value = preparation.input
        decision = AutomaticApprovalDecisionV1(
            decision="rejected" if issues else "approved",
            caller_id=caller_id,
            organization_id=organization_id,
            policy_ref=_reference(policy_publication, policy.protocol),
            preparation_ref=_reference(
                preparation_publication, "automatic-valuation-preparation-v1"
            ),
            expected_input_digest=request.expected_input_digest,
            input_digest=value.input_digest if value is not None else None,
            requested_policy_digest=request.approval_policy_digest,
            source_use_policy_digest=source_policy.digest,
            issue_codes=issues,
        )
        guard_execution_deadline(deadline_at)
        decision_publication = self._publish(
            f"automatic-valuation-approval:{sha256_digest(decision)}",
            decision,
            dependency_hashes=(
                decision.policy_ref.content_hash,
                decision.preparation_ref.content_hash,
                decision.source_use_policy_digest,
            ),
        )
        response = AutomaticValuationResponseV1(
            decision=decision,
            policy_publication=policy_publication,
            preparation_publication=preparation_publication,
            decision_publication=decision_publication,
        )
        if issues:
            return response
        assert value is not None and value.input_digest is not None
        # This envelope is created only after the authenticated caller's policy
        # decision is retained. It is not a representation of human approval.
        approval = CallerApprovalEnvelopeV1(
            input_digest=value.input_digest,
            decision="approved",
            caller_id=caller_id,
            decided_at=datetime.now(UTC),
        )
        calculation = operation.calculate(
            approval,
            correlation_id=f"automatic-valuation:{value.input_digest}",
        )
        guard_execution_deadline(deadline_at)
        execution = AutomaticValuationExecutionEvidenceV1(
            approval_ref=_reference(decision_publication, decision.protocol),
            input_digest=value.input_digest,
            result_digest=sha256_digest(calculation),
            result_references=calculation.artifact_references,
        )
        execution_publication = self._publish(
            f"automatic-valuation-execution:{sha256_digest(execution)}",
            execution,
            dependency_hashes=(
                execution.approval_ref.content_hash,
                *(item.content_hash for item in execution.result_references),
            ),
        )
        return AutomaticValuationResponseV1.model_validate(
            {
                **response.model_dump(),
                "execution_publication": execution_publication,
                "calculation": calculation,
            }
        )
