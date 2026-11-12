"""Original-bound zero residual of an exhaustive noncurrent liability partition."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import re

from .accounting_roles import (
    AccountingComponentV1,
    AccountingPeriodRuleV1,
    AccountingPeriodV1,
    AccountingRoleRules,
    AccountingRoleRuleSetV1,
    IssuerAccountingRoleRuleSetV1,
    evaluate_period_rule,
)
from .arelle_parser import ParsedXbrlFactV1, fact_semantic_digest
from .original_issuer import OriginalIssuerEvidenceV1
from .serialization import sha256_digest

NONCURRENT_LIABILITY_RESIDUAL = "registered:ZeroNoncurrentLiabilityResidual"
POLICY = "original-bound-zero-noncurrent-liability-residual-v1"
ROLES = frozenset(
    {"long_term_interest_bearing_debt", "long_term_finance_lease_liabilities"}
)
COMPONENTS = (
    ("us-gaap:Liabilities", 1),
    ("us-gaap:LiabilitiesCurrent", -1),
    ("us-gaap:OperatingLeaseLiabilityNoncurrent", -1),
)


@dataclass(frozen=True)
class OriginalClassification:
    source_hash: str
    fact_digest: str
    instants: tuple[date, ...]


# Complete original statements establish the nonnegative, unnetted partition.
# Only a zero residual can resolve both roles without allocating an unknown sum.
_ORIGINALS = {
    ("0000724910", "0001376474-23-000283"): OriginalClassification(
        "26d95888105590690531f4b3c4da8ca910e6aa4e315f6372ed51c55459b0b05c",
        "1ce5d69c3a2b560110b3cfffba644b15125475ce3531a99bdc5a5f5fd35ef90e",
        (date(2022, 3, 31), date(2023, 3, 31)),
    ),
    ("0000724910", "0001376474-24-000214"): OriginalClassification(
        "e337d87718577db631e61f5495c3c8f96304c0552161cb5054305967394c9dc6",
        "21c4ebca39e56c934edded6065b4ac78a0f451de96a540afe5d49726c53b01c1",
        (date(2023, 3, 31), date(2024, 3, 31)),
    ),
}


@dataclass(frozen=True)
class NoncurrentLiabilitySelection:
    rules: AccountingRoleRules | None = None
    selected: tuple[ParsedXbrlFactV1, ...] = ()
    reason_codes: tuple[str, ...] = ()


def select_registered_noncurrent_liabilities(
    original: OriginalIssuerEvidenceV1,
    normalized_field: str,
    *,
    security_id: str | None = None,
) -> NoncurrentLiabilitySelection:
    source = original.source
    entry = _ORIGINALS.get((source.cik, source.accession_number))
    if (
        normalized_field not in ROLES
        or entry is None
        or source.content_hash != entry.source_hash
    ):
        return NoncurrentLiabilitySelection(
            reason_codes=("MAPPING_NONCURRENT_SCOPE_UNREVIEWED",)
        )
    if fact_semantic_digest(original.report) != entry.fact_digest:
        return NoncurrentLiabilitySelection(
            reason_codes=("MAPPING_NONCURRENT_SOURCE_MISMATCH",)
        )
    selected = []
    periods = []
    for instant in entry.instants:
        if original.report_period_end is None or instant > original.report_period_end:
            return NoncurrentLiabilitySelection(
                reason_codes=("MAPPING_PERIOD_AFTER_ORIGINAL",)
            )
        components = []
        observations = []
        for concept, sign in COMPONENTS:
            matches = tuple(
                fact
                for fact in sorted(original.report.facts, key=sha256_digest)
                if fact.concept == concept
                and fact.instant == instant
                and not fact.dimensions
            )
            if not matches:
                return NoncurrentLiabilitySelection(
                    reason_codes=("MAPPING_NONCURRENT_COMPONENT_MISSING",)
                )
            if any(not _eligible(fact, source.cik) for fact in matches):
                return NoncurrentLiabilitySelection(
                    reason_codes=("MAPPING_NONCURRENT_COMPONENT_INVALID",)
                )
            if len({(Decimal(fact.value), fact.decimals) for fact in matches}) != 1:
                return NoncurrentLiabilitySelection(
                    reason_codes=("MAPPING_OBSERVATION_CONFLICT",)
                )
            fact = matches[0]
            observations.append(fact)
            components.append(
                AccountingComponentV1(
                    parsed_fact_digest=sha256_digest(fact),
                    sign=1 if sign == 1 else -1,
                )
            )
        if len({fact.namespace_uri for fact in observations}) != 1:
            return NoncurrentLiabilitySelection(
                reason_codes=("MAPPING_NONCURRENT_COMPONENT_INVALID",)
            )
        selected.extend(observations)
        periods.append(
            AccountingPeriodRuleV1(
                period=AccountingPeriodV1(period_end=instant, instant=True),
                disposition="derived",
                components=tuple(components),
                rationale=POLICY,
            )
        )
    rules: AccountingRoleRules = IssuerAccountingRoleRuleSetV1(
        policy_version=POLICY,
        normalized_field=normalized_field,
        issuer_id=source.cik,
        accession_number=source.accession_number,
        raw_content_hash=source.content_hash,
        parser_input_hash=source.parser_input_hash,
        parser_fact_digest=entry.fact_digest,
        unit="iso4217:USD",
        currency="USD",
        periods=tuple(periods),
    )
    # Use the existing accounting evaluator, including its fixed Decimal context.
    for period in rules.periods:
        references = set(period.source_references())
        observations_for_period = tuple(
            fact for fact in selected if sha256_digest(fact) in references
        )
        if evaluate_period_rule(rules, period, observations_for_period) != Decimal(0):
            return NoncurrentLiabilitySelection(
                reason_codes=("MAPPING_NONCURRENT_RESIDUAL_UNALLOCATED",)
            )
    if security_id is not None:
        rules = AccountingRoleRuleSetV1.model_validate(
            {
                **rules.model_dump(exclude={"protocol", "security_id"}),
                "security_id": security_id,
            }
        )
    return NoncurrentLiabilitySelection(rules=rules, selected=tuple(selected))


def _eligible(fact: ParsedXbrlFactV1, cik: str) -> bool:
    try:
        amount = Decimal(fact.value)
    except InvalidOperation:
        return False
    return (
        fact.is_numeric
        and amount.is_finite()
        and amount >= 0
        and fact.unit == "iso4217:USD"
        and fact.period_start is None
        and fact.period_end is None
        and fact.consolidation_scope == "consolidated"
        and fact.security_scope in {"issuer", "consolidated", "unspecified"}
        and re.fullmatch(
            r"http://(?:fasb\.org|xbrl\.us)/us-gaap/\d{4}(?:-\d{2}-\d{2})?",
            fact.namespace_uri or "",
        )
        is not None
        and fact.entity_scheme == "http://www.sec.gov/CIK"
        and (fact.entity_identifier or "").lstrip("0") == cik.lstrip("0")
        and (
            fact.decimals == "INF"
            or re.fullmatch(r"[0-9]+", fact.decimals or "") is not None
        )
    )
