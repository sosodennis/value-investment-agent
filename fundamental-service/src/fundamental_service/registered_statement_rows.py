from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .arelle_parser import ParsedXbrlFactV1
from .data_releases import DataReleaseError, ReleaseModel
from .registered_statement_row_registry import PRIMARY_STATEMENTS
from .original_issuer import OriginalIssuerEvidenceV1
from .statement_contracts import CashBasis
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
        or {
            fact.namespace_uri
            for fact in original.report.facts
            if fact.concept.startswith("us-gaap:")
        }
        != {scope.us_gaap_namespace}
    ):
        raise DataReleaseError(
            "STATEMENT_ORIGINAL_SCOPE_MISMATCH",
            "reviewed original raw and canonical parser inputs differ",
        )


def registered_statement_namespace(cik: str, accession_number: str) -> str:
    scope = PRIMARY_STATEMENTS.get((cik, accession_number))
    if scope is None:
        raise DataReleaseError(
            "STATEMENT_ORIGINAL_SCOPE_UNREVIEWED",
            "annual statement runtime selection requires a reviewed original source namespace",
        )
    return scope.us_gaap_namespace


def statement_cash_basis(
    original: OriginalIssuerEvidenceV1, row_id: str, concept: str
) -> CashBasis | None:
    activities = {"operating_cash_flow", "investing_cash_flow", "financing_cash_flow"}
    if row_id not in CASH_STATEMENT_ROLES | activities:
        return None
    scope = PRIMARY_STATEMENTS.get(
        (original.source.cik, original.source.accession_number)
    )
    if scope is None:
        return None
    if row_id == "effect_of_exchange_rates_on_cash":
        if concept != scope.cash_effect_concept or not any(
            locator.row_id == row_id and locator.context_ids
            for locator in scope.locators
        ):
            return None
        concept = scope.cash_balance_concept
    if row_id in activities:
        concept = scope.cash_balance_concept
    if concept in {
        "us-gaap:CashAndCashEquivalentsAtCarryingValue",
        "us-gaap:CashAndCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        "us-gaap:EffectOfExchangeRateOnCashAndCashEquivalents",
    }:
        return "cash_and_equivalents"
    if concept in {
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        "us-gaap:EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations",
    }:
        return "cash_equivalents_and_restricted_cash"
    return None


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
