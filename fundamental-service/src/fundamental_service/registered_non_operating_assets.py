"""Original-bound investment balances excluding cash and operating assets."""

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

NON_OPERATING_ASSETS = "registered:InvestmentAssetsExcludingCash"
POLICY = "original-bound-investment-assets-v1"
COMPONENT_CONCEPTS = (
    "us-gaap:MarketableSecuritiesCurrent",
    "us-gaap:MarketableSecuritiesNoncurrent",
    "fil:MarketableSecuritiesAccruedInterestReceivable",
)


@dataclass(frozen=True)
class OriginalClassification:
    source_hash: str
    fact_digest: str
    instants: tuple[date, ...]


# The complete investment/cash classification is in accounting-role-evidence.md.
_ORIGINALS = {
    ("0000724910", "0001376474-24-000214"): OriginalClassification(
        "e337d87718577db631e61f5495c3c8f96304c0552161cb5054305967394c9dc6",
        "21c4ebca39e56c934edded6065b4ac78a0f451de96a540afe5d49726c53b01c1",
        (date(2023, 3, 31), date(2024, 3, 31)),
    ),
}


@dataclass(frozen=True)
class NonOperatingAssetSelection:
    rules: AccountingRoleRules | None = None
    selected: tuple[ParsedXbrlFactV1, ...] = ()
    reason_codes: tuple[str, ...] = ()


def select_registered_non_operating_assets(
    original: OriginalIssuerEvidenceV1, *, security_id: str | None = None
) -> NonOperatingAssetSelection:
    source = original.source
    entry = _ORIGINALS.get((source.cik, source.accession_number))
    if entry is None or source.content_hash != entry.source_hash:
        return NonOperatingAssetSelection(
            reason_codes=("MAPPING_NON_OPERATING_ASSET_SCOPE_UNREVIEWED",)
        )
    if fact_semantic_digest(original.report) != entry.fact_digest:
        return NonOperatingAssetSelection(
            reason_codes=("MAPPING_NON_OPERATING_ASSET_SOURCE_MISMATCH",)
        )
    selected: list[ParsedXbrlFactV1] = []
    periods: list[AccountingPeriodRuleV1] = []
    for instant in entry.instants:
        components = []
        for concept in COMPONENT_CONCEPTS:
            matches = tuple(
                f
                for f in sorted(original.report.facts, key=sha256_digest)
                if f.concept == concept and f.instant == instant and not f.dimensions
            )
            if not matches:
                return NonOperatingAssetSelection(
                    reason_codes=("MAPPING_NON_OPERATING_ASSET_COMPONENT_MISSING",)
                )
            if any(not _eligible(f, source.cik) for f in matches):
                return NonOperatingAssetSelection(
                    reason_codes=("MAPPING_NON_OPERATING_ASSET_COMPONENT_INVALID",)
                )
            if len({(Decimal(f.value), f.decimals) for f in matches}) != 1:
                return NonOperatingAssetSelection(
                    reason_codes=("MAPPING_OBSERVATION_CONFLICT",)
                )
            fact = matches[0]
            selected.append(fact)
            components.append(
                AccountingComponentV1(parsed_fact_digest=sha256_digest(fact))
            )
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
        normalized_field="non_operating_assets",
        issuer_id=source.cik,
        accession_number=source.accession_number,
        raw_content_hash=source.content_hash,
        parser_input_hash=source.parser_input_hash,
        parser_fact_digest=fact_semantic_digest(original.report),
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
    return NonOperatingAssetSelection(rules=rules, selected=tuple(selected))


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
        and fact.entity_scheme == "http://www.sec.gov/CIK"
        and (fact.entity_identifier or "").lstrip("0") == cik.lstrip("0")
        and (
            fact.decimals == "INF"
            or re.fullmatch(r"-?[0-9]+", fact.decimals or "") is not None
        )
    )
