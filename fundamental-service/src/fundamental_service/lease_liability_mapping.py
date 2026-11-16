"""Select standard current-location lease facts without discarding their scope."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Literal

from .accounting_roles import (
    AccountingComponentV1,
    AccountingPeriodRuleV1,
    AccountingPeriodV1,
    AccountingRoleError,
    AccountingRoleRules,
    AccountingRoleRuleSetV1,
    IssuerAccountingRoleRuleSetV1,
    evaluate_period_rule,
)
from .arelle_parser import fact_semantic_digest, ParsedXbrlFactV1
from .original_issuer import OriginalIssuerEvidenceV1
from .serialization import sha256_digest

_CURRENT_LOCATION = (
    ("us-gaap:BalanceSheetLocationAxis", "us-gaap:OtherCurrentLiabilitiesMember"),
)
_NONCURRENT_LOCATION = (
    ("us-gaap:BalanceSheetLocationAxis", "us-gaap:OtherNoncurrentLiabilitiesMember"),
)
_LOCATIONS = {
    None: (),
    "current": _CURRENT_LOCATION,
    "noncurrent": _NONCURRENT_LOCATION,
}
_CONCEPTS = {
    "current_finance_lease_liabilities": "us-gaap:FinanceLeaseLiability",
    "long_term_finance_lease_liabilities": "us-gaap:FinanceLeaseLiability",
    "current_operating_lease_liabilities": "us-gaap:OperatingLeaseLiability",
    "long_term_operating_lease_liabilities": "us-gaap:OperatingLeaseLiability",
}
_POLICY = "standard-current-location-lease-liabilities-v1"


def lease_liability_concept(
    original: OriginalIssuerEvidenceV1, normalized_field: str
) -> str | None:
    concept = _CONCEPTS.get(normalized_field)
    if concept is not None and any(
        fact.concept == concept and fact.dimensions == _CURRENT_LOCATION
        for fact in original.report.facts
    ):
        return "classified:" + normalized_field
    return None


@dataclass(frozen=True)
class LeaseLiabilitySelection:
    rules: AccountingRoleRules | None = None
    selected: tuple[ParsedXbrlFactV1, ...] = ()
    reason_codes: tuple[str, ...] = ()


def _eligible(
    fact: ParsedXbrlFactV1,
    cik: str,
    *,
    location: Literal["current", "noncurrent"] | None,
) -> bool:
    try:
        amount = Decimal(fact.value)
    except InvalidOperation:
        return False
    return (
        fact.is_numeric
        and amount.is_finite()
        and amount >= 0
        and fact.unit == "iso4217:USD"
        and fact.instant is not None
        and fact.period_start is None
        and fact.period_end is None
        and fact.dimensions == _LOCATIONS[location]
        and fact.consolidation_scope == ("segmented" if location else "consolidated")
        and fact.security_scope
        in ({"segmented"} if location else {"issuer", "consolidated", "unspecified"})
        and fact.entity_scheme == "http://www.sec.gov/CIK"
        and re.fullmatch(r"[0-9]{1,10}", fact.entity_identifier or "") is not None
        and (fact.entity_identifier or "").lstrip("0") == cik.lstrip("0")
        and re.fullmatch(
            r"http://(?:fasb\.org|xbrl\.us)/us-gaap/\d{4}(?:-\d{2}-\d{2})?",
            fact.namespace_uri or "",
        )
        is not None
        and (
            fact.decimals == "INF"
            or re.fullmatch(r"-?[0-9]+", fact.decimals or "") is not None
        )
    )


def _one(
    matches: tuple[ParsedXbrlFactV1, ...],
    cik: str,
    *,
    location: Literal["current", "noncurrent"] | None = None,
) -> tuple[ParsedXbrlFactV1 | None, str | None]:
    if not matches:
        return None, "MAPPING_LEASE_COMPONENT_MISSING"
    if any(not _eligible(fact, cik, location=location) for fact in matches):
        return None, "MAPPING_LEASE_COMPONENT_INVALID"
    if len({(Decimal(f.value), f.decimals, f.namespace_uri) for f in matches}) != 1:
        return None, "MAPPING_OBSERVATION_CONFLICT"
    return min(matches, key=sha256_digest), None


def select_lease_liability(
    original: OriginalIssuerEvidenceV1,
    normalized_field: str,
    *,
    security_id: str | None = None,
) -> LeaseLiabilitySelection:
    if lease_liability_concept(original, normalized_field) is None:
        return LeaseLiabilitySelection(
            reason_codes=("MAPPING_LEASE_SCOPE_UNSUPPORTED",)
        )
    concept = _CONCEPTS[normalized_field]
    noncurrent = normalized_field.startswith("long_term_")
    facts = tuple(sorted(original.report.facts, key=sha256_digest))
    current_facts = tuple(
        fact
        for fact in facts
        if fact.concept == concept and fact.dimensions == _CURRENT_LOCATION
    )
    if any(
        not _eligible(f, original.source.cik, location="current") for f in current_facts
    ):
        return LeaseLiabilitySelection(
            reason_codes=("MAPPING_LEASE_COMPONENT_INVALID",)
        )
    selected: list[ParsedXbrlFactV1] = []
    periods: list[AccountingPeriodRuleV1] = []
    for instant in sorted({f.instant for f in current_facts if f.instant is not None}):
        if original.report_period_end is None or instant > original.report_period_end:
            return LeaseLiabilitySelection(
                reason_codes=("MAPPING_PERIOD_AFTER_ORIGINAL",)
            )
        current, reason = _one(
            tuple(f for f in current_facts if f.instant == instant),
            original.source.cik,
            location="current",
        )
        if reason is not None:
            return LeaseLiabilitySelection(reason_codes=(reason,))
        assert current is not None
        components = [
            AccountingComponentV1(
                parsed_fact_digest=sha256_digest(current),
                sign=-1 if noncurrent else 1,
                balance_sheet_location="other_current_liabilities",
            )
        ]
        observations = [current]
        totals = tuple(
            f
            for f in facts
            if f.concept == concept and f.instant == instant and not f.dimensions
        )
        if noncurrent or totals:
            total, reason = _one(
                totals,
                original.source.cik,
            )
            if reason is not None:
                return LeaseLiabilitySelection(reason_codes=(reason,))
            assert total is not None
            if total.namespace_uri != current.namespace_uri:
                return LeaseLiabilitySelection(
                    reason_codes=("MAPPING_LEASE_COMPONENT_INVALID",)
                )
            if Decimal(current.value) > Decimal(total.value):
                return LeaseLiabilitySelection(
                    reason_codes=("MAPPING_LEASE_RESIDUAL_INVALID",)
                )
        if noncurrent:
            assert total is not None
            components.insert(
                0, AccountingComponentV1(parsed_fact_digest=sha256_digest(total))
            )
            observations.insert(0, total)
        selected.extend(observations)
        periods.append(
            AccountingPeriodRuleV1(
                period=AccountingPeriodV1(period_end=instant, instant=True),
                disposition="derived" if noncurrent else "classified",
                components=tuple(components),
                rationale=_POLICY,
            )
        )
    rules: AccountingRoleRules = IssuerAccountingRoleRuleSetV1(
        policy_version=_POLICY,
        normalized_field=normalized_field,
        issuer_id=original.source.cik,
        accession_number=original.source.accession_number,
        raw_content_hash=original.source.content_hash,
        parser_input_hash=original.source.parser_input_hash,
        parser_fact_digest=fact_semantic_digest(original.report),
        unit="iso4217:USD",
        currency="USD",
        periods=tuple(periods),
    )
    direct_concept = concept + ("Noncurrent" if noncurrent else "Current")
    for period in periods:
        refs = set(period.source_references())
        observations_for_period = tuple(f for f in selected if sha256_digest(f) in refs)
        try:
            value = evaluate_period_rule(rules, period, observations_for_period)
        except AccountingRoleError as error:
            return LeaseLiabilitySelection(reason_codes=(error.code,))
        if value is None or value < 0:
            return LeaseLiabilitySelection(
                reason_codes=("MAPPING_LEASE_RESIDUAL_INVALID",)
            )
        alternatives: tuple[tuple[str, Literal["noncurrent"] | None], ...] = (
            ((direct_concept, None), (concept, "noncurrent"))
            if noncurrent
            else ((direct_concept, None),)
        )
        for alternate_concept, location in alternatives:
            matches = tuple(
                f
                for f in facts
                if f.concept == alternate_concept
                and f.instant == period.period.period_end
                and f.dimensions == _LOCATIONS[location]
            )
            if not matches:
                continue
            observation, reason = _one(matches, original.source.cik, location=location)
            if reason is not None:
                return LeaseLiabilitySelection(reason_codes=(reason,))
            assert observation is not None
            if observation.namespace_uri != observations_for_period[0].namespace_uri:
                return LeaseLiabilitySelection(
                    reason_codes=("MAPPING_LEASE_COMPONENT_INVALID",)
                )
            if Decimal(observation.value) != value:
                return LeaseLiabilitySelection(
                    reason_codes=("MAPPING_OBSERVATION_CONFLICT",)
                )
    if security_id is not None:
        rules = AccountingRoleRuleSetV1.model_validate(
            {
                **rules.model_dump(exclude={"protocol", "security_id"}),
                "security_id": security_id,
            }
        )
    return LeaseLiabilitySelection(rules=rules, selected=tuple(selected))
