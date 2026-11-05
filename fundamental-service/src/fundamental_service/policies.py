"""Versioned model eligibility and explicit assumption policy resolution."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import (
    AssumptionsV1,
    EligibilityReportV1,
    ForecastAssumptionsV1,
    InitialModelId,
    ModelId,
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
    model_id: ModelId
    schema_version: Literal["ModelSpecV1"] = "ModelSpecV1"
    model_version: str = Field(min_length=1)
    profile_id: str = Field(min_length=1)
    required_fields: tuple[str, ...] = Field(min_length=1)
    forbidden_conditions: tuple[str, ...] = ()
    acceptable_ranges: dict[str, tuple[Decimal | None, Decimal | None]] = {}
    minimum_quality: tuple[QualityStatus, ...] = (QualityStatus.VERIFIED,)
    supported_archetypes: tuple[str, ...] = Field(min_length=1)
    abstention_reasons: tuple[str, ...] = ()
    owner: str = Field(min_length=1)
    validator: str = Field(min_length=1)
    lifecycle: Literal["active", "exploratory", "retired"]
    economic_purpose: str = Field(min_length=1)
    valuation_basis: Literal["enterprise", "equity", "asset"]
    jurisdictions: tuple[str, ...] = Field(min_length=1)
    accounting_bases: tuple[str, ...] = Field(min_length=1)
    required_evidence: tuple[str, ...] = Field(min_length=1)
    assumption_policy: str = Field(min_length=1)
    formula_graph: str = Field(min_length=1)
    numerical_policy: str = Field(min_length=1)
    eligibility_policy: str = Field(min_length=1)
    abstention_policy: str = Field(min_length=1)
    uncertainty_policy: str = Field(min_length=1)
    calibration_policy: str = Field(min_length=1)
    calibration_targets: tuple[str, ...] = Field(min_length=1)
    calibration_required_for_promotion: bool = True
    required_release_gates: tuple[str, ...] = Field(min_length=1)
    source_register: tuple[str, ...] = Field(min_length=1)
    capital_bridge_policy: str = Field(min_length=1)
    golden_cohort: str = Field(min_length=1)
    challenger: str = Field(min_length=1)
    independent_validator: str = Field(min_length=1)
    approval_date: datetime | None = None
    review_date: datetime | None = None
    retirement_trigger: str = Field(min_length=1)
    rollback_policy: str = Field(min_length=1)
    monitoring_policy: str = Field(min_length=1)
    release_manifest: str | None = None

    @model_validator(mode="after")
    def governed_release(self) -> "ModelSpecV1":
        if self.lifecycle == "active":
            required = {
                "approval_date": self.approval_date,
                "review_date": self.review_date,
                "release_manifest": self.release_manifest,
            }
            missing = tuple(name for name, value in required.items() if value is None)
            if missing:
                raise ValueError(
                    "active model requires approval, review, and release manifest: "
                    + ", ".join(missing)
                )
        if self.lifecycle != "active" and self.release_manifest is not None:
            raise ValueError("unreleased model cannot carry a release manifest")
        if self.owner == self.independent_validator:
            raise ValueError("model owner cannot independently validate its release")
        for name, value in (
            ("approval_date", self.approval_date),
            ("review_date", self.review_date),
        ):
            if value is not None and (
                value.tzinfo is None or value.utcoffset() is None
            ):
                raise ValueError(f"{name} must include a timezone")
        if (
            self.approval_date is not None
            and self.review_date is not None
            and self.review_date <= self.approval_date
        ):
            raise ValueError("review_date must follow approval_date")
        return self


class PolicyRecordV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["fundamental.v1"]
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    profile_id: Literal["us-gaap-public-v1"]
    model_id: InitialModelId
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

    def add_model(self, model: ModelSpecV1) -> None:
        key = (model.model_id, model.model_version)
        if key in self._models and self._models[key] != model:
            raise ValueError("model versions are immutable")
        self._models[key] = model

    def models(self) -> tuple[ModelSpecV1, ...]:
        return tuple(self._models.values())


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
    if request.model_id not in {"fcff_dcf", "transition_fcff_dcf"}:
        raise ValueError("policy resolution is not released for this model family")
    if any(
        defaults.get(group) is None
        for group in ("forecast", "wacc", "capital_bridge", "trace")
    ):
        raise ValueError("policy does not contain a complete FCFF assumption set")
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
        resolved_fields=dict(resolved),
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
        if condition in quality.issue_codes
    )
    issues: list[str] = []
    if request.valuation_context.coverage_profile != model.profile_id:
        issues.append("UNSUPPORTED_PROFILE")
    if request.model_id != model.model_id:
        issues.append("MODEL_MISMATCH")
    if missing:
        issues.append("MISSING_REQUIRED_FACT")
    if forbidden:
        issues.append("FORBIDDEN_CONDITION")
    if quality.status not in model.minimum_quality:
        issues.append("INSUFFICIENT_QUALITY")
    if model.lifecycle != "active":
        issues.append("MODEL_NOT_ACTIVE")
    if model.release_manifest is None:
        issues.append("MODEL_RELEASE_EVIDENCE_MISSING")
    if issues:
        unsupported_issues = {
            "UNSUPPORTED_PROFILE",
            "MODEL_NOT_ACTIVE",
            "MODEL_RELEASE_EVIDENCE_MISSING",
        }
        status = (
            QualityStatus.UNSUPPORTED
            if set(issues) & unsupported_issues
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
        "economic_purpose": "value mature non-financial operating cash flows",
        "valuation_basis": "enterprise",
        "jurisdictions": ("US",),
        "accounting_bases": ("us-gaap",),
        "required_evidence": ("issuer-filings", "capital-bridge", "golden-cohort"),
        "assumption_policy": "policy-v1-explicit-caller-assumptions",
        "formula_graph": "calculator-v1-fcff",
        "numerical_policy": "decimal-50-end-of-year-v1",
        "eligibility_policy": "quality-policy-v1",
        "abstention_policy": "abstain-on-missing-or-unverified-evidence-v1",
        "uncertainty_policy": "caller-owned-explicit-controls-v1",
        "calibration_policy": "calibration-inactive-unless-oos-promoted-v1",
        "calibration_targets": ("first-subsequent-reported-revenue-v1",),
        "calibration_required_for_promotion": True,
        "required_release_gates": (
            "public-source-coverage",
            "point-in-time-accounting",
            "positive-negative-golden-cohorts",
            "independent-node-challenger",
            "calibration-oos",
            "replay-reproducibility",
        ),
        "source_register": ("sec-companyfacts", "sec-filing", "treasury-yields"),
        "capital_bridge_policy": (
            "enterprise-value-plus-cash-minus-debt-and-dilution-v1"
        ),
        "golden_cohort": "fundamental-engineering-cohort-v1",
        "challenger": "independent-verification-v1",
        "independent_validator": "fundamental-service-validator",
        "approval_date": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "review_date": datetime(2026, 12, 31, tzinfo=timezone.utc),
        "release_manifest": "release-fundamental-v1",
        "retirement_trigger": "blocking-reconciliation-or-expired-review",
        "rollback_policy": "restore-last-promoted-release-manifest",
        "monitoring_policy": (
            "monthly-source-health-drift-missingness-and-abstention-v1"
        ),
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


def expansion_model_specs() -> tuple[ModelSpecV1, ...]:
    """Governed inventory for post-cutover families.

    These records make coverage and ownership auditable while keeping every
    family explicitly unsupported until its evidence and release gates pass.
    """

    families = (
        {
            "model_id": "bank_excess_return",
            "archetype": "U.S. bank holding company or depository institution",
            "basis": "equity",
            "profile_id": "us-gaap-public-v1",
            "required_fields": (
                "bank_current_book_value",
                "bank_tangible_book_value",
                "bank_reported_rwa",
                "bank_cet1_capital",
                "bank_diluted_shares",
                "bank_regulatory_entity_relationship",
            ),
            "forbidden_conditions": (
                "BANK_REGULATORY_ENTITY_UNMAPPED",
                "BANK_REGULATORY_SCOPE_MISMATCH",
                "BANK_CET1_RECONCILIATION_FAILED",
                "BANK_REGULATORY_SOURCE_STALE",
            ),
            "sources": (
                "sec-companyfacts",
                "sec-filing",
                "fdic-bankfind",
                "ffiec-cdr",
            ),
            "evidence": (
                "issuer SEC filings and point-in-time company facts",
                "reported CET1 capital and risk-weighted assets at matched entity "
                "scope",
                "FDIC certificate or FFIEC RSSD crosswalk with dated ownership "
                "evidence",
                "positive and negative bank golden cohorts",
                "independent residual-income node report",
            ),
            "assumption_policy": (
                "caller supplies each forecast net income, RWA growth, cost of equity, "
                "payout, terminal growth, CET1 floor, and share count; no defaults"
            ),
            "formula_graph": "bank-excess-return-v1",
            "uncertainty_policy": (
                "caller specifies bounded forecast-income and RWA-growth "
                "distributions; "
                "reject invalid draws according to the request"
            ),
            "calibration_targets": (
                "next-reported-bank-net-income-v1",
                "next-reported-bank-risk-weighted-assets-v1",
            ),
            "capital_bridge_policy": (
                "reported-tangible-book-plus-discounted-residual-income-with-"
                "cet1-rwa-guard-v1"
            ),
            "valuation_basis": "equity",
            "economic_purpose": (
                "value a regulated banking issuer from tangible book and residual "
                "income"
            ),
        },
        {
            "model_id": "insurance_statutory_excess_return",
            "archetype": "U.S. insurance issuer",
            "basis": "equity",
            "profile_id": "us-gaap-public-v1",
            "required_fields": (
                "insurance_statutory_surplus",
                "insurance_rbc_ratio",
                "insurance_premiums_earned",
                "insurance_reserve_development",
                "insurance_diluted_shares",
            ),
            "forbidden_conditions": (
                "INSURANCE_STATUTORY_SCOPE_UNAVAILABLE",
                "INSURANCE_RBC_BASIS_UNVERIFIED",
                "INSURANCE_RESERVE_DEVELOPMENT_ADVERSE",
            ),
            "sources": ("sec-filing", "naic-statutory-filings"),
            "evidence": (
                "issuer filings and applicable jurisdiction statutory statements",
                "RBC formula and authorized-control-level basis by legal entity",
                "positive and negative insurer cohorts",
                "independent reserve and surplus reconciliation",
            ),
            "assumption_policy": (
                "caller supplies premium growth, loss and expense ratios, capital "
                "retention, cost of equity, and terminal growth"
            ),
            "formula_graph": "insurance-statutory-excess-return-v1",
            "uncertainty_policy": (
                "caller supplies bounded premium, loss-ratio, and reserve-"
                "development distributions"
            ),
            "calibration_targets": (
                "first-subsequent-statutory-premium-and-loss-ratio-v1",
            ),
            "capital_bridge_policy": "statutory-surplus-to-common-equity-v1",
            "valuation_basis": "equity",
            "economic_purpose": (
                "value insurer equity subject to statutory solvency constraints"
            ),
        },
        {
            "model_id": "reit_nav",
            "archetype": "U.S. equity REIT",
            "basis": "asset",
            "profile_id": "us-gaap-public-v1",
            "required_fields": (
                "reit_property_value_by_asset",
                "reit_debt_by_entity",
                "reit_lease_obligations",
                "reit_occupancy",
                "reit_maintenance_capex",
                "reit_diluted_shares",
            ),
            "forbidden_conditions": (
                "REIT_AFFO_UNRECONCILED",
                "REIT_PROPERTY_COVERAGE_INCOMPLETE",
                "REIT_LEASE_SCOPE_MISMATCH",
            ),
            "sources": ("sec-filing", "nareit-definitions"),
            "evidence": (
                "issuer property schedule, lease obligations, and debt maturities",
                "property-level valuation method and dated cap-rate evidence",
                "positive and negative REIT NAV cohorts",
                "independent property, debt, and share-count bridge",
            ),
            "assumption_policy": (
                "caller supplies asset-level NOI, discount or cap rates, "
                "disposition costs, "
                "and diluted shares"
            ),
            "formula_graph": "reit-asset-nav-v1",
            "uncertainty_policy": (
                "caller supplies bounded NOI, cap-rate, and occupancy distributions"
            ),
            "calibration_targets": ("first-subsequent-property-noi-and-occupancy-v1",),
            "capital_bridge_policy": (
                "property-nav-minus-debt-leases-and-other-claims-v1"
            ),
            "valuation_basis": "asset",
            "economic_purpose": (
                "value REIT common equity from property and liability NAV"
            ),
        },
        {
            "model_id": "regulated_utility",
            "archetype": "U.S. regulated electric or gas utility",
            "basis": "enterprise",
            "profile_id": "us-gaap-public-v1",
            "required_fields": (
                "utility_jurisdictional_rate_base",
                "utility_allowed_return",
                "utility_recovery_schedule",
                "utility_parent_debt",
                "utility_diluted_shares",
            ),
            "forbidden_conditions": (
                "UTILITY_RATE_ORDER_MISSING",
                "UTILITY_RECOVERY_DISALLOWED",
                "UTILITY_JURISDICTION_MIXED",
            ),
            "sources": ("sec-filing", "ferc-public-data"),
            "evidence": (
                "issuer filings and applicable FERC forms",
                "effective state commission rate orders and recovery timing",
                "positive and negative utility cohorts by jurisdiction",
                "independent rate-base and capital-structure bridge",
            ),
            "assumption_policy": (
                "caller specifies jurisdiction-specific rate base additions, "
                "allowed returns, "
                "recovery timing, and financing assumptions"
            ),
            "formula_graph": "jurisdictional-rate-base-discounted-cash-flow-v1",
            "uncertainty_policy": (
                "caller supplies bounded rate-base, recovery, and allowed-return "
                "distributions"
            ),
            "calibration_targets": (
                "first-subsequent-rate-base-and-allowed-return-v1",
            ),
            "capital_bridge_policy": (
                "jurisdictional-enterprise-cash-flow-to-parent-equity-v1"
            ),
            "valuation_basis": "enterprise",
            "economic_purpose": (
                "value utility cash flows under jurisdiction-specific rate regulation"
            ),
        },
        {
            "model_id": "normalized_cyclical",
            "archetype": "U.S. commodity-exposed cyclical issuer",
            "basis": "enterprise",
            "profile_id": "us-gaap-public-v1",
            "required_fields": (
                "cyclical_realized_price",
                "cyclical_production_volume",
                "cyclical_unit_cost",
                "cyclical_capacity_utilization",
                "cyclical_net_debt",
                "cyclical_diluted_shares",
            ),
            "forbidden_conditions": (
                "CYCLICAL_THROUGH_CYCLE_SERIES_INCOMPLETE",
                "CYCLICAL_COMMODITY_BASIS_MISMATCH",
                "CYCLICAL_CAPACITY_NOT_RECONCILED",
            ),
            "sources": (
                "sec-filing",
                "eia-open-data",
                "usgs-commodity-statistics",
                "usda-nass-quickstats",
            ),
            "evidence": (
                "issuer realized prices, volume, cost, and utilization from filings",
                "public commodity series mapped to the issuer's product and geography",
                "positive and negative through-cycle cohorts",
                "independent normalized margin and net-debt bridge",
            ),
            "assumption_policy": (
                "caller specifies cycle length, normalized price, volume, and "
                "unit-cost path"
            ),
            "formula_graph": "through-cycle-normalized-fcff-v1",
            "uncertainty_policy": (
                "caller supplies bounded commodity-price, volume, and unit-cost "
                "distributions"
            ),
            "calibration_targets": (
                "first-subsequent-realized-price-volume-and-cost-v1",
            ),
            "capital_bridge_policy": (
                "normalized-enterprise-value-minus-net-debt-and-dilution-v1"
            ),
            "valuation_basis": "enterprise",
            "economic_purpose": (
                "value a cyclical issuer on normalized through-cycle operations"
            ),
        },
        {
            "model_id": "biotech_rnpv",
            "archetype": "U.S. clinical-stage or commercial biotech issuer",
            "basis": "equity",
            "profile_id": "us-gaap-public-v1",
            "required_fields": (
                "biotech_asset_trial_phase",
                "biotech_primary_endpoint",
                "biotech_trial_status_date",
                "biotech_cash_runway",
                "biotech_diluted_shares",
            ),
            "forbidden_conditions": (
                "BIOTECH_TRIAL_STATUS_STALE",
                "BIOTECH_ENDPOINT_UNVERIFIED",
                "BIOTECH_PATENT_EXCLUSIVITY_UNKNOWN",
            ),
            "sources": ("sec-filing", "fda-drugs", "clinicaltrials-api"),
            "evidence": (
                "dated FDA and ClinicalTrials.gov records matched to the issuer's "
                "assets",
                "issuer cash runway, dilution, and patent disclosures",
                "positive and negative clinical-stage golden cohorts",
                "independent probability-of-success and launch-cost scenarios",
            ),
            "assumption_policy": (
                "caller supplies indication market, launch path, costs, and "
                "success probabilities"
            ),
            "formula_graph": "asset-level-risk-adjusted-npv-v1",
            "uncertainty_policy": (
                "caller supplies bounded trial-success and commercial-outcome "
                "distributions"
            ),
            "calibration_targets": ("first-subsequent-trial-outcome-by-phase-v1",),
            "capital_bridge_policy": (
                "asset-risk-adjusted-value-plus-cash-minus-debt-and-dilution-v1"
            ),
            "valuation_basis": "equity",
            "economic_purpose": (
                "value biotech assets with explicit clinical and commercial risk "
                "adjustment"
            ),
        },
        {
            "model_id": "sum_of_parts",
            "archetype": "U.S. multi-segment conglomerate",
            "basis": "asset",
            "profile_id": "us-gaap-public-v1",
            "required_fields": (
                "sotp_segment_financials",
                "sotp_segment_valuation_basis",
                "sotp_corporate_cost_allocation",
                "sotp_parent_debt_and_cash",
                "sotp_diluted_shares",
            ),
            "forbidden_conditions": (
                "SOTP_SEGMENT_ELIMINATIONS_UNRESOLVED",
                "SOTP_INTERCOMPANY_BALANCES_UNRESOLVED",
                "SOTP_PARENT_CLAIMS_UNALLOCATED",
            ),
            "sources": ("sec-filing", "sec-companyfacts"),
            "evidence": (
                "issuer segment disclosures and intersegment eliminations",
                "segment-specific peer or asset valuation method with dated evidence",
                "positive and negative conglomerate cohorts",
                "independent parent-debt, cash, and dilution bridge",
            ),
            "assumption_policy": (
                "caller supplies segment valuation assumptions and shared-cost "
                "allocation"
            ),
            "formula_graph": "segment-values-plus-parent-bridge-v1",
            "uncertainty_policy": (
                "caller supplies explicit segment-specific distributions and "
                "dependence assumptions"
            ),
            "calibration_targets": ("first-subsequent-segment-operating-results-v1",),
            "capital_bridge_policy": (
                "segment-sum-minus-intercompany-and-parent-claims-v1"
            ),
            "valuation_basis": "asset",
            "economic_purpose": (
                "value conglomerate common equity from independently valued "
                "operating segments"
            ),
        },
        {
            "model_id": "ifrs_fcff_dcf",
            "archetype": "IFRS-reporting non-financial operating issuer",
            "basis": "enterprise",
            "profile_id": "ifrs-public-v1",
            "required_fields": (
                "ifrs_revenue",
                "ifrs_operating_profit",
                "ifrs_cash",
                "ifrs_borrowings",
                "ifrs_diluted_shares",
            ),
            "forbidden_conditions": (
                "IFRS_TAXONOMY_MAPPING_UNVERIFIED",
                "IFRS_PRESENTATION_CURRENCY_MISMATCH",
                "IFRS_CASH_FLOW_CLASSIFICATION_UNRESOLVED",
            ),
            "sources": ("ifrs-taxonomy", "sec-filing"),
            "evidence": (
                "issuer filing with pinned IFRS taxonomy and mapping decisions",
                "IAS 7 cash-flow classification reconciliation",
                "positive and negative IFRS reporting cohorts",
                "independent enterprise-to-equity capital bridge",
            ),
            "assumption_policy": (
                "caller supplies explicit IFRS-mapped forecasts and discount "
                "assumptions"
            ),
            "formula_graph": "ifrs-fcff-dcf-v1",
            "uncertainty_policy": (
                "caller supplies bounded forecast and discount-rate distributions"
            ),
            "calibration_targets": (
                "first-subsequent-reported-ifrs-revenue-and-margin-v1",
            ),
            "capital_bridge_policy": (
                "ifrs-enterprise-value-plus-cash-minus-borrowings-and-dilution-v1"
            ),
            "valuation_basis": "enterprise",
            "economic_purpose": (
                "value IFRS-reporting non-financial operations without mixing "
                "GAAP mappings"
            ),
        },
    )
    return tuple(
        ModelSpecV1(
            contract_version="fundamental.v1",
            model_id=family["model_id"],
            model_version=f"{family['model_id']}-v1",
            profile_id=family["profile_id"],
            required_fields=family["required_fields"],
            forbidden_conditions=family["forbidden_conditions"],
            supported_archetypes=(family["archetype"],),
            owner="fundamental-service",
            validator="independent-model-validation",
            lifecycle="exploratory",
            economic_purpose=family["economic_purpose"],
            valuation_basis=family["valuation_basis"],
            jurisdictions=("US",),
            accounting_bases=(
                ("ifrs",) if family["model_id"] == "ifrs_fcff_dcf" else ("us-gaap",)
            ),
            required_evidence=family["evidence"],
            assumption_policy=family["assumption_policy"],
            formula_graph=family["formula_graph"],
            numerical_policy="decimal-50-end-of-year-v1",
            eligibility_policy=(
                "model-required-facts-forbidden-conditions-and-quality-v1"
            ),
            abstention_policy=(
                "abstain-on-any-required-evidence-or-entity-scope-failure-v1"
            ),
            uncertainty_policy=family["uncertainty_policy"],
            calibration_policy="chronological-point-in-time-oos-before-promotion-v1",
            calibration_targets=family["calibration_targets"],
            calibration_required_for_promotion=True,
            required_release_gates=(
                "public-source-coverage",
                "point-in-time-accounting",
                "positive-negative-golden-cohorts",
                "independent-node-challenger",
                "calibration-oos",
                "replay-reproducibility",
            ),
            source_register=family["sources"],
            capital_bridge_policy=family["capital_bridge_policy"],
            golden_cohort=f"{family['model_id']}-positive-negative-golden-cohort-v1",
            challenger=f"{family['model_id']}-independent-node-challenger-v1",
            independent_validator="independent-model-validation",
            retirement_trigger=(
                "source-loss-drift-validation-failure-or-expired-review-v1"
            ),
            rollback_policy="restore-last-promoted-release-manifest-and-replay-v1",
            monitoring_policy=(
                "monthly-source-health-drift-missingness-and-abstention-v1"
            ),
        )
        for family in families
    )
