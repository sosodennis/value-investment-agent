"""Versioned, source-bound composite noncash working-capital input policy.

This estimates an accounting input. It neither approves mappings/releases nor
implements an alternative FCFF formula. Sensitivity is deterministic, not a CI.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from .contracts import (
    CanonicalFactV1,
    InitialModelId,
    PeriodType,
    QualityStatus,
    SourceRole,
    SourceSnapshotV1,
    StrictModel,
)
from .numerical_policy import using_valuation_context
from .original_issuer import IssuerOperatingSourceV1, fact_matches_operating_identity
from .serialization import canonical_bytes, sha256_digest

WORKING_CAPITAL_INPUT_POLICY: Literal["composite-noncash-working-capital-v2"] = (
    "composite-noncash-working-capital-v2"
)
WORKING_CAPITAL_FIELDS = (
    "operating_current_receivables",
    "inventory",
    "contract_assets",
    "operating_current_payables",
    "accrued_operating_liabilities",
    "deferred_revenue",
)
_REQUIRED_EXCLUSIONS: dict[str, Literal["assets", "liabilities"]] = {
    "cash_and_equivalents": "assets",
    "short_term_investments": "assets",
    "current_interest_bearing_debt": "liabilities",
    "current_operating_lease_liabilities": "liabilities",
    "current_finance_lease_liabilities": "liabilities",
}
_EXCLUSION_ROLE_COVERAGE: dict[
    str, tuple[Literal["assets", "liabilities"], tuple[str, ...]]
] = {role: (side, (role,)) for role, side in _REQUIRED_EXCLUSIONS.items()} | {
    "cash_and_short_term_investments": (
        "assets",
        ("cash_and_equivalents", "short_term_investments"),
    ),
}
WORKING_CAPITAL_EXCLUSION_FIELDS = tuple(sorted(_EXCLUSION_ROLE_COVERAGE))
WORKING_CAPITAL_REQUIRED_EXCLUSIONS = tuple(sorted(_REQUIRED_EXCLUSIONS))


def working_capital_exclusion_coverage(
    role: str,
) -> tuple[Literal["assets", "liabilities"], tuple[str, ...]]:
    """Resolve the same role semantics used by the executable assessment."""

    if role not in _EXCLUSION_ROLE_COVERAGE:
        raise ValueError(f"unsupported working-capital exclusion role: {role}")
    return _EXCLUSION_ROLE_COVERAGE[role]


class InclusionScenariosV1(StrictModel):
    """Explicit inclusion fractions; no default operating classification."""

    low: Decimal = Field(ge=0, le=1)
    central: Decimal = Field(ge=0, le=1)
    high: Decimal = Field(ge=0, le=1)
    rationale: str = Field(min_length=16)

    @model_validator(mode="after")
    def ordered_fractions(self) -> InclusionScenariosV1:
        if not self.low <= self.central <= self.high:
            raise ValueError("inclusion scenarios must be ordered")
        return self


class WorkingCapitalExclusionV1(StrictModel):
    """One explicit source amount excluded from its same-filing gross parent."""

    account_class: str = Field(min_length=1)
    side: Literal["assets", "liabilities"]
    state: Literal["reported", "confirmed_absent", "unknown"]
    fact_id: str | None = None
    mapped_fact_role: str = Field(min_length=1)
    covered_by_fact_id: str = Field(min_length=1)
    covered_classes: tuple[str, ...] = Field(min_length=1)
    rationale: str = Field(min_length=16)

    @model_validator(mode="after")
    def evidence_matches_state(self) -> WorkingCapitalExclusionV1:
        if (self.state == "unknown") != (self.fact_id is None):
            raise ValueError("known exclusions require a fact; unknown has no amount")
        if tuple(sorted(set(self.covered_classes))) != self.covered_classes:
            raise ValueError("covered classes must be sorted and distinct")
        if any(
            self.side != _REQUIRED_EXCLUSIONS.get(name, self.side)
            for name in self.covered_classes
        ):
            raise ValueError("required exclusion has the wrong balance-sheet side")
        return self


class CompositeWorkingCapitalInputV1(StrictModel):
    policy_version: Literal["composite-noncash-working-capital-v2"] = (
        WORKING_CAPITAL_INPUT_POLICY
    )
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    mapping_version: str = Field(min_length=1)
    issuer_id: str = Field(min_length=1)
    accession_number: str = Field(min_length=1)
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    period_end: date
    current_assets_fact_id: str = Field(min_length=1)
    current_liabilities_fact_id: str = Field(min_length=1)
    exclusions: tuple[WorkingCapitalExclusionV1, ...] = Field(min_length=1)
    asset_residual: InclusionScenariosV1
    liability_residual: InclusionScenariosV1
    perimeter_rationale: str = Field(min_length=16)

    @model_validator(mode="after")
    def no_overlap_or_implicit_classification(self) -> CompositeWorkingCapitalInputV1:
        classes = [name for item in self.exclusions for name in item.covered_classes]
        if len(classes) != len(set(classes)):
            raise ValueError("exclusion coverage must not overlap")
        if not _REQUIRED_EXCLUSIONS.keys() <= set(classes):
            raise ValueError(
                "cash, investments, current debt and leases need explicit states"
            )
        ids = [self.current_assets_fact_id, self.current_liabilities_fact_id]
        for item in self.exclusions:
            parent = (
                self.current_assets_fact_id
                if item.side == "assets"
                else self.current_liabilities_fact_id
            )
            if item.covered_by_fact_id != parent:
                raise ValueError("exclusions require their declared gross parent")
            if item.fact_id is not None:
                ids.append(item.fact_id)
        if len(ids) != len(set(ids)):
            raise ValueError("a source fact cannot be counted more than once")
        if all(
            item.low == item.high
            for item in (self.asset_residual, self.liability_residual)
        ):
            raise ValueError("at least one residual requires explicit sensitivity")
        return self

    @property
    def fact_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                (
                    self.current_assets_fact_id,
                    self.current_liabilities_fact_id,
                    *(
                        item.fact_id
                        for item in self.exclusions
                        if item.fact_id is not None
                    ),
                )
            )
        )


class WorkingCapitalSensitivityV1(StrictModel):
    driver: Literal[
        "asset_residual_operating_fraction", "liability_residual_operating_fraction"
    ]
    fractions: tuple[Decimal, Decimal, Decimal]
    values: tuple[Decimal, Decimal, Decimal]


class CompositeWorkingCapitalAssessmentV1(StrictModel):
    """Full immutable source facts retain accession, scope, hashes and mapping IDs."""

    policy_input: CompositeWorkingCapitalInputV1
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["estimated", "abstained"]
    value: Decimal | None
    adjusted_assets: Decimal | None
    adjusted_liabilities: Decimal | None
    source_facts: tuple[CanonicalFactV1, ...]
    sensitivity: tuple[WorkingCapitalSensitivityV1, ...]
    sensitivity_interpretation: Literal[
        "deterministic_scenarios_not_confidence_intervals"
    ] = "deterministic_scenarios_not_confidence_intervals"
    missing_evidence: tuple[str, ...]
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def estimated_is_complete(self) -> CompositeWorkingCapitalAssessmentV1:
        if (self.status == "estimated") != (
            self.value is not None
            and self.adjusted_assets is not None
            and self.adjusted_liabilities is not None
            and bool(self.sensitivity)
            and not self.missing_evidence
        ):
            raise ValueError("estimated working capital requires complete evidence")
        if self.status == "abstained" and (self.value is not None or self.sensitivity):
            raise ValueError("abstention cannot contain a numerical estimate")
        if self.output_digest != sha256_digest(
            self.model_dump(exclude={"output_digest"})
        ):
            raise ValueError("working-capital assessment digest mismatch")
        return self


def working_capital_policy_digest() -> str:
    return sha256_digest(
        {
            "version": WORKING_CAPITAL_INPUT_POLICY,
            "formula": "(current_assets - asset_exclusions) * asset_fraction - (current_liabilities - liability_exclusions) * liability_fraction",
            "required_exclusions": _REQUIRED_EXCLUSIONS,
            "exclusion_role_coverage": _EXCLUSION_ROLE_COVERAGE,
            "unsupported_exclusion_roles": "abstain_requires_versioned_source_mapping",
            "unknown": "abstain",
            "sensitivity": "one_at_a_time_scenarios",
            "residuals": "explicit_fraction_and_rationale_no_default",
            "source_scope": "one_original_filing_same_instant_currency_consolidation",
        }
    )


def canonical_working_capital_inputs(
    inputs: tuple[CompositeWorkingCapitalInputV1, ...],
) -> tuple[CompositeWorkingCapitalInputV1, ...]:
    """Validate caller-created models and freeze a deterministic input ordering."""

    normalized = []
    for item in inputs:
        payload = item.model_dump()
        payload["exclusions"] = tuple(
            sorted(
                item.exclusions,
                key=lambda exclusion: (
                    exclusion.account_class,
                    sha256_digest(exclusion),
                ),
            )
        )
        normalized.append(
            CompositeWorkingCapitalInputV1.model_validate_json(canonical_bytes(payload))
        )
    return tuple(
        sorted(
            normalized,
            key=lambda item: (item.period_end, item.source_hash, sha256_digest(item)),
        )
    )


class ValuationWorkingCapitalPolicyV1(StrictModel):
    """Explicit release input policy for a full security valuation model."""

    protocol: Literal["valuation-working-capital-policy-v1"] = (
        "valuation-working-capital-policy-v1"
    )
    model_id: InitialModelId
    model_version: str = Field(min_length=1)
    requirements_profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    mapping_version: str = Field(min_length=1)
    inputs: tuple[CompositeWorkingCapitalInputV1, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def canonical_source_inputs(self) -> ValuationWorkingCapitalPolicyV1:
        if self.inputs != canonical_working_capital_inputs(self.inputs):
            raise ValueError("valuation working-capital inputs must be canonical")
        periods = {(item.issuer_id, item.period_end) for item in self.inputs}
        if len(periods) != len(self.inputs):
            raise ValueError("valuation working-capital issuer periods must be unique")
        if any(item.mapping_version != self.mapping_version for item in self.inputs):
            raise ValueError("valuation working-capital inputs must pin one mapping")
        return self


@using_valuation_context
def assess_composite_working_capital(
    policy_input: CompositeWorkingCapitalInputV1,
    facts: tuple[CanonicalFactV1, ...],
    *,
    snapshot: SourceSnapshotV1 | IssuerOperatingSourceV1,
) -> CompositeWorkingCapitalAssessmentV1:
    """Assess already mapped inputs; caller still authenticates their release."""

    policy_input = canonical_working_capital_inputs((policy_input,))[0]
    ordered_facts = tuple(
        sorted(facts, key=lambda fact: (fact.fact_id, sha256_digest(fact)))
    )
    by_id = {fact.fact_id: fact for fact in ordered_facts}
    sources = {source.content_hash: source for source in snapshot.source_records}
    referenced = tuple(
        fact for fact in ordered_facts if fact.fact_id in policy_input.fact_ids
    )
    missing: list[str] = []
    if policy_input.policy_digest != working_capital_policy_digest():
        missing.append("WORKING_CAPITAL_POLICY_DIGEST_MISMATCH")
    if policy_input.issuer_id != snapshot.identity.issuer_id:
        missing.append("WORKING_CAPITAL_ISSUER_MISMATCH")
    if len(by_id) != len(facts):
        missing.append("WORKING_CAPITAL_FACT_ID_DUPLICATE")
    exclusion_observations = [
        (fact.source.content_hash, fact.concept, fact.context.context_id)
        for fact in referenced
        if fact.fact_id
        not in {
            policy_input.current_assets_fact_id,
            policy_input.current_liabilities_fact_id,
        }
    ]
    if len(exclusion_observations) != len(set(exclusion_observations)):
        missing.append("WORKING_CAPITAL_EXCLUSION_OBSERVATION_DUPLICATE")
    mapped_classes: set[str] = set()
    for exclusion in policy_input.exclusions:
        coverage = _EXCLUSION_ROLE_COVERAGE.get(exclusion.mapped_fact_role)
        if coverage is None:
            missing.append(
                f"WORKING_CAPITAL_EXCLUSION_ROLE_UNSUPPORTED:{exclusion.mapped_fact_role}"
            )
            continue
        side, classes = coverage
        if exclusion.side != side or exclusion.covered_classes != classes:
            missing.append(
                f"WORKING_CAPITAL_EXCLUSION_COVERAGE_MISMATCH:{exclusion.account_class}:{exclusion.mapped_fact_role}"
            )
            continue
        fact = by_id.get(exclusion.fact_id or "")
        if fact is not None and fact.normalized_field == exclusion.mapped_fact_role:
            mapped_classes.update(classes)
    missing.extend(
        f"WORKING_CAPITAL_FACT_ROLE_MISSING:{account_class}"
        for account_class in sorted(set(_REQUIRED_EXCLUSIONS) - mapped_classes)
        if not any(
            account_class in item.covered_classes and item.state == "unknown"
            for item in policy_input.exclusions
        )
    )
    for key in policy_input.fact_ids:
        fact = by_id.get(key)
        if fact is None:
            missing.append(f"WORKING_CAPITAL_FACT_MISSING:{key}")
            continue
        source = sources.get(fact.source.content_hash)
        if source is None or not fact_matches_operating_identity(fact, snapshot):
            missing.append(f"WORKING_CAPITAL_SOURCE_MISMATCH:{key}")
            continue
        source_checks = (
            ("SOURCE_HASH", fact.source.content_hash == policy_input.source_hash),
            ("ACCESSION", fact.accession_number == policy_input.accession_number),
            (
                "PERIOD",
                fact.period_end == policy_input.period_end
                and fact.instant == policy_input.period_end
                and fact.period_start is None,
            ),
            (
                "INSTANT_CONTEXT",
                fact.context.period_type is PeriodType.INSTANT
                and fact.context.instant == policy_input.period_end,
            ),
            (
                "UNIT_CONTEXT",
                fact.context.measure == fact.unit
                and fact.context.unit_qname in {fact.unit, f"iso4217:{fact.unit}"},
            ),
            ("DIMENSIONS", not fact.context.dimensions),
            ("CONSOLIDATION_SCOPE", fact.context.consolidation_scope == "consolidated"),
            (
                "AMENDMENT",
                not fact.is_amendment
                and not source.is_amendment
                and fact.amendment_scope is None
                and source.amendment_scope is None
                and fact.filing_version == "original"
                and source.filing_version == "original",
            ),
            (
                "AVAILABILITY",
                fact.available_at == source.available_at
                and fact.source.available_at == source.available_at
                and fact.available_at <= snapshot.valuation_timestamp
                and source.available_at <= snapshot.valuation_timestamp,
            ),
            ("FILING_ROLE", fact.source.source_role is SourceRole.FILING),
            (
                "SOURCE_ACCESSION",
                fact.accession_number == source.accession_number
                and fact.source.accession_number == source.accession_number
                and bool(fact.accession_number),
            ),
            ("SOURCE_URI", fact.source.source_url == source.uri),
        )
        missing.extend(
            f"WORKING_CAPITAL_SOURCE_SCOPE_INVALID:{key}:{label}"
            for label, matches in source_checks
            if not matches
        )
        if (
            fact.currency != snapshot.identity.currency
            or fact.unit
            not in {snapshot.identity.currency, f"iso4217:{snapshot.identity.currency}"}
            or fact.quality is not QualityStatus.VERIFIED
            or not isinstance(fact.value, Decimal)
            or not fact.value.is_finite()
            or fact.value < 0
            or not fact.mapping_decision_id
            or fact.mapping_confidence != "high"
        ):
            missing.append(f"WORKING_CAPITAL_AMOUNT_OR_MAPPING_INVALID:{key}")
    if (
        referenced
        and len(
            {(item.source.content_hash, item.accession_number) for item in referenced}
        )
        != 1
    ):
        missing.append("WORKING_CAPITAL_FILING_MISMATCH")
    if len({(item.unit, item.scale, item.currency) for item in referenced}) != 1:
        missing.append("WORKING_CAPITAL_UNIT_MISMATCH")
    if (
        len(
            {
                (
                    item.period_end,
                    item.context.entity_scope,
                    item.context.consolidation_scope,
                    item.currency,
                    item.security_scope,
                    item.security_id,
                )
                for item in referenced
            }
        )
        != 1
    ):
        missing.append("WORKING_CAPITAL_PERIOD_SCOPE_OR_CURRENCY_MISMATCH")

    adjustments = {"assets": Decimal("0"), "liabilities": Decimal("0")}
    for item in policy_input.exclusions:
        if item.state == "unknown":
            missing.append(f"WORKING_CAPITAL_EXCLUSION_UNKNOWN:{item.account_class}")
            continue
        fact = by_id.get(item.fact_id or "")
        if (
            fact is None
            or not isinstance(fact.value, Decimal)
            or not fact.value.is_finite()
        ):
            continue
        if fact.normalized_field != item.mapped_fact_role:
            missing.append(
                f"WORKING_CAPITAL_EXCLUSION_ROLE_MISMATCH:{item.account_class}:{item.mapped_fact_role}"
            )
        if item.state == "confirmed_absent" and (
            fact.value != 0
            or fact.accounting_evidence is None
            or fact.accounting_evidence.period_rule.disposition != "confirmed_absent"
        ):
            missing.append(f"WORKING_CAPITAL_ABSENCE_UNSUPPORTED:{item.account_class}")
        adjustments[item.side] += fact.value

    totals: dict[str, Decimal] = {}
    for field, key, side in (
        ("current_assets", policy_input.current_assets_fact_id, "assets"),
        (
            "current_liabilities",
            policy_input.current_liabilities_fact_id,
            "liabilities",
        ),
    ):
        fact = by_id.get(key)
        if (
            fact is None
            or not isinstance(fact.value, Decimal)
            or not fact.value.is_finite()
        ):
            continue
        if fact.normalized_field != field:
            missing.append(f"WORKING_CAPITAL_TOTAL_ROLE_MISMATCH:{field}")
        totals[side] = fact.value - adjustments[side]
        if totals[side] < 0:
            missing.append(f"WORKING_CAPITAL_EXCLUSIONS_EXCEED_TOTAL:{side}")

    value = None
    sensitivity: tuple[WorkingCapitalSensitivityV1, ...] = ()
    if not missing:
        assets, liabilities = totals["assets"], totals["liabilities"]
        asset, liability = policy_input.asset_residual, policy_input.liability_residual
        value = assets * asset.central - liabilities * liability.central
        sensitivity = (
            WorkingCapitalSensitivityV1(
                driver="asset_residual_operating_fraction",
                fractions=(asset.low, asset.central, asset.high),
                values=(
                    assets * asset.low - liabilities * liability.central,
                    value,
                    assets * asset.high - liabilities * liability.central,
                ),
            ),
            WorkingCapitalSensitivityV1(
                driver="liability_residual_operating_fraction",
                fractions=(liability.low, liability.central, liability.high),
                values=(
                    assets * asset.central - liabilities * liability.low,
                    value,
                    assets * asset.central - liabilities * liability.high,
                ),
            ),
        )
    payload = {
        "policy_input": policy_input,
        "policy_digest": working_capital_policy_digest(),
        "status": "estimated" if value is not None else "abstained",
        "value": value,
        "adjusted_assets": totals.get("assets") if value is not None else None,
        "adjusted_liabilities": totals.get("liabilities")
        if value is not None
        else None,
        "source_facts": tuple(sorted(referenced, key=lambda fact: fact.fact_id)),
        "sensitivity": sensitivity,
        "sensitivity_interpretation": "deterministic_scenarios_not_confidence_intervals",
        "missing_evidence": tuple(sorted(set(missing))),
        "input_digest": sha256_digest(
            {
                "policy_input": policy_input,
                "facts": tuple(sorted(referenced, key=lambda fact: fact.fact_id)),
                "snapshot": snapshot.manifest_digest,
            }
        ),
    }
    return CompositeWorkingCapitalAssessmentV1.model_validate(
        {**payload, "output_digest": sha256_digest(payload)}
    )
