"""Reviewed primary-row scopes bound to immutable original filing bytes.

Only concepts and periods are registered; reported amounts come from validated
canonical facts. The matching primary rows are retained in the #494 source audit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .arelle_parser import ParsedXbrlFactV1
from .data_releases import DataReleaseError, ReleaseModel
from .registered_statement_row_registry import PRIMARY_STATEMENTS
from .original_issuer import OriginalIssuerEvidenceV1
from typing import Literal

CASH_STATEMENT_ROLES = frozenset(
    {
        "cash_flow_beginning_balance",
        "cash_flow_ending_balance",
        "net_change_in_cash",
        "effect_of_exchange_rates_on_cash",
    }
)


def registered_primary_concept(
    original: OriginalIssuerEvidenceV1, row_id: str
) -> str | None:
    scope = PRIMARY_STATEMENTS.get(
        (original.source.cik, original.source.accession_number)
    )
    return scope.concept_for(row_id) if scope is not None else None


def has_registered_primary_statement_scope(original: OriginalIssuerEvidenceV1) -> bool:
    return (
        original.source.cik,
        original.source.accession_number,
    ) in PRIMARY_STATEMENTS


def require_registered_primary_statement_scope(
    original: OriginalIssuerEvidenceV1,
) -> None:
    scope = PRIMARY_STATEMENTS.get(
        (original.source.cik, original.source.accession_number)
    )
    if scope is None:
        raise DataReleaseError(
            "STATEMENT_ORIGINAL_SCOPE_UNREVIEWED",
            "the annual statement profile requires a reviewed original filing scope",
        )
    if (
        original.status != "matched"
        or original.source.content_hash != scope.raw_content_hash
        or original.source.parser_input_hash != scope.parser_input_hash
        or original.report.source_content_hash != scope.parser_input_hash
    ):
        raise DataReleaseError(
            "STATEMENT_ORIGINAL_SCOPE_MISMATCH",
            "reviewed original raw and canonical parser inputs differ",
        )


class PrimaryStatementScopeEvidenceV1(ReleaseModel):
    selection_policy: Literal["reviewed-original-primary-row-v1"] = (
        "reviewed-original-primary-row-v1"
    )
    row_id: str
    raw_content_hash: str
    parser_input_hash: str
    source_concept: str | None
    table_index: int | None
    row_index: int | None
    context_ids: tuple[str, ...]
    annual_periods: tuple[tuple[date, date], ...]


def primary_statement_scope_evidence(
    original: OriginalIssuerEvidenceV1, row_id: str
) -> PrimaryStatementScopeEvidenceV1 | None:
    scope = PRIMARY_STATEMENTS.get(
        (original.source.cik, original.source.accession_number)
    )
    if scope is None or row_id not in {"revenue", *CASH_STATEMENT_ROLES}:
        return None
    locator = next(
        (locator for locator in scope.locators if locator.row_id == row_id), None
    )
    return PrimaryStatementScopeEvidenceV1(
        row_id=row_id,
        raw_content_hash=scope.raw_content_hash,
        parser_input_hash=scope.parser_input_hash,
        source_concept=scope.concept_for(row_id),
        table_index=locator.table_index if locator is not None else None,
        row_index=locator.row_index if locator is not None else None,
        context_ids=locator.context_ids if locator is not None else (),
        annual_periods=scope.annual_periods,
    )


@dataclass(frozen=True)
class PrimaryStatementSelection:
    selected: tuple[ParsedXbrlFactV1, ...] = ()
    rejected: tuple[tuple[ParsedXbrlFactV1, str], ...] = ()
    reason_codes: tuple[str, ...] = ()


def select_primary_statement_observations(
    original: OriginalIssuerEvidenceV1,
    row_id: str,
) -> PrimaryStatementSelection:
    scope = PRIMARY_STATEMENTS.get(
        (original.source.cik, original.source.accession_number)
    )
    if scope is None:
        return PrimaryStatementSelection(
            reason_codes=("MAPPING_STATEMENT_ROW_SCOPE_UNREVIEWED",)
        )
    if (
        original.status != "matched"
        or original.source.content_hash != scope.raw_content_hash
        or original.source.parser_input_hash != scope.parser_input_hash
        or original.report.source_content_hash != scope.parser_input_hash
    ):
        return PrimaryStatementSelection(
            reason_codes=("MAPPING_STATEMENT_ROW_SOURCE_MISMATCH",)
        )
    if scope.concept_for(row_id) is None:
        return PrimaryStatementSelection(
            reason_codes=("MAPPING_STATEMENT_ROW_NOT_PRESENTED",)
        )
    concept = scope.concept_for(row_id)
    contexts = next(
        locator.context_ids for locator in scope.locators if locator.row_id == row_id
    )
    instants = {end for _, end in scope.annual_periods}
    instants.update(start - timedelta(days=1) for start, _ in scope.annual_periods)
    selected, rejected = [], []
    for fact in original.report.facts:
        if fact.concept != concept:
            continue
        if fact.dimensions:
            rejected.append((fact, "MAPPING_SCOPE_UNSUPPORTED"))
        elif fact.context_id not in contexts:
            rejected.append((fact, "MAPPING_STATEMENT_CONTEXT_SCOPE_UNREVIEWED"))
        elif (
            fact.period_start,
            fact.period_end,
        ) in scope.annual_periods or fact.instant in instants:
            selected.append(fact)
        else:
            rejected.append((fact, "MAPPING_STATEMENT_PERIOD_SCOPE_UNREVIEWED"))
    return PrimaryStatementSelection(selected=tuple(selected), rejected=tuple(rejected))
