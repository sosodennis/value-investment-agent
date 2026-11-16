"""Deployment authorization for a service-composed exact valuation input."""

from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from .contracts import StrictModel
from .serialization import sha256_digest
from .valuation_preparation import AutomaticValuationPreparationV1


class AutomaticCallerGrantV1(StrictModel):
    model_config = ConfigDict(frozen=True)
    caller_id: str = Field(min_length=1)
    organization_id: str = Field(min_length=1)


class AutomaticApprovalModelV1(StrictModel):
    model_config = ConfigDict(frozen=True)
    model_id: Literal["fcff_dcf", "transition_fcff_dcf"]
    model_version: str = Field(min_length=1)
    valuation_policy_version: str = Field(min_length=1)


class AutomaticValuationApprovalPolicyV1(StrictModel):
    """No built-in grant: the deployment must pin and authorize this policy."""

    model_config = ConfigDict(frozen=True)

    protocol: Literal["automatic-valuation-approval-policy-v1"] = (
        "automatic-valuation-approval-policy-v1"
    )
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    effective_from: datetime
    expires_at: datetime
    callers: tuple[AutomaticCallerGrantV1, ...] = Field(min_length=1)
    models: tuple[AutomaticApprovalModelV1, ...] = Field(min_length=1)
    source_use_policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    allow_provisional: bool = False
    allow_uncalibrated_what_if: bool = False
    allowed_issue_codes: tuple[str, ...] = ()
    allowed_missing_evidence: tuple[str, ...] = ()
    limitations: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def bounded_authorization(self) -> "AutomaticValuationApprovalPolicyV1":
        for value in (self.effective_from, self.expires_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("approval policy timestamps must include a timezone")
        if self.expires_at <= self.effective_from:
            raise ValueError("approval policy requires a nonempty authorization window")
        for values in (self.allowed_issue_codes, self.allowed_missing_evidence):
            if values != tuple(sorted(set(values))) or any(not v for v in values):
                raise ValueError("approval exceptions must be distinct and ordered")
        if len(set(self.callers)) != len(self.callers) or len(set(self.models)) != len(
            self.models
        ):
            raise ValueError("approval grants and model bindings must be distinct")
        if self.allow_uncalibrated_what_if and not self.allow_provisional:
            raise ValueError("uncalibrated what-if authorization requires provisional")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)


def automatic_approval_issues(
    policy: AutomaticValuationApprovalPolicyV1,
    preparation: AutomaticValuationPreparationV1,
    *,
    caller_id: str,
    organization_id: str,
    expected_input_digest: str,
    source_use_policy_digest: str,
    received_at: datetime,
) -> tuple[str, ...]:
    """Policy only; source/release/composer validation belongs to their owners."""
    issues = set()
    if (
        AutomaticCallerGrantV1(caller_id=caller_id, organization_id=organization_id)
        not in policy.callers
    ):
        issues.add("AUTOMATIC_CALLER_NOT_AUTHORIZED")
    if not policy.effective_from <= received_at < policy.expires_at:
        issues.add("AUTOMATIC_APPROVAL_POLICY_NOT_EFFECTIVE")
    if policy.source_use_policy_digest != source_use_policy_digest:
        issues.add("AUTOMATIC_APPROVAL_SOURCE_POLICY_MISMATCH")
    if (
        AutomaticApprovalModelV1(
            model_id=preparation.model_id,
            model_version=preparation.model_version,
            valuation_policy_version=preparation.policy_version,
        )
        not in policy.models
    ):
        issues.add("AUTOMATIC_APPROVAL_MODEL_NOT_AUTHORIZED")
    if set(preparation.issue_codes) - set(policy.allowed_issue_codes):
        issues.add("AUTOMATIC_APPROVAL_UNSUPPORTED_ISSUES")
    if set(preparation.missing_evidence) - set(policy.allowed_missing_evidence):
        issues.add("AUTOMATIC_APPROVAL_UNSUPPORTED_MISSING_EVIDENCE")
    value = preparation.input
    if preparation.status != "prepared" or value is None:
        issues.add("AUTOMATIC_APPROVAL_INPUT_NOT_PREPARED")
        return tuple(sorted(issues))
    if value.with_digest().input_digest != expected_input_digest:
        issues.add("AUTOMATIC_APPROVAL_INPUT_DIGEST_MISMATCH")
    if value.caller_approval is not None:
        issues.add("AUTOMATIC_APPROVAL_PREEXISTING_DECISION")
    if value.valuation_context.valuation_timestamp > received_at:
        issues.add("AUTOMATIC_APPROVAL_FUTURE_VALUATION")
    if not value.valuation_context.data_release_manifest_digest:
        issues.add("AUTOMATIC_APPROVAL_RELEASE_REQUIRED")
    if preparation.quality_status.value not in (
        ("verified", "provisional") if policy.allow_provisional else ("verified",)
    ):
        issues.add("AUTOMATIC_APPROVAL_QUALITY_NOT_AUTHORIZED")
    if any(item.method == "manual" for item in preparation.assumptions_evidence):
        issues.add("AUTOMATIC_APPROVAL_MANUAL_OVERRIDE_NOT_SUPPORTED")
    conditional = (
        preparation.conditional_capital is not None
        or preparation.conditional_operating is not None
    )
    if conditional and (
        not policy.allow_uncalibrated_what_if
        or value.uncertainty.mode != "scenarios"
        or preparation.quality_status.value != "provisional"
    ):
        issues.add("AUTOMATIC_APPROVAL_WHAT_IF_NOT_AUTHORIZED")
    if value.uncertainty.mode not in {"none", "scenarios"}:
        issues.add("AUTOMATIC_APPROVAL_UNCERTAINTY_NOT_SUPPORTED")
    return tuple(sorted(issues))
