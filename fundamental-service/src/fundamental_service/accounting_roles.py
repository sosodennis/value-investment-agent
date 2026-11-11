"""Source-bound accounting classifications; no valuation or approval policy."""

from __future__ import annotations

from datetime import date
from decimal import Context, Decimal, InvalidOperation, localcontext, ROUND_HALF_EVEN
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .arelle_parser import ParsedXbrlFactV1
from .serialization import sha256_digest


class AccountingRoleError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RoleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AccountingPeriodV1(RoleModel):
    period_start: date | None = None
    period_end: date
    instant: bool = False

    @model_validator(mode="after")
    def period_shape(self) -> AccountingPeriodV1:
        if self.instant == (self.period_start is not None):
            raise ValueError("accounting period must be one instant or one duration")
        if self.period_start is not None and self.period_start > self.period_end:
            raise ValueError("accounting duration is reversed")
        return self


class AccountingComponentV1(RoleModel):
    parsed_fact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    sign: Literal[-1, 1] = 1


class AbsencePassageV1(RoleModel):
    parsed_fact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    exact_quote: str = Field(min_length=16)


class AccountingPeriodRuleV1(RoleModel):
    period: AccountingPeriodV1
    disposition: Literal["derived", "confirmed_absent", "unknown", "unsupported"]
    components: tuple[AccountingComponentV1, ...] = ()
    absence_passages: tuple[AbsencePassageV1, ...] = ()
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def disposition_has_evidence(self) -> AccountingPeriodRuleV1:
        if self.disposition == "derived":
            if len(self.components) < 2 or self.absence_passages:
                raise ValueError(
                    "derived roles require at least two numeric components"
                )
        elif self.disposition == "confirmed_absent":
            if self.components or not self.absence_passages:
                raise ValueError(
                    "confirmed absence requires original disclosure passages"
                )
        elif self.components or self.absence_passages:
            raise ValueError("unresolved roles cannot carry resolved numeric evidence")
        keys = tuple(item.parsed_fact_digest for item in self.components)
        if len(set(keys)) != len(keys):
            raise ValueError("accounting components must not repeat a source fact")
        if self.components and not any(item.sign == 1 for item in self.components):
            raise ValueError(
                "accounting classification needs a positive base component"
            )
        return self


class AccountingRoleRuleSetV1(RoleModel):
    protocol: Literal["sec-accounting-role-v1"] = "sec-accounting-role-v1"
    policy_version: str = Field(min_length=1)
    normalized_field: str = Field(min_length=1)
    issuer_id: str = Field(pattern=r"^\d{10}$")
    security_id: str = Field(min_length=1)
    accession_number: str = Field(pattern=r"^\d{10}-\d{2}-\d{6}$")
    raw_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_fact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    unit: str = Field(min_length=1)
    currency: str | None = None
    periods: tuple[AccountingPeriodRuleV1, ...] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def periods_are_distinct_and_ordered(self) -> AccountingRoleRuleSetV1:
        periods = tuple(sha256_digest(rule.period) for rule in self.periods)
        if len(set(periods)) != len(periods):
            raise ValueError("role rules must have distinct periods")
        if self.periods != tuple(
            sorted(self.periods, key=lambda rule: rule.period.period_end)
        ):
            raise ValueError("role rules must be chronological")
        expected_currency = (
            self.unit.rsplit(":", 1)[-1] if self.unit.startswith("iso4217:") else None
        )
        if self.currency != expected_currency:
            raise ValueError("role currency must match its XBRL unit")
        return self


class AccountingRoleEvidenceV1(RoleModel):
    """A computed accounting value retains the exact observations it consumes."""

    rule_set: AccountingRoleRuleSetV1
    period_rule: AccountingPeriodRuleV1
    source_facts: tuple[ParsedXbrlFactV1, ...] = ()
    value: Decimal | None = None

    @model_validator(mode="after")
    def resolved_value_matches_sources(self) -> AccountingRoleEvidenceV1:
        if self.period_rule not in self.rule_set.periods:
            raise ValueError("accounting evidence period is not in its rule set")
        expected = evaluate_period_rule(
            self.rule_set, self.period_rule, self.source_facts
        )
        if self.value != expected:
            raise ValueError("accounting value differs from its exact source evidence")
        if self.source_facts != tuple(sorted(self.source_facts, key=sha256_digest)):
            raise ValueError("accounting source evidence must be canonical")
        return self


def evaluate_period_rule(
    rules: AccountingRoleRuleSetV1,
    rule: AccountingPeriodRuleV1,
    source_facts: tuple[ParsedXbrlFactV1, ...],
) -> Decimal | None:
    """Evaluate only a predeclared rule; semantic review stays a release gate."""
    if rule.disposition in {"unknown", "unsupported"}:
        if source_facts:
            raise AccountingRoleError(
                "ACCOUNTING_ROLE_UNRESOLVED", "unresolved role has numeric evidence"
            )
        return None
    by_digest = {sha256_digest(fact): fact for fact in source_facts}
    references = (
        tuple(item.parsed_fact_digest for item in rule.components)
        if rule.disposition == "derived"
        else tuple(item.parsed_fact_digest for item in rule.absence_passages)
    )
    if len(by_digest) != len(source_facts) or set(by_digest) != set(references):
        raise AccountingRoleError(
            "ACCOUNTING_ROLE_SOURCE_MISMATCH",
            "role evidence does not match its exact source references",
        )
    for fact in source_facts:
        if (
            fact.entity_identifier is None
            or fact.entity_identifier.lstrip("0") != rules.issuer_id.lstrip("0")
            or fact.dimensions
            or fact.consolidation_scope != "consolidated"
        ):
            raise AccountingRoleError(
                "ACCOUNTING_ROLE_SCOPE_MISMATCH",
                "role source must match the consolidated issuer scope",
            )
    if rule.disposition == "confirmed_absent":
        for passage in rule.absence_passages:
            fact = by_digest[passage.parsed_fact_digest]
            disclosed_end = fact.instant or fact.period_end
            if (
                fact.is_numeric
                or passage.exact_quote not in fact.value
                or disclosed_end != rule.period.period_end
                or (
                    not rule.period.instant
                    and fact.period_start != rule.period.period_start
                )
            ):
                raise AccountingRoleError(
                    "ACCOUNTING_ABSENCE_PASSAGE_MISMATCH",
                    "absence assertion requires its exact original passage",
                )
        return Decimal("0")
    concepts = tuple(fact.concept for fact in source_facts)
    if len(set(concepts)) != len(concepts):
        raise AccountingRoleError(
            "ACCOUNTING_COMPONENT_OVERLAP",
            "a role cannot count equivalent source concepts twice",
        )
    amounts: list[Decimal] = []
    for component in rule.components:
        fact = by_digest[component.parsed_fact_digest]
        if (
            not fact.is_numeric
            or fact.unit != rules.unit
            or fact.period_start != rule.period.period_start
            or (fact.instant if rule.period.instant else fact.period_end)
            != rule.period.period_end
            or (fact.instant is not None) != rule.period.instant
        ):
            raise AccountingRoleError(
                "ACCOUNTING_COMPONENT_PERIOD_UNIT_MISMATCH",
                "accounting components must have one aligned period and unit",
            )
        try:
            amount = Decimal(fact.value)
        except InvalidOperation as error:
            raise AccountingRoleError(
                "ACCOUNTING_COMPONENT_NON_NUMERIC",
                "accounting component is not a finite amount",
            ) from error
        if not amount.is_finite():
            raise AccountingRoleError(
                "ACCOUNTING_COMPONENT_NON_NUMERIC",
                "accounting component is not a finite amount",
            )
        amounts.append(amount.copy_negate() if component.sign == -1 else amount)
    with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)):
        return sum(amounts, Decimal("0"))
