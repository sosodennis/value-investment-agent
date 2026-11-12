"""Continuing cash-capex scope for explicitly classified original fact sets."""

from dataclasses import dataclass

from .arelle_parser import ParsedXbrlFactV1, fact_semantic_digest
from .original_issuer import OriginalIssuerEvidenceV1
from .serialization import sha256_digest

CAPITAL_EXPENDITURE = "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"


@dataclass(frozen=True)
class OriginalCapitalExpenditureScope:
    source_hash: str
    fact_digest: str
    continuing_years: tuple[int, ...]


# The original discontinued-operations note combines cash-flow scopes. Only the
# post-disposal years are classified; equal cash/segment totals do not classify
# the disposal year. See docs/accounting-role-evidence.md and issue #415.
_ORIGINALS = {
    ("0001282637", "0001282637-15-000004"): OriginalCapitalExpenditureScope(
        "5e9510723b0fb3a20bc9a4f77d14cdbc984dffb2c327fb98388c60ae98ee5f7d",
        "fb3dfe48db99cd56e547a4b24349783f7d73f1b5fac7e0c4fb4d0a741ae591b3",
        (2014,),
    ),
    ("0001282637", "0001282637-16-000028"): OriginalCapitalExpenditureScope(
        "06be302baf2ecf9ff95ab87243df1f2a1cd63e9ababc969b89c4764be794e380",
        "87cdac62baffd9c6810d93bec52c418fef016931c445fca0771ec597d3bef5f0",
        (2014, 2015),
    ),
    ("0001282637", "0001282637-17-000005"): OriginalCapitalExpenditureScope(
        "19247250d691d0625172f45ab484b7e6ad44b2b82462e6aff3ed956f03576422",
        "67ab534c782b3412c77d57cdc2e6dd42a2809924488d85ea6d975a0d09c706a1",
        (2014, 2015, 2016),
    ),
    ("0000724910", "0001376474-23-000283"): OriginalCapitalExpenditureScope(
        "26d95888105590690531f4b3c4da8ca910e6aa4e315f6372ed51c55459b0b05c",
        "1ce5d69c3a2b560110b3cfffba644b15125475ce3531a99bdc5a5f5fd35ef90e",
        (2022, 2023),
    ),
    ("0000724910", "0001376474-24-000214"): OriginalCapitalExpenditureScope(
        "e337d87718577db631e61f5495c3c8f96304c0552161cb5054305967394c9dc6",
        "21c4ebca39e56c934edded6065b4ac78a0f451de96a540afe5d49726c53b01c1",
        (2023, 2024),
    ),
}


@dataclass(frozen=True)
class CapitalExpenditureSelection:
    selected: tuple[ParsedXbrlFactV1, ...] = ()
    rejected: tuple[tuple[ParsedXbrlFactV1, str], ...] = ()
    reason_codes: tuple[str, ...] = ()


def select_registered_capital_expenditure(
    original: OriginalIssuerEvidenceV1,
) -> CapitalExpenditureSelection:
    """Bind period classification to original bytes and the complete fact set."""
    source = original.source
    entry = _ORIGINALS.get((source.cik, source.accession_number))
    if entry is None or source.content_hash != entry.source_hash:
        return CapitalExpenditureSelection(
            reason_codes=("MAPPING_CAPEX_SCOPE_UNREVIEWED",)
        )
    if fact_semantic_digest(original.report) != entry.fact_digest:
        return CapitalExpenditureSelection(
            reason_codes=("MAPPING_CAPEX_SOURCE_MISMATCH",)
        )
    selected = []
    rejected = []
    for fact in sorted(original.report.facts, key=sha256_digest):
        if fact.concept != CAPITAL_EXPENDITURE:
            continue
        if (
            fact.period_end is not None
            and fact.period_end.year in entry.continuing_years
        ):
            selected.append(fact)
        else:
            rejected.append((fact, "MAPPING_CAPEX_CONTINUING_SCOPE_UNRESOLVED"))
    return CapitalExpenditureSelection(
        selected=tuple(selected), rejected=tuple(rejected)
    )
