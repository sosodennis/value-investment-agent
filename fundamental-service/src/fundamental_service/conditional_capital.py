"""Assess source-bound capital hypotheses without granting release authority."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Literal

from .capital_bridge_policy import (
    CapitalBridgePolicyError,
    require_disjoint_non_operating_assets,
)
from .conditional_capital_balances import CapitalBalanceRole
from .conditional_capital_contracts import (
    CAPITAL_SUPPORTING_AWARD_FIELDS,
    ConditionalCapitalPolicyV1,
    ConditionalCapitalAssessmentV1,
    ConditionalCapitalScenarioV1,
    HypotheticalConversionV1,
    HypotheticalConvertibleDebtV1,
    UNRESOLVED_CAPITAL_FIELDS,
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
from .numerical_policy import using_valuation_context
from .serialization import sha256_digest


class ConditionalCapitalError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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
        fact.fact_id
        for fact in facts
        if fact.normalized_field in CAPITAL_SUPPORTING_AWARD_FIELDS
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
        (
            fact.normalized_field in UNRESOLVED_CAPITAL_FIELDS
            and fact.instant == policy.period_end
            or fact.normalized_field in policy.hypothetical_balance_fields
            and fact.instant is not None
            and fact.instant >= policy.period_end
            and fact.instant <= policy.valuation_timestamp.date()
            and fact.available_at <= policy.valuation_timestamp
            and fact.source.available_at <= policy.valuation_timestamp
            and fact.source.content_hash in sources
        )
        and fact.quality is QualityStatus.VERIFIED
        and isinstance(fact.value, Decimal)
        for fact in facts
    ):
        raise ConditionalCapitalError(
            "CONDITIONAL_CAPITAL_OBSERVED_CLAIM_CONFLICT",
            "an observed claim cannot be replaced by an unresolved hypothesis",
        )
    if "non_operating_assets" in policy.observations:
        try:
            require_disjoint_non_operating_assets(
                {role: by_id[ref.fact_id] for role, ref in policy.observations.items()},
                facts,
                snapshot,
            )
        except CapitalBridgePolicyError as error:
            raise ConditionalCapitalError(error.code, str(error)) from error
    balances = (
        {row.name: row.values for row in policy.balance_hypotheses.scenarios}
        if policy.balance_hypotheses is not None
        else {}
    )

    def amount(
        role: CapitalBalanceRole, scenario: Literal["base", "downside", "upside"]
    ) -> Decimal:
        return (
            balances[scenario][role]
            if role in policy.hypothetical_balance_fields
            else values[role]
        )

    scenarios = tuple(
        ConditionalCapitalScenarioV1(
            hypothesis=scenario,
            bridge=CapitalBridgeAssumptionsV1(
                cash=values["cash_and_equivalents"],
                non_operating_assets=amount("non_operating_assets", scenario.name),
                debt=amount("current_interest_bearing_debt", scenario.name)
                + values["long_term_interest_bearing_debt"]
                + (
                    scenario.convertible.additional_debt
                    if isinstance(scenario.convertible, HypotheticalConvertibleDebtV1)
                    else Decimal(0)
                ),
                preferred_stock=scenario.preferred_claims,
                lease_liabilities=values["current_finance_lease_liabilities"]
                + values["long_term_finance_lease_liabilities"],
                non_controlling_interest=amount(
                    "noncontrolling_interests", scenario.name
                ),
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
