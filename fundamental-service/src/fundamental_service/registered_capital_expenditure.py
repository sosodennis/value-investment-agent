"""Continuing cash-capex scope for explicitly classified original fact sets."""

from dataclasses import dataclass

from .arelle_parser import ParsedXbrlFactV1, fact_semantic_digest
from .original_issuer import (
    OriginalIssuerEvidenceV1,
    parser_input_matches_registered_original,
)
from .serialization import sha256_digest

CAPITAL_EXPENDITURE = "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"


@dataclass(frozen=True)
class OriginalCapitalExpenditureScope:
    parser_input_hash: str
    fact_digest: str
    continuing_years: tuple[int, ...]


# The original discontinued-operations note combines cash-flow scopes. Only the
# post-disposal years are classified; equal cash/segment totals do not classify
# the disposal year. See docs/accounting-role-evidence.md and issue #415.
_ORIGINALS = {
    ("0001282637", "0001282637-15-000004"): OriginalCapitalExpenditureScope(
        "d39dc0bc0bfe564d802422b7ece4d64845bd58e194208e2caccb0b7a9c72a2df",
        "fb3dfe48db99cd56e547a4b24349783f7d73f1b5fac7e0c4fb4d0a741ae591b3",
        (2014,),
    ),
    ("0001282637", "0001282637-16-000028"): OriginalCapitalExpenditureScope(
        "90b1f0fddb61415dab858235894745b2c2808ee598ac0594b0a28010b808e14c",
        "87cdac62baffd9c6810d93bec52c418fef016931c445fca0771ec597d3bef5f0",
        (2014, 2015),
    ),
    ("0001282637", "0001282637-17-000005"): OriginalCapitalExpenditureScope(
        "baed1535c218e094d38daa1aca950bc29048a1935596d649a68d53348109a1b5",
        "67ab534c782b3412c77d57cdc2e6dd42a2809924488d85ea6d975a0d09c706a1",
        (2014, 2015, 2016),
    ),
    ("0000724910", "0001376474-23-000283"): OriginalCapitalExpenditureScope(
        "fbab4403625d475d594960fc11a39ef1be6dd079a854647c11243dba9bdb3469",
        "1ce5d69c3a2b560110b3cfffba644b15125475ce3531a99bdc5a5f5fd35ef90e",
        (2022, 2023),
    ),
    ("0000724910", "0001376474-24-000214"): OriginalCapitalExpenditureScope(
        "9b08f22245c6dbe458fdc90ff1484e87af5e8900b41774be6f4d0d7d7bd8ae57",
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
    """Bind period classification to validated parser input and complete facts."""
    source = original.source
    entry = _ORIGINALS.get((source.cik, source.accession_number))
    if entry is None or not parser_input_matches_registered_original(
        original, entry.parser_input_hash
    ):
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
