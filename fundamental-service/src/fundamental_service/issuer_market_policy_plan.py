"""Build an issuer/date reference plan from interchangeable source mappings.

This module owns classification-to-subject joins. It does not read source bytes,
approve a provider, or calculate valuation inputs. Source admission and the
existing reference selectors remain the owners of those responsibilities.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .classification_crosswalk import IndustryCrosswalkEvidenceV1
from .issuer_classification import IssuerClassificationEvidenceV1
from .issuer_country_crosswalk import IssuerCountryCrosswalkEvidenceV1
from .market_reference import ReferenceMetric
from .market_reference_selection import (
    IssuerMarketReferencePlanV1,
    MarketReferenceSelectionPolicyV1,
)
from .serialization import sha256_digest
from .snapshots import SnapshotError

DEFAULT_ISSUER_REFERENCE_PLAN_POLICY = "issuer-reference-plan-v1"
DEFAULT_INDUSTRY_CAPITAL_POLICY = "usd-industry-capital-proxy-v1"
DEFAULT_COUNTRY_METRICS: tuple[ReferenceMetric, ...] = ("country.equity_risk_premium",)
DEFAULT_INDUSTRY_METRICS: tuple[ReferenceMetric, ...] = (
    "industry.equity_beta",
    "industry.pre_tax_cost_of_debt",
    "industry.debt_weight",
    "industry.equity_weight",
)


class IssuerMarketReferencePlanPolicyV1(BaseModel):
    """Versioned join policy with no concrete source-provider names."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: str = Field(
        default=DEFAULT_ISSUER_REFERENCE_PLAN_POLICY, min_length=1
    )
    maximum_age_days: int = Field(default=730, ge=0)
    country_metrics: tuple[ReferenceMetric, ...] = DEFAULT_COUNTRY_METRICS
    industry_metrics: tuple[ReferenceMetric, ...] = DEFAULT_INDUSTRY_METRICS
    industry_capital_policy: Literal["usd-industry-capital-proxy-v1"] = (
        DEFAULT_INDUSTRY_CAPITAL_POLICY
    )

    @field_validator("country_metrics", "industry_metrics")
    @classmethod
    def unique_metrics(
        cls, value: tuple[ReferenceMetric, ...]
    ) -> tuple[ReferenceMetric, ...]:
        if not value or len(set(value)) != len(value):
            raise ValueError(
                "issuer reference policy metrics must be unique and nonempty"
            )
        return tuple(sorted(value))

    @model_validator(mode="after")
    def metric_kinds_match(self) -> IssuerMarketReferencePlanPolicyV1:
        if any(not metric.startswith("country.") for metric in self.country_metrics):
            raise ValueError("country metrics must use country reference metrics")
        if any(not metric.startswith("industry.") for metric in self.industry_metrics):
            raise ValueError("industry metrics must use industry reference metrics")
        return self


class IssuerMarketReferencePlanDecisionV1(BaseModel):
    """A deterministic plan or a complete retained refusal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["issuer-market-reference-plan-v1"] = (
        "issuer-market-reference-plan-v1"
    )
    policy: IssuerMarketReferencePlanPolicyV1
    issuer_id: str = Field(min_length=1)
    valuation_at: datetime
    classification_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    country_mapping_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    industry_mapping_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["planned", "refused"]
    issue_codes: tuple[str, ...]
    plan: IssuerMarketReferencePlanV1 | None = None
    output_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("valuation_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("issuer reference planning requires a valuation timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def canonical_decision(self) -> IssuerMarketReferencePlanDecisionV1:
        if self.issue_codes != tuple(sorted(set(self.issue_codes))):
            raise ValueError("issuer reference plan issues are not canonical")
        if self.status == "planned" and (self.issue_codes or self.plan is None):
            raise ValueError(
                "planned reference result must contain a plan without issues"
            )
        if self.status == "refused" and self.plan is not None:
            raise ValueError("refused reference result cannot contain a plan")
        if self.input_digest != sha256_digest(
            {
                "policy": self.policy,
                "issuer_id": self.issuer_id,
                "valuation_at": self.valuation_at,
                "classification_digest": self.classification_digest,
                "country_mapping_digest": self.country_mapping_digest,
                "industry_mapping_digest": self.industry_mapping_digest,
            }
        ):
            raise ValueError("issuer reference plan input digest differs from its pins")
        if self.output_digest != sha256_digest(
            self.model_dump(exclude={"output_digest"})
        ):
            raise ValueError("issuer reference plan output digest differs from content")
        return self


def build_issuer_market_reference_plan(
    classification: IssuerClassificationEvidenceV1,
    *,
    country_mapping: IssuerCountryCrosswalkEvidenceV1,
    industry_mapping: IndustryCrosswalkEvidenceV1,
    policy: IssuerMarketReferencePlanPolicyV1,
    policy_id: str,
    expected: IssuerMarketReferencePlanDecisionV1 | None = None,
) -> IssuerMarketReferencePlanDecisionV1:
    """Join exact SEC classifications to reference subjects without guessing."""

    classification = IssuerClassificationEvidenceV1.model_validate_json(
        classification.model_dump_json()
    )
    country_mapping = IssuerCountryCrosswalkEvidenceV1.model_validate_json(
        country_mapping.model_dump_json()
    )
    industry_mapping = IndustryCrosswalkEvidenceV1.model_validate_json(
        industry_mapping.model_dump_json()
    )
    policy = IssuerMarketReferencePlanPolicyV1.model_validate_json(
        policy.model_dump_json()
    )
    request = classification.request
    input_payload = {
        "policy": policy,
        "issuer_id": request.issuer_id,
        "valuation_at": request.valuation_at,
        "classification_digest": classification.output_digest,
        "country_mapping_digest": country_mapping.output_digest,
        "industry_mapping_digest": industry_mapping.output_digest,
    }
    input_digest = sha256_digest(input_payload)
    issues = set(classification.issue_codes)
    if classification.status != "matched":
        issues.add("ISSUER_CLASSIFICATION_NOT_MATCHED")

    if country_mapping.issuer_id != request.issuer_id:
        issues.add("ISSUER_COUNTRY_CROSSWALK_ISSUER_MISMATCH")
    if country_mapping.accession_number != request.accession_number:
        issues.add("ISSUER_COUNTRY_CROSSWALK_ACCESSION_MISMATCH")
    if country_mapping.classification_digest != classification.output_digest:
        issues.add("ISSUER_COUNTRY_CROSSWALK_CLASSIFICATION_MISMATCH")
    if country_mapping.status != "mapped":
        issues.update(country_mapping.issue_codes)
        issues.add("ISSUER_COUNTRY_CROSSWALK_REFUSED")

    if industry_mapping.issuer_id != request.issuer_id:
        issues.add("ISSUER_INDUSTRY_CROSSWALK_ISSUER_MISMATCH")
    if industry_mapping.accession_number != request.accession_number:
        issues.add("ISSUER_INDUSTRY_CROSSWALK_ACCESSION_MISMATCH")
    if industry_mapping.classification_digest != classification.output_digest:
        issues.add("ISSUER_INDUSTRY_CROSSWALK_CLASSIFICATION_MISMATCH")
    if industry_mapping.status != "mapped":
        issues.update(industry_mapping.issue_codes)
        issues.add("ISSUER_INDUSTRY_CROSSWALK_REFUSED")

    if not issues:
        assert country_mapping.target_subject is not None
        assert country_mapping.target_population is not None
        assert industry_mapping.target_subject is not None
        assert industry_mapping.target_population is not None
        selections = tuple(
            MarketReferenceSelectionPolicyV1(
                policy_version=policy.policy_version,
                metric=metric,
                population=country_mapping.target_population,
                subject_kind="country",
                subject=country_mapping.target_subject,
                maximum_age_days=policy.maximum_age_days,
            )
            for metric in policy.country_metrics
        ) + tuple(
            MarketReferenceSelectionPolicyV1(
                policy_version=policy.policy_version,
                metric=metric,
                population=industry_mapping.target_population,
                subject_kind="industry",
                subject=industry_mapping.target_subject,
                maximum_age_days=policy.maximum_age_days,
            )
            for metric in policy.industry_metrics
        )
        plan = IssuerMarketReferencePlanV1(
            issuer_id=request.issuer_id,
            policy_id=policy_id,
            valuation_at=request.valuation_at,
            industry_capital_policy=policy.industry_capital_policy,
            selections=selections,
        )
    else:
        plan = None

    payload = {
        "protocol": "issuer-market-reference-plan-v1",
        **input_payload,
        "input_digest": input_digest,
        "status": "refused" if issues else "planned",
        "issue_codes": tuple(sorted(issues)),
        "plan": plan,
    }
    result = IssuerMarketReferencePlanDecisionV1.model_validate(
        {**payload, "output_digest": sha256_digest(payload)}
    )
    if expected is not None and result != expected:
        raise SnapshotError(
            "ISSUER_MARKET_REFERENCE_PLAN_REPLAY_MISMATCH",
            "issuer market reference plan differs from retained replay",
        )
    return result
