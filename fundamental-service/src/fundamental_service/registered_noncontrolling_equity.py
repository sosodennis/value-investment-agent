"""Original-bound noncontrolling equity from reported total and parent equity."""

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
)
from .arelle_parser import fact_semantic_digest, ParsedXbrlFactV1
from .original_issuer import OriginalIssuerEvidenceV1
from .serialization import sha256_digest

NONCONTROLLING_EQUITY = "registered:NoncontrollingEquityFromReportedEquity"
POLICY = "original-bound-noncontrolling-equity-v1"
TOTAL_EQUITY = (
    "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
)
PARENT_EQUITY = "us-gaap:StockholdersEquity"


@dataclass(frozen=True)
class OriginalClassification:
    source_hash: str
    fact_digest: str
    instants: tuple[date, ...]


# These complete statements have no temporary-equity claims outside this pair.
# The classification and taxonomy definitions are in accounting-role-evidence.md.
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
class NoncontrollingEquitySelection:
    rules: AccountingRoleRules | None = None
    selected: tuple[ParsedXbrlFactV1, ...] = ()
    reason_codes: tuple[str, ...] = ()


def select_registered_noncontrolling_equity(
    original: OriginalIssuerEvidenceV1, *, security_id: str | None = None
) -> NoncontrollingEquitySelection:
    source = original.source
    entry = _ORIGINALS.get((source.cik, source.accession_number))
    if entry is None or source.content_hash != entry.source_hash:
        return NoncontrollingEquitySelection(
            reason_codes=("MAPPING_NONCONTROLLING_SCOPE_UNREVIEWED",)
        )
    if fact_semantic_digest(original.report) != entry.fact_digest:
        return NoncontrollingEquitySelection(
            reason_codes=("MAPPING_NONCONTROLLING_SOURCE_MISMATCH",)
        )
    selected = []
    periods = []
    for instant in entry.instants:
        if original.report_period_end is None or instant > original.report_period_end:
            return NoncontrollingEquitySelection(
                reason_codes=("MAPPING_PERIOD_AFTER_ORIGINAL",)
            )
        pair = []
        for concept in (TOTAL_EQUITY, PARENT_EQUITY):
            matches = tuple(
                f
                for f in sorted(original.report.facts, key=sha256_digest)
                if f.concept == concept and f.instant == instant and not f.dimensions
            )
            if not matches:
                return NoncontrollingEquitySelection(
                    reason_codes=("MAPPING_NONCONTROLLING_COMPONENT_MISSING",)
                )
            if any(not _eligible(f, source.cik) for f in matches):
                return NoncontrollingEquitySelection(
                    reason_codes=("MAPPING_NONCONTROLLING_COMPONENT_INVALID",)
                )
            if len({(Decimal(f.value), f.decimals) for f in matches}) != 1:
                return NoncontrollingEquitySelection(
                    reason_codes=("MAPPING_OBSERVATION_CONFLICT",)
                )
            pair.append(matches[0])
        total, parent = pair
        if total.namespace_uri != parent.namespace_uri or Decimal(
            total.value
        ) < Decimal(parent.value):
            return NoncontrollingEquitySelection(
                reason_codes=("MAPPING_NONCONTROLLING_EQUITY_INCONSISTENT",)
            )
        selected.extend(pair)
        periods.append(
            AccountingPeriodRuleV1(
                period=AccountingPeriodV1(period_end=instant, instant=True),
                disposition="derived",
                components=(
                    AccountingComponentV1(parsed_fact_digest=sha256_digest(total)),
                    AccountingComponentV1(
                        parsed_fact_digest=sha256_digest(parent), sign=-1
                    ),
                ),
                rationale=POLICY,
            )
        )
    rules: AccountingRoleRules = IssuerAccountingRoleRuleSetV1(
        policy_version=POLICY,
        normalized_field="noncontrolling_interests",
        issuer_id=source.cik,
        accession_number=source.accession_number,
        raw_content_hash=source.content_hash,
        parser_input_hash=source.parser_input_hash,
        parser_fact_digest=entry.fact_digest,
        unit="iso4217:USD",
        currency="USD",
        periods=tuple(periods),
    )
    if security_id is not None:
        rules = AccountingRoleRuleSetV1.model_validate(
            {
                **rules.model_dump(exclude={"protocol", "security_id"}),
                "security_id": security_id,
            }
        )
    return NoncontrollingEquitySelection(rules=rules, selected=tuple(selected))


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
