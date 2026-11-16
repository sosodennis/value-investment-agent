"""Original-bound zero residuals of exhaustive liability principal partitions."""

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
from .original_issuer import (
    OriginalIssuerEvidenceV1,
    parser_input_matches_registered_original,
)
from .serialization import sha256_digest

NONCURRENT_LIABILITY_RESIDUAL = "registered:ZeroNoncurrentLiabilityResidual"
CURRENT_LIABILITY_RESIDUAL = "registered:ZeroCurrentLiabilityPrincipalResidual"


@dataclass(frozen=True)
class LiabilityPartition:
    concept: str
    policy_version: str
    reason_prefix: str
    roles: frozenset[str]
    components: tuple[tuple[str, int], ...]


PARTITIONS = (
    LiabilityPartition(
        NONCURRENT_LIABILITY_RESIDUAL,
        "original-bound-zero-noncurrent-liability-residual-v1",
        "MAPPING_NONCURRENT",
        frozenset(
            {"long_term_interest_bearing_debt", "long_term_finance_lease_liabilities"}
        ),
        (
            ("us-gaap:Liabilities", 1),
            ("us-gaap:LiabilitiesCurrent", -1),
            ("us-gaap:OperatingLeaseLiabilityNoncurrent", -1),
        ),
    ),
    LiabilityPartition(
        CURRENT_LIABILITY_RESIDUAL,
        "original-bound-zero-current-liability-principal-residual-v1",
        "MAPPING_CURRENT",
        frozenset(
            {"current_interest_bearing_debt", "current_finance_lease_liabilities"}
        ),
        (
            ("us-gaap:LiabilitiesCurrent", 1),
            ("us-gaap:AccountsPayableCurrent", -1),
            ("us-gaap:AccruedLiabilitiesCurrent", -1),
            ("us-gaap:OperatingLeaseLiabilityCurrent", -1),
        ),
    ),
)
ROLES = frozenset(role for partition in PARTITIONS for role in partition.roles)


def liability_residual_concept(normalized_field: str) -> str:
    return next(p.concept for p in PARTITIONS if normalized_field in p.roles)


@dataclass(frozen=True)
class OriginalClassification:
    parser_input_hash: str
    fact_digest: str
    instants: tuple[date, ...]


# The current partition classifies trade payables and cost accruals separately
# from financing principal. It does not classify the entire accrued line as
# operating or establish annual finance-lease expense or instrument absence.
# Only these complete originals establish the unnetted, nonnegative partitions.
_ORIGINALS = {
    ("0000724910", "0001376474-23-000283"): OriginalClassification(
        "fbab4403625d475d594960fc11a39ef1be6dd079a854647c11243dba9bdb3469",
        "1ce5d69c3a2b560110b3cfffba644b15125475ce3531a99bdc5a5f5fd35ef90e",
        (date(2022, 3, 31), date(2023, 3, 31)),
    ),
    ("0000724910", "0001376474-24-000214"): OriginalClassification(
        "9b08f22245c6dbe458fdc90ff1484e87af5e8900b41774be6f4d0d7d7bd8ae57",
        "21c4ebca39e56c934edded6065b4ac78a0f451de96a540afe5d49726c53b01c1",
        (date(2023, 3, 31), date(2024, 3, 31)),
    ),
}


@dataclass(frozen=True)
class LiabilityResidualSelection:
    rules: AccountingRoleRules | None = None
    selected: tuple[ParsedXbrlFactV1, ...] = ()
    reason_codes: tuple[str, ...] = ()


def select_registered_liability_residual(
    original: OriginalIssuerEvidenceV1,
    normalized_field: str,
    *,
    security_id: str | None = None,
) -> LiabilityResidualSelection:
    source = original.source
    partition = next((p for p in PARTITIONS if normalized_field in p.roles), None)
    if partition is None:
        return LiabilityResidualSelection(
            reason_codes=("MAPPING_LIABILITY_ROLE_UNSUPPORTED",)
        )
    prefix = partition.reason_prefix
    entry = _ORIGINALS.get((source.cik, source.accession_number))
    if entry is None or not parser_input_matches_registered_original(
        original, entry.parser_input_hash
    ):
        return LiabilityResidualSelection(reason_codes=(f"{prefix}_SCOPE_UNREVIEWED",))
    if fact_semantic_digest(original.report) != entry.fact_digest:
        return LiabilityResidualSelection(reason_codes=(f"{prefix}_SOURCE_MISMATCH",))
    selected = []
    periods = []
    for instant in entry.instants:
        if original.report_period_end is None or instant > original.report_period_end:
            return LiabilityResidualSelection(
                reason_codes=("MAPPING_PERIOD_AFTER_ORIGINAL",)
            )
        components = []
        observations = []
        namespaces: set[str | None] = set()
        for concept, sign in partition.components:
            matches = tuple(
                fact
                for fact in sorted(original.report.facts, key=sha256_digest)
                if fact.concept == concept
                and fact.instant == instant
                and not fact.dimensions
            )
            if not matches:
                return LiabilityResidualSelection(
                    reason_codes=(f"{prefix}_COMPONENT_MISSING",)
                )
            if any(not _eligible(fact, source.cik) for fact in matches):
                return LiabilityResidualSelection(
                    reason_codes=(f"{prefix}_COMPONENT_INVALID",)
                )
            namespaces.update(fact.namespace_uri for fact in matches)
            if len({(Decimal(fact.value), fact.decimals) for fact in matches}) != 1:
                return LiabilityResidualSelection(
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
        if len(namespaces) != 1:
            return LiabilityResidualSelection(
                reason_codes=(f"{prefix}_COMPONENT_INVALID",)
            )
        selected.extend(observations)
        periods.append(
            AccountingPeriodRuleV1(
                period=AccountingPeriodV1(period_end=instant, instant=True),
                disposition="derived",
                components=tuple(components),
                rationale=partition.policy_version,
            )
        )
    rules: AccountingRoleRules = IssuerAccountingRoleRuleSetV1(
        policy_version=partition.policy_version,
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
            return LiabilityResidualSelection(
                reason_codes=(f"{prefix}_RESIDUAL_UNALLOCATED",)
            )
    if security_id is not None:
        rules = AccountingRoleRuleSetV1.model_validate(
            {
                **rules.model_dump(exclude={"protocol", "security_id"}),
                "security_id": security_id,
            }
        )
    return LiabilityResidualSelection(rules=rules, selected=tuple(selected))


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
