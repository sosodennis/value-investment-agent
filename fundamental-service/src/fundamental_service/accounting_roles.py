"""Source-bound accounting classifications; no valuation or approval policy."""

from __future__ import annotations

from datetime import date
from decimal import Context, Decimal, InvalidOperation, localcontext, ROUND_HALF_EVEN
import re
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


class DisclosedAmountV1(RoleModel):
    parsed_fact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    quote_start: int = Field(ge=0)
    exact_quote: str = Field(min_length=16, max_length=8192)
    amount_start: int = Field(ge=0)
    amount_token: str = Field(
        pattern=r"^-?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?$",
        max_length=80,
    )
    scale_start: int = Field(ge=0)
    scale_token: Literal[
        "dollars",
        "shares",
        "thousand",
        "thousands",
        "million",
        "millions",
        "billion",
        "billions",
    ]
    scale: Literal[0, 3, 6, 9]
    unit_start: int = Field(ge=0)
    unit_quote: str = Field(min_length=1, max_length=64)
    reported_unit: str = Field(min_length=1)
    reported_decimals: int = Field(ge=-9, le=18)
    covered_classes: tuple[str, ...] = Field(min_length=1, max_length=32)
    complete_role: Literal[True]

    @model_validator(mode="after")
    def transcription_is_consistent(self) -> DisclosedAmountV1:
        scales = {
            "dollars": 0,
            "shares": 0,
            "thousand": 3,
            "thousands": 3,
            "million": 6,
            "millions": 6,
            "billion": 9,
            "billions": 9,
        }
        fractional_digits = len(self.amount_token.partition(".")[2])
        if (
            self.scale != scales[self.scale_token]
            or self.reported_decimals != fractional_digits - self.scale
            or len(self.amount_token.replace(",", "").replace(".", "").lstrip("-")) > 34
        ):
            raise ValueError(
                "disclosed scale and precision must match the source token"
            )
        end = self.amount_start + len(self.amount_token)
        if self.exact_quote[self.amount_start : end] != self.amount_token:
            raise ValueError("disclosed amount is not at its exact quote offset")
        for neighbor in (
            self.exact_quote[self.amount_start - 1 : self.amount_start]
            if self.amount_start
            else "",
            self.exact_quote[end : end + 1],
        ):
            if neighbor and neighbor in "0123456789.,-":
                raise ValueError(
                    "disclosed amount must reference a complete numeric token"
                )
        if len(set(self.covered_classes)) != len(self.covered_classes) or any(
            not item.strip() for item in self.covered_classes
        ):
            raise ValueError("disclosed covered classes must be distinct and nonempty")
        return self


class AccountingPeriodRuleV1(RoleModel):
    period: AccountingPeriodV1
    disposition: Literal[
        "derived", "disclosed", "confirmed_absent", "unknown", "unsupported"
    ]
    components: tuple[AccountingComponentV1, ...] = ()
    absence_passages: tuple[AbsencePassageV1, ...] = ()
    disclosed_amount: DisclosedAmountV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def disposition_has_evidence(self) -> AccountingPeriodRuleV1:
        if self.disposition == "derived":
            if (
                len(self.components) < 2
                or self.absence_passages
                or self.disclosed_amount
            ):
                raise ValueError(
                    "derived roles require at least two numeric components"
                )
        elif self.disposition == "disclosed":
            if (
                self.components
                or self.absence_passages
                or self.disclosed_amount is None
            ):
                raise ValueError("disclosed roles require one exact original amount")
        elif self.disposition == "confirmed_absent":
            if self.components or not self.absence_passages or self.disclosed_amount:
                raise ValueError(
                    "confirmed absence requires original disclosure passages"
                )
        elif self.components or self.absence_passages or self.disclosed_amount:
            raise ValueError("unresolved roles cannot carry resolved numeric evidence")
        keys = tuple(item.parsed_fact_digest for item in self.components)
        if len(set(keys)) != len(keys):
            raise ValueError("accounting components must not repeat a source fact")
        if self.components and not any(item.sign == 1 for item in self.components):
            raise ValueError(
                "accounting classification needs a positive base component"
            )
        return self

    def source_references(self) -> tuple[str, ...]:
        if self.disclosed_amount is not None:
            return (self.disclosed_amount.parsed_fact_digest,)
        if self.disposition == "derived":
            return tuple(item.parsed_fact_digest for item in self.components)
        return tuple(item.parsed_fact_digest for item in self.absence_passages)


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
    references = rule.source_references()
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
    if rule.disposition == "disclosed":
        transcription = rule.disclosed_amount
        assert transcription is not None
        fact = by_digest[transcription.parsed_fact_digest]
        scale_end = transcription.scale_start + len(transcription.scale_token)
        unit_end = transcription.unit_start + len(transcription.unit_quote)
        if (
            fact.is_numeric
            or rule.period.instant
            or fact.period_start != rule.period.period_start
            or fact.period_end != rule.period.period_end
            or fact.instant is not None
            or transcription.reported_unit != rules.unit
            or fact.value[
                transcription.quote_start : transcription.quote_start
                + len(transcription.exact_quote)
            ]
            != transcription.exact_quote
            or fact.value[transcription.scale_start : scale_end]
            != transcription.scale_token
            or fact.value[transcription.unit_start : unit_end]
            != transcription.unit_quote
            or re.search(r"[A-Za-z]", fact.value[scale_end : scale_end + 1])
            or (
                transcription.scale_start
                and re.search(
                    r"[A-Za-z]",
                    fact.value[
                        transcription.scale_start - 1 : transcription.scale_start
                    ],
                )
            )
        ):
            raise AccountingRoleError(
                "ACCOUNTING_DISCLOSED_AMOUNT_MISMATCH",
                "disclosed transcription requires its exact original period, unit and spans",
            )
        with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)):
            value = Decimal(transcription.amount_token.replace(",", "")).scaleb(
                transcription.scale
            )
        return Decimal(format(value, "f"))
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
