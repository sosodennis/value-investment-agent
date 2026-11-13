"""Original-bound investment and cash classifications for distinct input roles."""

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
from .original_issuer import (
    OriginalIssuerEvidenceV1,
    parser_input_matches_registered_original,
)
from .serialization import sha256_digest

NON_OPERATING_ASSETS = "registered:InvestmentAssetsExcludingCash"
CASH_AND_SHORT_TERM_INVESTMENTS = "registered:CashAndCurrentInvestmentAssets"
COMPONENT_CONCEPTS = (
    "us-gaap:MarketableSecuritiesCurrent",
    "us-gaap:MarketableSecuritiesNoncurrent",
    "fil:MarketableSecuritiesAccruedInterestReceivable",
)
CASH_SHORT_TERM_COMPONENTS = (
    "us-gaap:CashAndCashEquivalentsAtCarryingValue",
    "us-gaap:MarketableSecuritiesCurrent",
)


@dataclass(frozen=True)
class InvestmentClassification:
    concept: str
    policy_version: str
    reason_prefix: str
    components: tuple[str, ...]


_CLASSIFICATIONS = {
    "non_operating_assets": InvestmentClassification(
        NON_OPERATING_ASSETS,
        "original-bound-investment-assets-v1",
        "MAPPING_NON_OPERATING_ASSET",
        COMPONENT_CONCEPTS,
    ),
    "cash_and_short_term_investments": InvestmentClassification(
        CASH_AND_SHORT_TERM_INVESTMENTS,
        "original-bound-cash-current-investment-exclusion-v1",
        "MAPPING_INVESTMENT_EXCLUSION",
        CASH_SHORT_TERM_COMPONENTS,
    ),
}
ROLES = frozenset(_CLASSIFICATIONS)


def investment_asset_concept(normalized_field: str) -> str:
    return _CLASSIFICATIONS[normalized_field].concept


@dataclass(frozen=True)
class OriginalClassification:
    parser_input_hash: str
    fact_digest: str
    instants: tuple[date, ...]
    roles: frozenset[str]


# The complete investment/cash classification is in accounting-role-evidence.md.
_ORIGINALS = {
    ("0000724910", "0001376474-23-000283"): OriginalClassification(
        "fbab4403625d475d594960fc11a39ef1be6dd079a854647c11243dba9bdb3469",
        "1ce5d69c3a2b560110b3cfffba644b15125475ce3531a99bdc5a5f5fd35ef90e",
        (date(2022, 3, 31), date(2023, 3, 31)),
        frozenset({"cash_and_short_term_investments"}),
    ),
    ("0000724910", "0001376474-24-000214"): OriginalClassification(
        "9b08f22245c6dbe458fdc90ff1484e87af5e8900b41774be6f4d0d7d7bd8ae57",
        "21c4ebca39e56c934edded6065b4ac78a0f451de96a540afe5d49726c53b01c1",
        (date(2023, 3, 31), date(2024, 3, 31)),
        ROLES,
    ),
}


@dataclass(frozen=True)
class InvestmentAssetSelection:
    rules: AccountingRoleRules | None = None
    selected: tuple[ParsedXbrlFactV1, ...] = ()
    reason_codes: tuple[str, ...] = ()


def select_registered_investment_assets(
    original: OriginalIssuerEvidenceV1,
    normalized_field: str,
    *,
    security_id: str | None = None,
) -> InvestmentAssetSelection:
    classification = _CLASSIFICATIONS.get(normalized_field)
    if classification is None:
        return InvestmentAssetSelection(
            reason_codes=("MAPPING_INVESTMENT_ROLE_UNSUPPORTED",)
        )
    prefix = classification.reason_prefix
    source = original.source
    entry = _ORIGINALS.get((source.cik, source.accession_number))
    if (
        entry is None
        or not parser_input_matches_registered_original(
            original, entry.parser_input_hash
        )
        or normalized_field not in entry.roles
    ):
        return InvestmentAssetSelection(reason_codes=(f"{prefix}_SCOPE_UNREVIEWED",))
    if fact_semantic_digest(original.report) != entry.fact_digest:
        return InvestmentAssetSelection(reason_codes=(f"{prefix}_SOURCE_MISMATCH",))
    selected: list[ParsedXbrlFactV1] = []
    periods: list[AccountingPeriodRuleV1] = []
    for instant in entry.instants:
        if original.report_period_end is None or instant > original.report_period_end:
            return InvestmentAssetSelection(
                reason_codes=("MAPPING_PERIOD_AFTER_ORIGINAL",)
            )
        components = []
        gaap_namespaces: set[str | None] = set()
        for concept in classification.components:
            matches = tuple(
                f
                for f in sorted(original.report.facts, key=sha256_digest)
                if f.concept == concept and f.instant == instant and not f.dimensions
            )
            if not matches:
                return InvestmentAssetSelection(
                    reason_codes=(f"{prefix}_COMPONENT_MISSING",)
                )
            if any(not _eligible(f, source.cik, normalized_field) for f in matches):
                return InvestmentAssetSelection(
                    reason_codes=(f"{prefix}_COMPONENT_INVALID",)
                )
            if concept.startswith("us-gaap:"):
                gaap_namespaces.update(f.namespace_uri for f in matches)
            if len({(Decimal(f.value), f.decimals) for f in matches}) != 1:
                return InvestmentAssetSelection(
                    reason_codes=("MAPPING_OBSERVATION_CONFLICT",)
                )
            fact = matches[0]
            selected.append(fact)
            components.append(
                AccountingComponentV1(parsed_fact_digest=sha256_digest(fact))
            )
        if len(gaap_namespaces) != 1:
            return InvestmentAssetSelection(
                reason_codes=(f"{prefix}_COMPONENT_INVALID",)
            )
        periods.append(
            AccountingPeriodRuleV1(
                period=AccountingPeriodV1(period_end=instant, instant=True),
                disposition="derived",
                components=tuple(components),
                rationale=classification.policy_version,
            )
        )
    rules: AccountingRoleRules = IssuerAccountingRoleRuleSetV1(
        policy_version=classification.policy_version,
        normalized_field=normalized_field,
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
    return InvestmentAssetSelection(rules=rules, selected=tuple(selected))


def _eligible(fact: ParsedXbrlFactV1, cik: str, normalized_field: str) -> bool:
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
        and (
            not fact.concept.startswith("us-gaap:")
            or re.fullmatch(
                r"http://(?:fasb\.org|xbrl\.us)/us-gaap/\d{4}(?:-\d{2}-\d{2})?",
                fact.namespace_uri or "",
            )
            is not None
        )
        and fact.entity_scheme == "http://www.sec.gov/CIK"
        and (fact.entity_identifier or "").lstrip("0") == cik.lstrip("0")
        and (
            fact.decimals == "INF"
            or re.fullmatch(
                r"[0-9]+"
                if normalized_field == "cash_and_short_term_investments"
                else r"-?[0-9]+",
                fact.decimals or "",
            )
            is not None
        )
    )
