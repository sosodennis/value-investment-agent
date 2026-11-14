"""Original-bound classification of contract revenue as statement total revenue."""

from dataclasses import dataclass
from datetime import date

from .arelle_parser import ParsedXbrlFactV1, fact_semantic_digest
from .original_issuer import (
    OriginalIssuerEvidenceV1,
    parser_input_matches_registered_original,
)
from .serialization import sha256_digest

CONTRACT_REVENUE = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"


@dataclass(frozen=True)
class OriginalRevenueScope:
    parser_input_hash: str
    fact_digest: str
    annual_periods: tuple[tuple[date, date], ...]


# These complete consolidated income statements label the base-context row
# "Total revenue". The contract-revenue QName alone cannot establish this scope.
_ORIGINALS = {
    ("0000789019", "0000950170-25-100235"): OriginalRevenueScope(
        "7475ad82dc11fc5e27bdbea995b44da0545778b966725ba42524953e4ac9ce2c",
        "f85516d9a48b94101325a022d724dc2176c27550ef604f3abfcabd3831cdb4ac",
        tuple((date(year - 1, 7, 1), date(year, 6, 30)) for year in (2023, 2024, 2025)),
    ),
    ("0000789019", "0001193125-26-323660"): OriginalRevenueScope(
        "4561138eb81082fd06a693e6a2036eeae14e321d0c75a77aee5c28f1d4dc6d1d",
        "f9abe2c5126979fd28814e9ac4088241833cf4c957f91e363141bbc7ffbde0f7",
        tuple((date(year - 1, 7, 1), date(year, 6, 30)) for year in (2024, 2025, 2026)),
    ),
}


def registered_revenue_concept(original: OriginalIssuerEvidenceV1) -> str | None:
    if (original.source.cik, original.source.accession_number) in _ORIGINALS:
        return CONTRACT_REVENUE
    return None


@dataclass(frozen=True)
class RevenueSelection:
    selected: tuple[ParsedXbrlFactV1, ...] = ()
    rejected: tuple[tuple[ParsedXbrlFactV1, str], ...] = ()
    reason_codes: tuple[str, ...] = ()


def select_registered_revenue(original: OriginalIssuerEvidenceV1) -> RevenueSelection:
    entry = _ORIGINALS.get((original.source.cik, original.source.accession_number))
    if entry is None:
        return RevenueSelection(reason_codes=("MAPPING_REVENUE_SCOPE_UNREVIEWED",))
    if (
        not parser_input_matches_registered_original(original, entry.parser_input_hash)
        or fact_semantic_digest(original.report) != entry.fact_digest
    ):
        return RevenueSelection(reason_codes=("MAPPING_REVENUE_SOURCE_MISMATCH",))
    selected = []
    rejected = []
    for fact in sorted(original.report.facts, key=sha256_digest):
        if fact.concept != CONTRACT_REVENUE:
            continue
        if (fact.period_start, fact.period_end) in entry.annual_periods:
            selected.append(fact)
        else:
            rejected.append((fact, "MAPPING_REVENUE_PERIOD_SCOPE_UNREVIEWED"))
    return RevenueSelection(selected=tuple(selected), rejected=tuple(rejected))
