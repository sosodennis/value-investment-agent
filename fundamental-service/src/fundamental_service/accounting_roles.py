"""Source-bound accounting classifications; no valuation or approval policy."""

from __future__ import annotations

from datetime import date, timedelta
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


class AbsencePassageV1(RoleModel):
    parsed_fact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    exact_quote: str = Field(min_length=16)


class DerivativeClassificationPassageV1(RoleModel):
    parsed_fact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    exact_quote: str = Field(min_length=16, max_length=65536)


class AccruedInterestSwapExclusionV1(RoleModel):
    dimensions: tuple[tuple[str, str], ...] = Field(min_length=2, max_length=3)
    accrued_base_fact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    noncurrent_fact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    classification_passage: DerivativeClassificationPassageV1

    @model_validator(mode="after")
    def supported_dimensions(self) -> AccruedInterestSwapExclusionV1:
        axes = dict(self.dimensions)
        required = {
            "us-gaap:BalanceSheetLocationAxis",
            "us-gaap:DerivativeInstrumentRiskAxis",
        }
        if (
            len(axes) != len(self.dimensions)
            or self.dimensions != tuple(sorted(self.dimensions))
            or not required <= axes.keys()
            or axes.keys() - required - {"us-gaap:DerivativeByNatureAxis"}
            or axes["us-gaap:DerivativeInstrumentRiskAxis"]
            != "us-gaap:InterestRateSwapMember"
            or any(not member.strip() for member in axes.values())
        ):
            raise ValueError(
                "swap exclusion requires exact supported source dimensions"
            )
        return self


class AccountingComponentV1(RoleModel):
    parsed_fact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    sign: Literal[-1, 1] = 1
    balance_sheet_location: Literal["other_current_liabilities"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    accrued_interest_swap_exclusion: AccruedInterestSwapExclusionV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    finance_lease_expense_location: (
        Literal["operating_expenses", "interest_expense"] | None
    ) = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def swap_is_an_exclusion(self) -> AccountingComponentV1:
        if self.accrued_interest_swap_exclusion is not None and (
            self.sign != -1
            or self.balance_sheet_location is not None
            or self.finance_lease_expense_location is not None
        ):
            raise ValueError(
                "interest swap scope is only valid for a negative component"
            )
        if (
            self.balance_sheet_location is not None
            and self.finance_lease_expense_location is not None
        ):
            raise ValueError("a component cannot mix balance-sheet and expense scopes")
        return self


class DisclosedValueV1(RoleModel):
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

    @model_validator(mode="after")
    def transcription_is_consistent(self) -> DisclosedValueV1:
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


class DisclosedAmountV1(DisclosedValueV1):
    complete_role: Literal[True]


class DisclosedInstantDateV1(RoleModel):
    period_end: date
    month_day_start: int = Field(ge=0)
    month_day_token: str = Field(min_length=5, max_length=12)
    year_start: int = Field(ge=0)
    year_token: str = Field(pattern=r"^[0-9]{4}$")

    @model_validator(mode="after")
    def explicit_date_matches_target(self) -> DisclosedInstantDateV1:
        months = (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        )
        expected = f"{months[self.period_end.month - 1]} {self.period_end.day}"
        if self.month_day_token != expected or self.year_token != str(
            self.period_end.year
        ):
            raise ValueError("disclosed date tokens must match the target instant")
        return self


class DatedDisclosureComponentV1(DisclosedValueV1):
    kind: Literal["dated_disclosure"]
    sign: Literal[1] = 1
    date: DisclosedInstantDateV1
    complete_component: Literal[True]

    @model_validator(mode="after")
    def date_spans_are_exact(self) -> DatedDisclosureComponentV1:
        for start, token in (
            (self.date.month_day_start, self.date.month_day_token),
            (self.date.year_start, self.date.year_token),
        ):
            end = start + len(token)
            if (
                self.exact_quote[start:end] != token
                or (start and self.exact_quote[start - 1].isalnum())
                or (end < len(self.exact_quote) and self.exact_quote[end].isalnum())
            ):
                raise ValueError("disclosed date must reference exact complete tokens")
        if self.date.year_start <= self.date.month_day_start + len(
            self.date.month_day_token
        ):
            raise ValueError("disclosed year must follow its month and day")
        return self


class AccountingPeriodRuleV1(RoleModel):
    period: AccountingPeriodV1
    disposition: Literal[
        "derived",
        "classified",
        "disclosed",
        "confirmed_absent",
        "unknown",
        "unsupported",
    ]
    components: tuple[AccountingComponentV1 | DatedDisclosureComponentV1, ...] = ()
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
                raise ValueError("derived roles require at least two source components")
        elif self.disposition == "classified":
            if (
                len(self.components) != 1
                or not isinstance(self.components[0], AccountingComponentV1)
                or self.components[0].sign != 1
                or self.components[0].balance_sheet_location is None
                or self.absence_passages
                or self.disclosed_amount
            ):
                raise ValueError(
                    "classified roles require one scoped positive component"
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
        disclosed = tuple(
            item
            for item in self.components
            if isinstance(item, DatedDisclosureComponentV1)
        )
        if disclosed and (
            self.disposition != "derived"
            or not self.period.instant
            or any(item.date.period_end != self.period.period_end for item in disclosed)
        ):
            raise ValueError(
                "dated disclosure components require their same-date instant derived role"
            )
        classes = tuple(name for item in disclosed for name in item.covered_classes)
        if len(set(classes)) != len(classes):
            raise ValueError(
                "dated disclosure components cannot repeat covered classes"
            )
        return self

    def source_references(self) -> tuple[str, ...]:
        if self.disclosed_amount is not None:
            return (self.disclosed_amount.parsed_fact_digest,)
        if self.disposition in {"derived", "classified"}:
            return tuple(
                dict.fromkeys(
                    [item.parsed_fact_digest for item in self.components]
                    + [
                        item.accrued_interest_swap_exclusion.classification_passage.parsed_fact_digest
                        for item in self.components
                        if isinstance(item, AccountingComponentV1)
                        and item.accrued_interest_swap_exclusion is not None
                    ]
                )
            )
        return tuple(item.parsed_fact_digest for item in self.absence_passages)


class _AccountingRoleRules(RoleModel):
    policy_version: str = Field(min_length=1)
    normalized_field: str = Field(min_length=1)
    issuer_id: str = Field(pattern=r"^\d{10}$")
    accession_number: str = Field(pattern=r"^\d{10}-\d{2}-\d{6}$")
    raw_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_fact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    unit: str = Field(min_length=1)
    currency: str | None = None
    periods: tuple[AccountingPeriodRuleV1, ...] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def periods_are_distinct_and_ordered(self) -> _AccountingRoleRules:
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


class AccountingRoleRuleSetV1(_AccountingRoleRules):
    protocol: Literal["sec-accounting-role-v1"] = "sec-accounting-role-v1"
    security_id: str = Field(min_length=1)


class IssuerAccountingRoleRuleSetV1(_AccountingRoleRules):
    protocol: Literal["sec-accounting-role-issuer-v1"] = "sec-accounting-role-issuer-v1"
    security_id: None = None


AccountingRoleRules = AccountingRoleRuleSetV1 | IssuerAccountingRoleRuleSetV1


class AccountingRoleEvidenceV1(RoleModel):
    """A computed accounting value retains the exact observations it consumes."""

    rule_set: AccountingRoleRules
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
    rules: AccountingRoleRules,
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
    components = {item.parsed_fact_digest: item for item in rule.components}
    for fact in source_facts:
        component = components.get(sha256_digest(fact))
        exclusion = (
            component.accrued_interest_swap_exclusion
            if isinstance(component, AccountingComponentV1)
            else None
        )
        derivative_scope = (
            exclusion is not None
            and fact.dimensions == exclusion.dimensions
            and fact.consolidation_scope == "segmented"
            and fact.security_scope == "segmented"
        )
        classified_location = (
            isinstance(component, AccountingComponentV1)
            and component.balance_sheet_location is not None
        )
        classified_expense = (
            isinstance(component, AccountingComponentV1)
            and component.finance_lease_expense_location is not None
        )
        if classified_expense:
            assert isinstance(component, AccountingComponentV1)
            _validate_finance_lease_expense_classification(rules, rule, component, fact)
        if classified_location:
            assert isinstance(component, AccountingComponentV1)
            _validate_current_lease_classification(rules, rule, component, fact)
            if rules.normalized_field.startswith("long_term_") and (
                len(rule.components) != 2
                or not any(
                    other.concept == fact.concept
                    and not other.dimensions
                    and isinstance(
                        other_component := components[sha256_digest(other)],
                        AccountingComponentV1,
                    )
                    and other_component.sign == 1
                    and other_component.balance_sheet_location is None
                    for other in source_facts
                )
            ):
                raise AccountingRoleError(
                    "ACCOUNTING_ROLE_SCOPE_MISMATCH",
                    "noncurrent lease classification requires the same lease total minus current",
                )
        if (
            fact.entity_identifier is None
            or fact.entity_identifier.lstrip("0") != rules.issuer_id.lstrip("0")
            or (
                not classified_location
                and not classified_expense
                and not derivative_scope
                and (fact.dimensions or fact.consolidation_scope != "consolidated")
            )
            or (
                isinstance(rules, IssuerAccountingRoleRuleSetV1)
                and not derivative_scope
                and not classified_location
                and not classified_expense
                and fact.security_scope not in {"issuer", "consolidated", "unspecified"}
            )
        ):
            raise AccountingRoleError(
                "ACCOUNTING_ROLE_SCOPE_MISMATCH",
                "role source must match the consolidated issuer scope",
            )
    if rule.disposition == "disclosed":
        transcription = rule.disclosed_amount
        assert transcription is not None
        fact = by_digest[transcription.parsed_fact_digest]
        if (
            fact.is_numeric
            or rule.period.instant
            or fact.period_start != rule.period.period_start
            or fact.period_end != rule.period.period_end
            or fact.instant is not None
        ):
            raise AccountingRoleError(
                "ACCOUNTING_DISCLOSED_AMOUNT_MISMATCH",
                "disclosed transcription requires its exact original period, unit and spans",
            )
        return _transcribe_amount(transcription, fact, rules.unit)
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
    concepts = tuple(
        (
            by_digest[item.parsed_fact_digest].concept,
            by_digest[item.parsed_fact_digest].dimensions,
        )
        for item in rule.components
    )
    if len(set(concepts)) != len(concepts):
        raise AccountingRoleError(
            "ACCOUNTING_COMPONENT_OVERLAP",
            "a role cannot count equivalent source concepts twice",
        )
    for component in rule.components:
        fact = by_digest[component.parsed_fact_digest]
        if not fact.dimensions:
            continue
        if any(
            other.concept == fact.concept
            and not other.dimensions
            and (component.sign != -1 or components[sha256_digest(other)].sign != 1)
            for other in source_facts
        ):
            raise AccountingRoleError(
                "ACCOUNTING_COMPONENT_OVERLAP",
                "a total and its classified current portion require total minus current",
            )
    amounts: list[Decimal] = []
    unsigned: dict[str, Decimal] = {}
    for component in rule.components:
        fact = by_digest[component.parsed_fact_digest]
        if isinstance(component, DatedDisclosureComponentV1):
            if (
                not rule.period.instant
                or component.date.period_end != rule.period.period_end
                or fact.is_numeric
                or fact.instant is not None
                or fact.period_start is None
                or fact.period_end is None
                or not 330 <= (fact.period_end - fact.period_start).days <= 371
                or not fact.period_start - timedelta(days=1)
                <= rule.period.period_end
                <= fact.period_end
            ):
                raise AccountingRoleError(
                    "ACCOUNTING_DISCLOSED_DATE_MISMATCH",
                    "dated disclosure requires its explicit instant within the original annual or comparative period",
                )
            amount = _transcribe_amount(component, fact, rules.unit)
            unsigned[component.parsed_fact_digest] = amount
            amounts.append(amount)
            continue
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
        unsigned[component.parsed_fact_digest] = amount
        amounts.append(amount.copy_negate() if component.sign == -1 else amount)
    with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)):
        _validate_swap_exclusion(rules, rule, by_digest, unsigned)
        result = sum(amounts, Decimal("0"))
        _validate_lease_expense_components(rules, rule, by_digest, unsigned, result)
        return result


def _transcribe_amount(
    transcription: DisclosedValueV1, fact: ParsedXbrlFactV1, unit: str
) -> Decimal:
    # Revalidate nested token/date constraints even for in-process model_copy callers.
    try:
        transcription = type(transcription).model_validate(transcription.model_dump())
    except ValueError as error:
        raise AccountingRoleError(
            "ACCOUNTING_DISCLOSED_AMOUNT_MISMATCH",
            "disclosed transcription requires its exact original period, unit and spans",
        ) from error
    scale_end = transcription.scale_start + len(transcription.scale_token)
    unit_end = transcription.unit_start + len(transcription.unit_quote)
    if (
        transcription.reported_unit != unit
        or fact.value[
            transcription.quote_start : transcription.quote_start
            + len(transcription.exact_quote)
        ]
        != transcription.exact_quote
        or fact.value[transcription.scale_start : scale_end]
        != transcription.scale_token
        or fact.value[transcription.unit_start : unit_end] != transcription.unit_quote
        or re.search(r"[A-Za-z]", fact.value[scale_end : scale_end + 1])
        or (
            transcription.scale_start
            and re.search(
                r"[A-Za-z]",
                fact.value[transcription.scale_start - 1 : transcription.scale_start],
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


def accounting_reported_decimals(
    rule: AccountingPeriodRuleV1, source_facts: tuple[ParsedXbrlFactV1, ...]
) -> int | None:
    if rule.disclosed_amount is not None:
        return rule.disclosed_amount.reported_decimals
    disclosed = tuple(
        component
        for component in rule.components
        if isinstance(component, DatedDisclosureComponentV1)
    )
    if not disclosed and not any(
        isinstance(component, AccountingComponentV1)
        and component.finance_lease_expense_location is not None
        for component in rule.components
    ):
        return None
    precision = [item.reported_decimals for item in disclosed]
    for fact in source_facts:
        if not fact.is_numeric or fact.decimals == "INF":
            continue
        if fact.decimals is None or not re.fullmatch(r"-?[0-9]+", fact.decimals):
            return None
        precision.append(int(fact.decimals))
    return min(precision, default=None)


def _validate_finance_lease_expense_classification(
    rules: AccountingRoleRules,
    rule: AccountingPeriodRuleV1,
    component: AccountingComponentV1,
    fact: ParsedXbrlFactV1,
) -> None:
    locations = {
        "us-gaap:FinanceLeaseRightOfUseAssetAmortization": (
            "operating_expenses",
            "us-gaap:OperatingExpenseMember",
        ),
        "us-gaap:FinanceLeaseInterestExpense": (
            "interest_expense",
            "us-gaap:InterestExpenseMember",
        ),
    }
    location, member = locations.get(fact.concept, (None, None))
    sign = {"finance_lease_cost": 1, "operating_lease_cost": -1}.get(
        rules.normalized_field
    )
    if (
        location is None
        or component.finance_lease_expense_location != location
        or component.sign != sign
        or rule.disposition != "derived"
        or rule.period.instant
        or not rules.unit.startswith("iso4217:")
        or fact.dimensions != (("us-gaap:IncomeStatementLocationAxis", member),)
        or fact.consolidation_scope != "segmented"
        or fact.security_scope != "segmented"
    ):
        raise AccountingRoleError(
            "ACCOUNTING_ROLE_SCOPE_MISMATCH",
            "finance lease expense requires its exact statement location, role and sign",
        )


def _validate_lease_expense_components(
    rules: AccountingRoleRules,
    rule: AccountingPeriodRuleV1,
    by_digest: dict[str, ParsedXbrlFactV1],
    unsigned: dict[str, Decimal],
    result: Decimal,
) -> None:
    classified = tuple(
        item
        for item in rule.components
        if isinstance(item, AccountingComponentV1)
        and item.finance_lease_expense_location is not None
    )
    if not classified:
        return
    bases = tuple(item for item in rule.components if item not in classified)
    operating = rules.normalized_field == "operating_lease_cost"
    if len(classified) != 2 or len(bases) != (1 if operating else 0):
        raise AccountingRoleError(
            "ACCOUNTING_ROLE_SCOPE_MISMATCH",
            "lease expense requires paired finance components and its declared total",
        )
    if operating:
        base = bases[0]
        fact = by_digest[base.parsed_fact_digest]
        if (
            not isinstance(base, AccountingComponentV1)
            or base.sign != 1
            or base.balance_sheet_location is not None
            or base.accrued_interest_swap_exclusion is not None
            or fact.concept != "us-gaap:LeaseCost"
            or fact.dimensions
            or fact.consolidation_scope != "consolidated"
        ):
            raise AccountingRoleError(
                "ACCOUNTING_ROLE_SCOPE_MISMATCH",
                "operating lease expense requires its consolidated lease-cost total",
            )
    if result < 0 or any(value < 0 for value in unsigned.values()):
        raise AccountingRoleError(
            "ACCOUNTING_LEASE_COST_INVALID",
            "lease expense components and the resulting role must be nonnegative",
        )


def _validate_current_lease_classification(
    rules: AccountingRoleRules,
    rule: AccountingPeriodRuleV1,
    component: AccountingComponentV1,
    fact: ParsedXbrlFactV1,
) -> None:
    allowed = {
        "current_operating_lease_liabilities": (
            ("us-gaap:OperatingLeaseLiability", 1),
        ),
        "current_finance_lease_liabilities": (("us-gaap:FinanceLeaseLiability", 1),),
        "long_term_operating_lease_liabilities": (
            ("us-gaap:OperatingLeaseLiability", -1),
        ),
        "long_term_finance_lease_liabilities": (("us-gaap:FinanceLeaseLiability", -1),),
        "accrued_operating_liabilities": (
            ("us-gaap:OperatingLeaseLiability", -1),
            ("us-gaap:FinanceLeaseLiability", -1),
        ),
    }
    if (
        component.balance_sheet_location != "other_current_liabilities"
        or (fact.concept, component.sign) not in allowed.get(rules.normalized_field, ())
        or (
            rules.normalized_field.startswith("current_")
            and rule.disposition != "classified"
        )
        or not rule.period.instant
        or fact.dimensions
        != (
            (
                "us-gaap:BalanceSheetLocationAxis",
                "us-gaap:OtherCurrentLiabilitiesMember",
            ),
        )
        or fact.consolidation_scope != "segmented"
        or fact.security_scope != "segmented"
    ):
        raise AccountingRoleError(
            "ACCOUNTING_ROLE_SCOPE_MISMATCH",
            "lease classification requires its exact current-liability axis, role and sign",
        )


def _validate_swap_exclusion(
    rules: AccountingRoleRules,
    rule: AccountingPeriodRuleV1,
    sources: dict[str, ParsedXbrlFactV1],
    amounts: dict[str, Decimal],
) -> None:
    exclusions = tuple(
        item
        for item in rule.components
        if isinstance(item, AccountingComponentV1)
        and item.accrued_interest_swap_exclusion is not None
    )
    if not exclusions:
        return
    if (
        len(exclusions) != 1
        or rules.normalized_field != "accrued_operating_liabilities"
        or not rule.period.instant
    ):
        raise AccountingRoleError(
            "ACCOUNTING_DERIVATIVE_EXCLUSION_MISMATCH",
            "one interest swap exclusion requires an instant accrued operating role",
        )
    component = exclusions[0]
    exclusion = component.accrued_interest_swap_exclusion
    assert exclusion is not None
    positive = {item.parsed_fact_digest for item in rule.components if item.sign == 1}
    total = sources[component.parsed_fact_digest]
    base = sources.get(exclusion.accrued_base_fact_digest)
    noncurrent = sources.get(exclusion.noncurrent_fact_digest)
    passage = sources[exclusion.classification_passage.parsed_fact_digest]
    quote = exclusion.classification_passage.exact_quote
    if (
        component.sign != -1
        or total.concept
        != "us-gaap:InterestRateDerivativeInstrumentsNotDesignatedAsHedgingInstrumentsLiabilityAtFairValue"
        or total.dimensions != exclusion.dimensions
        or base is None
        or base.concept != "us-gaap:AccruedLiabilitiesCurrent"
        or exclusion.accrued_base_fact_digest not in positive
        or noncurrent is None
        or noncurrent.concept
        != "us-gaap:DerivativeInstrumentsAndHedgesLiabilitiesNoncurrent"
        or exclusion.noncurrent_fact_digest not in positive
        or passage.is_numeric
        or passage.concept
        != "us-gaap:ScheduleOfDerivativeInstrumentsInStatementOfFinancialPositionFairValueTextBlock"
        or passage.instant is not None
        or passage.period_start is None
        or passage.period_end is None
        or passage.period_end < rule.period.period_end
        or quote not in passage.value
        or "Accrued expenses" not in quote
        or "Other noncurrent liabilities" not in quote
        or str(rule.period.period_end.year) not in quote
    ):
        raise AccountingRoleError(
            "ACCOUNTING_DERIVATIVE_EXCLUSION_MISMATCH",
            "swap exclusion requires its exact accrued base, noncurrent pair and original classification passage",
        )
    current = (
        amounts[component.parsed_fact_digest]
        - amounts[exclusion.noncurrent_fact_digest]
    )
    accrued = amounts[exclusion.accrued_base_fact_digest]
    if (
        min(
            amounts[component.parsed_fact_digest],
            amounts[exclusion.noncurrent_fact_digest],
            accrued,
        )
        < 0
        or not Decimal("0") <= current <= accrued
        or sum(
            (amounts[item.parsed_fact_digest] * item.sign for item in rule.components),
            Decimal("0"),
        )
        < 0
    ):
        raise AccountingRoleError(
            "ACCOUNTING_DERIVATIVE_EXCLUSION_MISMATCH",
            "current swap exclusion must fit the original nonnegative accrued balance",
        )
