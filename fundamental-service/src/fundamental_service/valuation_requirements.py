"""Versioned Fundamental Service requirements for released FCFF models."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from pydantic import Field, model_validator

from .contracts import (
    CanonicalFactV1,
    InitialModelId,
    MissingValueV1,
    QualityStatus,
    SourceSnapshotV1,
    StrictModel,
)
from .serialization import sha256_digest
from .equity_award_evidence import AWARD_FACT_FIELDS
from .original_issuer import IssuerOperatingSourceV1, fact_matches_operating_identity
from .working_capital import WORKING_CAPITAL_INPUT_POLICY


class ValuationRequirementsProfileV1(StrictModel):
    """Service-owned evidence roles and history policy for one released model."""

    profile_id: str = Field(min_length=1)
    profile_version: str = Field(min_length=1)
    model_id: InitialModelId
    annual_duration_fields: tuple[str, ...] = Field(min_length=1)
    annual_instant_fields: tuple[str, ...] = Field(min_length=1)
    point_in_time_fact_fields: tuple[str, ...] = ()
    market_policy_input_roles: tuple[str, ...] = ()
    supporting_fact_fields: tuple[str, ...] = ()
    history_window_years: int = Field(default=5, ge=1)
    candidate_minimum_complete_years: int = Field(default=3, ge=1)
    supported_history_threshold: int | None = Field(default=None, ge=1)
    anchor_field: str = Field(default="revenue", min_length=1)
    transition_filing_evidence_required: bool = False

    @model_validator(mode="after")
    def profile_is_coherent(self) -> ValuationRequirementsProfileV1:
        groups = (
            self.annual_duration_fields,
            self.annual_instant_fields,
            self.point_in_time_fact_fields,
            self.market_policy_input_roles,
            self.supporting_fact_fields,
        )
        if any(len(values) != len(set(values)) for values in groups):
            raise ValueError("requirements profile fields must be unique")
        if self.anchor_field not in self.annual_duration_fields:
            raise ValueError("anchor_field must be an annual duration field")
        if self.candidate_minimum_complete_years > self.history_window_years:
            raise ValueError("minimum history cannot exceed the candidate window")
        if (
            self.supported_history_threshold is not None
            and self.supported_history_threshold > self.history_window_years
        ):
            raise ValueError("supported threshold cannot exceed the history window")
        if self.transition_filing_evidence_required != (
            self.model_id == "transition_fcff_dcf"
        ):
            raise ValueError("transition filing evidence must match the selected model")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self.model_dump(mode="json"))

    @property
    def required_fact_fields(self) -> tuple[str, ...]:
        fields = (
            *self.annual_duration_fields,
            *self.annual_instant_fields,
            *self.point_in_time_fact_fields,
        )
        if self.transition_filing_evidence_required:
            fields = (*fields, "filed_operating_evidence")
        return fields


@dataclass(frozen=True)
class ReleasedFactSelectionV1:
    """Profile roles selected from facts already bound to one release."""

    facts: tuple[CanonicalFactV1, ...]
    missing_fields: tuple[str, ...]
    rejected_fact_ids: tuple[str, ...]
    issue_codes: tuple[str, ...]


def select_released_facts(
    facts: Iterable[CanonicalFactV1],
    *,
    profile: ValuationRequirementsProfileV1,
    snapshot: SourceSnapshotV1 | IssuerOperatingSourceV1,
    valuation_timestamp: datetime,
    additional_fact_ids: tuple[str, ...] = (),
) -> ReleasedFactSelectionV1:
    """Select every eligible candidate for the profile without caller mappings."""

    require_operating_source_profile(snapshot, profile)
    source_hashes = {record.content_hash for record in snapshot.source_records}
    required_fields = profile.required_fact_fields
    selected: list[CanonicalFactV1] = []
    rejected: list[str] = []
    for fact in facts:
        if (
            (
                fact.normalized_field
                not in (*required_fields, *profile.supporting_fact_fields)
                and fact.fact_id not in additional_fact_ids
            )
            or not fact_matches_operating_identity(fact, snapshot)
            or fact.source.content_hash not in source_hashes
            or fact.available_at > valuation_timestamp
            or next(
                (
                    source.available_at > valuation_timestamp
                    for source in snapshot.source_records
                    if source.content_hash == fact.source.content_hash
                ),
                False,
            )
            or fact.quality is not QualityStatus.VERIFIED
            or (
                not isinstance(fact.value, Decimal)
                and not (
                    fact.normalized_field == "filed_operating_evidence"
                    and not isinstance(fact.value, MissingValueV1)
                )
            )
        ):
            rejected.append(fact.fact_id)
            continue
        selected.append(fact)

    selected_fields = {fact.normalized_field for fact in selected}
    missing = tuple(sorted(set(required_fields) - selected_fields))
    issue_codes = []
    if missing:
        issue_codes.append("VALUATION_REQUIRED_FACTS_MISSING")
    if rejected:
        issue_codes.append("VALUATION_FACT_CANDIDATES_REJECTED")
    return ReleasedFactSelectionV1(
        facts=tuple(sorted(selected, key=lambda fact: fact.fact_id)),
        missing_fields=missing,
        rejected_fact_ids=tuple(sorted(rejected)),
        issue_codes=tuple(issue_codes),
    )


def require_operating_source_profile(
    snapshot: SourceSnapshotV1 | IssuerOperatingSourceV1,
    profile: ValuationRequirementsProfileV1,
) -> None:
    if isinstance(snapshot, IssuerOperatingSourceV1) and profile not in (
        operating_forecast_requirements_profile(profile.model_id),
        composite_working_capital_requirements_profile(profile.model_id),
    ):
        raise ValueError("issuer-only evidence requires the exact operating profile")


_ANNUAL_DURATION_FIELDS = (
    "revenue",
    "cost_of_revenue",
    "operating_income",
    "income_before_tax",
    "income_tax_expense",
    "net_income",
    "depreciation_and_amortization",
    "capital_expenditure",
    "operating_lease_cost",
    "finance_lease_cost",
    "stock_based_compensation",
    "basic_weighted_average_shares",
    "diluted_weighted_average_shares",
)

_ANNUAL_INSTANT_FIELDS = (
    "operating_current_receivables",
    "inventory",
    "contract_assets",
    "operating_current_payables",
    "accrued_operating_liabilities",
    "deferred_revenue",
)

_POINT_IN_TIME_FACT_FIELDS = (
    "cash_and_equivalents",
    "non_operating_assets",
    "current_interest_bearing_debt",
    "long_term_interest_bearing_debt",
    "current_operating_lease_liabilities",
    "long_term_operating_lease_liabilities",
    "current_finance_lease_liabilities",
    "long_term_finance_lease_liabilities",
    "preferred_claims",
    "noncontrolling_interests",
    "convertible_instruments",
    "common_shares_outstanding",
    "other_share_classes",
)

_MARKET_POLICY_INPUT_ROLES = (
    "risk_free_rate",
    "industry_beta",
    "equity_risk_premium",
    "marginal_cost_of_debt",
    "market_capitalization",
    "normalized_marginal_tax_rate",
    "terminal_growth",
)

_PROFILES = {
    "fcff_dcf": ValuationRequirementsProfileV1(
        profile_id="fcff-valuation-requirements-v3",
        profile_version="fcff-valuation-requirements-v3",
        model_id="fcff_dcf",
        annual_duration_fields=_ANNUAL_DURATION_FIELDS,
        annual_instant_fields=_ANNUAL_INSTANT_FIELDS,
        point_in_time_fact_fields=_POINT_IN_TIME_FACT_FIELDS,
        market_policy_input_roles=_MARKET_POLICY_INPUT_ROLES,
        supporting_fact_fields=AWARD_FACT_FIELDS,
    ),
    "transition_fcff_dcf": ValuationRequirementsProfileV1(
        profile_id="transition-fcff-valuation-requirements-v3",
        profile_version="transition-fcff-valuation-requirements-v3",
        model_id="transition_fcff_dcf",
        annual_duration_fields=_ANNUAL_DURATION_FIELDS,
        annual_instant_fields=_ANNUAL_INSTANT_FIELDS,
        point_in_time_fact_fields=_POINT_IN_TIME_FACT_FIELDS,
        market_policy_input_roles=_MARKET_POLICY_INPUT_ROLES,
        supporting_fact_fields=AWARD_FACT_FIELDS,
        transition_filing_evidence_required=True,
    ),
}


class UnsupportedValuationModel(ValueError):
    """Raised when a model has no released Fundamental requirements profile."""


def valuation_requirements_profile(
    model_id: str,
) -> ValuationRequirementsProfileV1:
    try:
        return _PROFILES[model_id]
    except KeyError as error:
        raise UnsupportedValuationModel(
            f"no valuation requirements profile is released for {model_id}"
        ) from error


def operating_forecast_requirements_profile(
    model_id: str,
) -> ValuationRequirementsProfileV1:
    """Evidence dependencies of operating targets, without valuation claims."""

    valuation = valuation_requirements_profile(model_id)
    return ValuationRequirementsProfileV1(
        profile_id=f"{model_id}-operating-forecast-requirements-v1",
        profile_version="operating-forecast-requirements-v1",
        model_id=valuation.model_id,
        annual_duration_fields=(
            "revenue",
            "operating_income",
            "income_before_tax",
            "income_tax_expense",
            "capital_expenditure",
            "depreciation_and_amortization",
        ),
        annual_instant_fields=valuation.annual_instant_fields,
        history_window_years=valuation.history_window_years,
        candidate_minimum_complete_years=valuation.candidate_minimum_complete_years,
        transition_filing_evidence_required=valuation.transition_filing_evidence_required,
    )


def composite_working_capital_requirements_profile(
    model_id: str,
    *,
    operating_only: bool = True,
) -> ValuationRequirementsProfileV1:
    """Explicit alternate input policy; never reinterpret an existing release."""

    exact = (
        operating_forecast_requirements_profile(model_id)
        if operating_only
        else valuation_requirements_profile(model_id)
    )
    return ValuationRequirementsProfileV1.model_validate(
        {
            **exact.model_dump(),
            "profile_id": f"{exact.profile_id}-{WORKING_CAPITAL_INPUT_POLICY}",
            "profile_version": WORKING_CAPITAL_INPUT_POLICY,
            "annual_instant_fields": ("current_assets", "current_liabilities"),
        }
    )


__all__ = [
    "ReleasedFactSelectionV1",
    "UnsupportedValuationModel",
    "ValuationRequirementsProfileV1",
    "operating_forecast_requirements_profile",
    "composite_working_capital_requirements_profile",
    "select_released_facts",
    "valuation_requirements_profile",
]
