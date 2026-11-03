"""Versioned model eligibility and explicit assumption policy resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import (
    AssumptionsV1,
    EligibilityReportV1,
    ForecastAssumptionsV1,
    PolicyResolutionV1,
    QualityInputV1,
    QualityStatus,
    TraceV1,
    ValuationInputV1,
    WaccAssumptionsV1,
)
from .serialization import sha256_digest


class ModelSpecV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["fundamental.v1"]
    model_id: Literal["fcff_dcf", "transition_fcff_dcf"]
    model_version: str = Field(min_length=1)
    profile_id: Literal["us-gaap-public-v1"]
    required_fields: tuple[str, ...] = Field(min_length=1)
    forbidden_conditions: tuple[str, ...] = ()
    acceptable_ranges: dict[str, tuple[Decimal | None, Decimal | None]] = {}
    minimum_quality: tuple[QualityStatus, ...] = (QualityStatus.VERIFIED,)
    supported_archetypes: tuple[str, ...] = Field(min_length=1)
    abstention_reasons: tuple[str, ...] = ()
    owner: str = Field(min_length=1)
    validator: str = Field(min_length=1)
    lifecycle: Literal["active", "exploratory", "retired"]


class PolicyRecordV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["fundamental.v1"]
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    profile_id: Literal["us-gaap-public-v1"]
    model_id: Literal["fcff_dcf", "transition_fcff_dcf"]
    assumptions: AssumptionsV1
    source_refs: tuple[str, ...] = Field(min_length=1)
    effective_at: datetime
    status: Literal["active", "retired"]
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def digest_matches(self) -> "PolicyRecordV1":
        payload = self.model_dump(exclude={"policy_digest"})
        if self.policy_digest != sha256_digest(payload):
            raise ValueError("policy_digest does not match policy content")
        return self


class PolicyRegistry:
    def __init__(
        self,
        models: Iterable[ModelSpecV1] = (),
        policies: Iterable[PolicyRecordV1] = (),
    ) -> None:
        self._models = {(item.model_id, item.model_version): item for item in models}
        self._policies = {item.policy_id: item for item in policies}

    def model(self, model_id: str, model_version: str) -> ModelSpecV1 | None:
        return self._models.get((model_id, model_version))

    def policy(self, policy_id: str) -> PolicyRecordV1 | None:
        return self._policies.get(policy_id)

    def add_policy(self, policy: PolicyRecordV1) -> None:
        if (
            policy.policy_id in self._policies
            and self._policies[policy.policy_id] != policy
        ):
            raise ValueError("policy versions are immutable")
        self._policies[policy.policy_id] = policy


@dataclass(frozen=True)
class EligibilityResult:
    report: EligibilityReportV1
    policy: PolicyRecordV1 | None = None


def resolve_policy(
    *,
    request: ValuationInputV1,
    policy: PolicyRecordV1,
) -> tuple[ValuationInputV1, PolicyResolutionV1]:
    if policy.model_id != request.model_id:
        raise ValueError("policy model_id does not match request")
    caller = request.assumptions.model_dump()
    defaults = policy.assumptions.model_dump()
    resolved: dict[str, object] = {}
    precedence: dict[str, Literal["caller", "policy"]] = {}
    for group, values in defaults.items():
        if not isinstance(values, dict):
            key = f"assumptions.{group}"
            resolved[key] = (
                caller.get(group) if caller.get(group) is not None else values
            )
            precedence[key] = "caller" if caller.get(group) is not None else "policy"
            continue
        for field, value in values.items():
            key = f"assumptions.{group}.{field}"
            supplied = (
                caller.get(group, {}).get(field)
                if isinstance(caller.get(group), dict)
                else None
            )
            if supplied is None:
                resolved[key] = value
                precedence[key] = "policy"
            else:
                resolved[key] = supplied
                precedence[key] = "caller"
    resolved_assumptions = AssumptionsV1(
        forecast=ForecastAssumptionsV1(
            **{**defaults["forecast"], **caller["forecast"]}
        ),
        wacc=WaccAssumptionsV1(**{**defaults["wacc"], **caller["wacc"]}),
        terminal_growth=(
            caller["terminal_growth"]
            if caller.get("terminal_growth") is not None
            else defaults["terminal_growth"]
        ),
        capital_bridge=policy.assumptions.capital_bridge.model_copy(
            update=caller.get("capital_bridge", {})
        ),
        trace=TraceV1(
            description=f"policy {policy.policy_id}; caller values take precedence"
        ),
    )
    resolved_input = request.model_copy(
        update={"assumptions": resolved_assumptions, "policy_id": policy.policy_id}
    )
    resolved_input = resolved_input.with_digest()
    resolution = PolicyResolutionV1(
        contract_version="fundamental.v1",
        policy_id=policy.policy_id,
        resolved_fields={key: value for key, value in resolved.items()},
        precedence=precedence,
        input_digest=resolved_input.input_digest,
    )
    return resolved_input, resolution


def evaluate_eligibility(
    *,
    request: ValuationInputV1,
    model: ModelSpecV1,
    available_fields: set[str],
    quality: QualityInputV1,
    policy: PolicyRecordV1 | None = None,
) -> EligibilityResult:
    quality = QualityInputV1.model_validate(quality)
    missing = tuple(
        field for field in model.required_fields if field not in available_fields
    )
    forbidden = tuple(
        condition
        for condition in model.forbidden_conditions
        if condition in available_fields
    )
    issues: list[str] = []
    if request.valuation_context.coverage_profile != model.profile_id:
        issues.append("UNSUPPORTED_PROFILE")
    if missing:
        issues.append("MISSING_REQUIRED_FACT")
    if forbidden:
        issues.append("FORBIDDEN_CONDITION")
    if quality.status not in model.minimum_quality:
        issues.append("INSUFFICIENT_QUALITY")
    if model.lifecycle != "active":
        issues.append("MODEL_NOT_ACTIVE")
    if issues:
        status = (
            QualityStatus.UNSUPPORTED
            if "UNSUPPORTED_PROFILE" in issues
            else QualityStatus.ABSTAIN
        )
        return EligibilityResult(
            EligibilityReportV1(
                contract_version="fundamental.v1",
                status=status,
                selected_model=None,
                candidates=(model.model_id,),
                missing_fields=missing,
                forbidden_conditions=forbidden,
                issue_codes=tuple(issues),
                rationale="; ".join(issues),
            ),
            policy,
        )
    return EligibilityResult(
        EligibilityReportV1(
            contract_version="fundamental.v1",
            status=QualityStatus.VERIFIED,
            selected_model=model.model_id,
            candidates=(model.model_id,),
            rationale="all model applicability and quality gates passed",
        ),
        policy,
    )


def initial_model_specs() -> tuple[ModelSpecV1, ...]:
    common = {
        "contract_version": "fundamental.v1",
        "profile_id": "us-gaap-public-v1",
        "required_fields": (
            "revenue",
            "operating_income",
            "cash",
            "debt",
            "diluted_shares",
        ),
        "supported_archetypes": ("mature_non_financial",),
        "owner": "fundamental-service",
        "validator": "quality-policy-v1",
        "lifecycle": "active",
    }
    return (
        ModelSpecV1(model_id="fcff_dcf", model_version="fcff_dcf-v1", **common),
        ModelSpecV1(
            model_id="transition_fcff_dcf",
            model_version="transition_fcff_dcf-v1",
            required_fields=(*common["required_fields"], "filed_operating_evidence"),
            supported_archetypes=("high_growth_non_financial",),
            **{
                key: value
                for key, value in common.items()
                if key not in {"required_fields", "supported_archetypes"}
            },
        ),
    )
