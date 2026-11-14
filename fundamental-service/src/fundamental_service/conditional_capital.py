"""Source-bound capital hypotheses; no completeness or release authority."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .capital_bridge_policy import (
    CapitalBridgePolicyError,
    require_disjoint_non_operating_assets,
)
from .contracts import (
    CapitalBridgeAssumptionsV1,
    PeriodType,
    CanonicalFactV1,
    QualityStatus,
    SourceRole,
    SourceSnapshotV1,
)
from .facts import canonical_fact_digest
from .equity_award_evidence import AWARD_FACT_FIELDS
from .numerical_policy import using_valuation_context
from .serialization import sha256_digest

CONDITIONAL_CAPITAL_POLICY: Literal["conditional-capital-hypotheses-v1"] = (
    "conditional-capital-hypotheses-v1"
)
OBSERVED_CAPITAL_FIELDS = (
    "cash_and_equivalents",
    "non_operating_assets",
    "current_interest_bearing_debt",
    "long_term_interest_bearing_debt",
    "current_operating_lease_liabilities",
    "long_term_operating_lease_liabilities",
    "current_finance_lease_liabilities",
    "long_term_finance_lease_liabilities",
    "noncontrolling_interests",
    "common_shares_outstanding",
)
UNRESOLVED_CAPITAL_FIELDS = (
    "preferred_claims",
    "convertible_instruments",
    "other_share_classes",
)
CAPITAL_UNKNOWNS = (
    *UNRESOLVED_CAPITAL_FIELDS,
    "complete_award_inventory",
    "per_strike_inventory",
    "compensation_allocation",
)


class ConditionalCapitalError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _CapitalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class CapitalObservationRefV1(_CapitalModel):
    fact_id: str = Field(min_length=1)
    fact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class HypotheticalConvertibleDebtV1(_CapitalModel):
    treatment: Literal["debt"] = "debt"
    additional_debt: Decimal = Field(ge=0, allow_inf_nan=False)


class HypotheticalConversionV1(_CapitalModel):
    treatment: Literal["if_converted"] = "if_converted"
    additional_common_equivalent_shares: Decimal = Field(ge=0, allow_inf_nan=False)


def _convertible_exposure(
    value: HypotheticalConvertibleDebtV1 | HypotheticalConversionV1,
) -> tuple[Decimal, Decimal]:
    if isinstance(value, HypotheticalConvertibleDebtV1):
        return value.additional_debt, Decimal(0)
    return Decimal(0), value.additional_common_equivalent_shares


class CapitalHypothesisV1(_CapitalModel):
    name: Literal["base", "downside", "upside"]
    preferred_claims: Decimal = Field(ge=0, allow_inf_nan=False)
    convertible: Annotated[
        HypotheticalConvertibleDebtV1 | HypotheticalConversionV1,
        Field(discriminator="treatment"),
    ]
    other_common_equivalent_shares: Decimal = Field(ge=0, allow_inf_nan=False)
    incremental_award_shares: Decimal = Field(ge=0, allow_inf_nan=False)
    rationale: dict[
        Literal[
            "preferred_claims",
            "convertible_instruments",
            "other_share_classes",
            "award_dilution",
        ],
        str,
    ]

    @model_validator(mode="after")
    def every_hypothesis_is_explained(self) -> CapitalHypothesisV1:
        if set(self.rationale) != {*UNRESOLVED_CAPITAL_FIELDS, "award_dilution"} or any(
            len(text.strip()) < 40 for text in self.rationale.values()
        ):
            raise ValueError(
                "every unresolved capital hypothesis requires an explicit rationale"
            )
        return self


class ConditionalCapitalPolicyV1(_CapitalModel):
    protocol: Literal["conditional-capital-hypotheses-v1"] = CONDITIONAL_CAPITAL_POLICY
    interpretation: Literal["conditional_hypotheses_not_estimates_or_bounds"] = (
        "conditional_hypotheses_not_estimates_or_bounds"
    )
    complete_capital_claims: Literal[False] = False
    complete_award_inventory: Literal[False] = False
    model_id: Literal["fcff_dcf", "transition_fcff_dcf"]
    model_version: str = Field(min_length=1)
    mapping_version: str = Field(min_length=1)
    snapshot_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    issuer_id: str = Field(pattern=r"^[0-9]{10}$")
    security_id: str = Field(min_length=1)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    valuation_timestamp: datetime
    period_end: date
    observations: dict[str, CapitalObservationRefV1]
    supporting_observations: tuple[CapitalObservationRefV1, ...] = Field(min_length=1)
    unknowns: tuple[str, ...]
    limitations: tuple[str, ...] = Field(min_length=1)
    scenarios: tuple[CapitalHypothesisV1, ...] = Field(min_length=3, max_length=3)

    @field_validator("valuation_timestamp")
    @classmethod
    def timestamp_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("valuation timestamp requires a timezone")
        return value

    @field_validator("supporting_observations")
    @classmethod
    def canonical_supporting_observations(
        cls, values: tuple[CapitalObservationRefV1, ...]
    ) -> tuple[CapitalObservationRefV1, ...]:
        return tuple(sorted(values, key=lambda item: item.fact_id))

    @field_validator("scenarios")
    @classmethod
    def canonical_scenarios(
        cls, values: tuple[CapitalHypothesisV1, ...]
    ) -> tuple[CapitalHypothesisV1, ...]:
        order = {"base": 0, "downside": 1, "upside": 2}
        return tuple(sorted(values, key=lambda item: order[item.name]))

    @model_validator(mode="after")
    def policy_keeps_unknowns_and_sensitivity(self) -> ConditionalCapitalPolicyV1:
        if self.model_version != f"{self.model_id}-v2":
            raise ValueError(
                "conditional capital requires the supported FCFF model version"
            )
        if self.period_end > self.valuation_timestamp.date():
            raise ValueError("capital observations cannot have a future balance date")
        if set(self.observations) != set(OBSERVED_CAPITAL_FIELDS):
            raise ValueError("conditional capital requires every observed capital role")
        references = (*self.observations.values(), *self.supporting_observations)
        if len({item.fact_id for item in references}) != len(references):
            raise ValueError("capital observations cannot repeat a fact")
        if len(self.unknowns) != len(CAPITAL_UNKNOWNS) or set(self.unknowns) != set(
            CAPITAL_UNKNOWNS
        ):
            raise ValueError(
                "conditional capital must retain every unresolved claim and award role"
            )
        if any(len(text.strip()) < 40 for text in self.limitations):
            raise ValueError("conditional capital requires explicit limitations")
        if {item.name for item in self.scenarios} != {"base", "downside", "upside"}:
            raise ValueError(
                "capital scenarios must be distinct base, downside and upside"
            )
        sensitivity: dict[str, set[Decimal] | set[tuple[Decimal, Decimal]]] = {
            "preferred_claims": {item.preferred_claims for item in self.scenarios},
            "convertible": {
                _convertible_exposure(item.convertible) for item in self.scenarios
            },
            "other_common_equivalent_shares": {
                item.other_common_equivalent_shares for item in self.scenarios
            },
            "incremental_award_shares": {
                item.incremental_award_shares for item in self.scenarios
            },
        }
        for field, values in sensitivity.items():
            if len(values) < 2:
                raise ValueError(
                    f"unresolved capital role requires scenario sensitivity: {field}"
                )
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)


class ConditionalCapitalScenarioV1(_CapitalModel):
    hypothesis: CapitalHypothesisV1
    bridge: CapitalBridgeAssumptionsV1


class ConditionalCapitalAssessmentV1(_CapitalModel):
    policy: ConditionalCapitalPolicyV1
    status: Literal["provisional_conditional_hypotheses"] = (
        "provisional_conditional_hypotheses"
    )
    source_facts: tuple[CanonicalFactV1, ...]
    scenarios: tuple[ConditionalCapitalScenarioV1, ...]
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def output_digest(self) -> str:
        return sha256_digest(self)


@using_valuation_context
def assess_conditional_capital(
    policy: ConditionalCapitalPolicyV1,
    facts: Iterable[CanonicalFactV1],
    *,
    snapshot: SourceSnapshotV1,
    mapping_version: str,
) -> ConditionalCapitalAssessmentV1:
    """Bind hypothetical operands to observations without granting valuation authority."""

    policy = ConditionalCapitalPolicyV1.model_validate_json(policy.model_dump_json())
    identity = snapshot.identity
    if (
        policy.snapshot_manifest_digest,
        policy.issuer_id,
        policy.security_id,
        policy.currency,
        policy.valuation_timestamp,
    ) != (
        snapshot.manifest_digest,
        identity.issuer_id,
        identity.security_id,
        identity.currency,
        snapshot.valuation_timestamp,
    ):
        raise ConditionalCapitalError(
            "CONDITIONAL_CAPITAL_SNAPSHOT_MISMATCH",
            "capital hypotheses must bind the exact snapshot, identity, currency and date",
        )
    if policy.mapping_version != mapping_version:
        raise ConditionalCapitalError(
            "CONDITIONAL_CAPITAL_MAPPING_MISMATCH",
            "capital hypotheses require the exact release mapping version",
        )
    facts = tuple(facts)
    if len({fact.fact_id for fact in facts}) != len(facts):
        raise ConditionalCapitalError(
            "CONDITIONAL_CAPITAL_FACT_CONFLICT",
            "released capital candidates cannot repeat fact identities",
        )
    by_id = {fact.fact_id: fact for fact in facts}
    if {ref.fact_id for ref in policy.supporting_observations} != {
        fact.fact_id for fact in facts if fact.normalized_field in AWARD_FACT_FIELDS
    }:
        raise ConditionalCapitalError(
            "CONDITIONAL_CAPITAL_AWARD_OBSERVATIONS_UNBOUND",
            "conditional hypotheses must retain every released award observation",
        )
    sources = {
        source.content_hash: source
        for source in snapshot.source_records
        if source.role is SourceRole.FILING
        and source.source_id == "sec-filing"
        and source.available_at <= policy.valuation_timestamp
    }
    selected = []
    values = {}
    for role, reference in (
        *policy.observations.items(),
        *((None, ref) for ref in policy.supporting_observations),
    ):
        fact = by_id.get(reference.fact_id)
        if fact is None or canonical_fact_digest(fact) != reference.fact_digest:
            raise ConditionalCapitalError(
                "CONDITIONAL_CAPITAL_FACT_MISMATCH",
                "capital observation differs from its exact released fact",
            )
        source = sources.get(fact.source.content_hash)
        if (
            source is None
            or fact.issuer_id != policy.issuer_id
            or fact.security_id not in {None, policy.security_id}
            or fact.available_at > policy.valuation_timestamp
            or fact.quality is not QualityStatus.VERIFIED
            or fact.source.available_at > policy.valuation_timestamp
            or fact.period_end > policy.valuation_timestamp.date()
            or not fact.mapping_decision_id
            or not fact.accession_number
            or fact.accession_number != source.accession_number
            or fact.source.accession_number != source.accession_number
            or fact.source.source_role is not SourceRole.FILING
            or fact.is_amendment
        ):
            raise ConditionalCapitalError(
                "CONDITIONAL_CAPITAL_SOURCE_INVALID",
                "capital observations require eligible verified mapped sources in this snapshot",
            )
        if role is not None:
            if (
                fact.normalized_field != role
                or not isinstance(fact.value, Decimal)
                or not fact.value.is_finite()
                or fact.value < 0
                or fact.instant is None
                or fact.period_start is not None
                or fact.period_end != fact.instant
                or fact.context.period_type is not PeriodType.INSTANT
                or fact.context.start_date is not None
                or fact.context.end_date is not None
                or fact.context.instant != fact.instant
                or fact.context.concept_qname != fact.concept
                or fact.context.entity_scope.lstrip("0") != policy.issuer_id.lstrip("0")
                or fact.context.unit_qname.replace("xbrli:", "").replace("iso4217:", "")
                != fact.unit.replace("xbrli:", "").replace("iso4217:", "")
                or fact.instant > policy.valuation_timestamp.date()
                or fact.instant < policy.period_end
                or (
                    fact.instant != policy.period_end
                    and role != "common_shares_outstanding"
                )
                or fact.context.dimensions
                or fact.context.consolidation_scope != "consolidated"
            ):
                raise ConditionalCapitalError(
                    "CONDITIONAL_CAPITAL_OBSERVATION_INVALID",
                    "observed capital roles require exact nonnegative consolidated balances",
                )
            shares = role == "common_shares_outstanding"
            if (
                shares
                and (fact.unit not in {"shares", "xbrli:shares"} or fact.value <= 0)
            ) or (
                not shares
                and (
                    fact.currency != policy.currency
                    or fact.unit not in {policy.currency, f"iso4217:{policy.currency}"}
                )
            ):
                raise ConditionalCapitalError(
                    "CONDITIONAL_CAPITAL_UNIT_INVALID",
                    "capital observations require their declared currency or positive share unit",
                )
            values[role] = fact.value
            if any(
                candidate.normalized_field == role
                and candidate.instant is not None
                and fact.instant
                < candidate.instant
                <= policy.valuation_timestamp.date()
                and candidate.available_at <= policy.valuation_timestamp
                and candidate.source.content_hash in sources
                and candidate.quality is QualityStatus.VERIFIED
                for candidate in facts
            ):
                raise ConditionalCapitalError(
                    "CONDITIONAL_CAPITAL_OBSERVATION_SUPERSEDED",
                    "capital hypotheses cannot select away newer eligible balances",
                )
            if any(
                candidate.normalized_field == role
                and candidate.instant == fact.instant
                and candidate.source.content_hash in sources
                and candidate.quality is QualityStatus.VERIFIED
                and (candidate.value, candidate.unit, candidate.currency)
                != (fact.value, fact.unit, fact.currency)
                for candidate in facts
            ):
                raise ConditionalCapitalError(
                    "CONDITIONAL_CAPITAL_FACT_CONFLICT",
                    "capital hypotheses cannot select away conflicting observations",
                )
        selected.append(fact)
    if any(
        fact.normalized_field in UNRESOLVED_CAPITAL_FIELDS
        and fact.instant == policy.period_end
        and fact.quality is QualityStatus.VERIFIED
        and isinstance(fact.value, Decimal)
        for fact in facts
    ):
        raise ConditionalCapitalError(
            "CONDITIONAL_CAPITAL_OBSERVED_CLAIM_CONFLICT",
            "an observed claim cannot be replaced by an unresolved hypothesis",
        )
    try:
        require_disjoint_non_operating_assets(
            {role: by_id[ref.fact_id] for role, ref in policy.observations.items()},
            facts,
            snapshot,
        )
    except CapitalBridgePolicyError as error:
        raise ConditionalCapitalError(error.code, str(error)) from error
    scenarios = tuple(
        ConditionalCapitalScenarioV1(
            hypothesis=scenario,
            bridge=CapitalBridgeAssumptionsV1(
                cash=values["cash_and_equivalents"],
                non_operating_assets=values["non_operating_assets"],
                debt=values["current_interest_bearing_debt"]
                + values["long_term_interest_bearing_debt"]
                + (
                    scenario.convertible.additional_debt
                    if isinstance(scenario.convertible, HypotheticalConvertibleDebtV1)
                    else Decimal(0)
                ),
                preferred_stock=scenario.preferred_claims,
                lease_liabilities=values["current_finance_lease_liabilities"]
                + values["long_term_finance_lease_liabilities"],
                non_controlling_interest=values["noncontrolling_interests"],
                diluted_shares=values["common_shares_outstanding"]
                + scenario.incremental_award_shares
                + scenario.other_common_equivalent_shares
                + (
                    scenario.convertible.additional_common_equivalent_shares
                    if isinstance(scenario.convertible, HypotheticalConversionV1)
                    else Decimal(0)
                ),
            ),
        )
        for scenario in policy.scenarios
    )
    source_facts = tuple(sorted(selected, key=lambda fact: fact.fact_id))
    return ConditionalCapitalAssessmentV1(
        policy=policy,
        source_facts=source_facts,
        scenarios=scenarios,
        input_digest=sha256_digest(
            {
                "policy": policy,
                "source_facts": source_facts,
                "snapshot_manifest_digest": snapshot.manifest_digest,
            }
        ),
    )
