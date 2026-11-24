from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, DecimalException, Inexact, Rounded, localcontext
from typing import Literal

from .contracts import (
    CandidateRejectionV1,
    MissingValueV1,
    PeriodType,
    QualityStatus,
    Severity,
)
from .data_releases import ArtifactRefV1
from .facts import FactCandidateV1, select_fact
from .numerical_policy import using_valuation_context
from .serialization import sha256_digest
from .statement_contracts import (
    AnnualStatementsV1,
    CashBasis,
    DurationStatementPeriodV1,
    InstantStatementPeriodV1,
    ReportedStatementCellV1,
    StatementAnnualColumnV1,
    StatementCellV1,
    StatementColumnV1,
    StatementComparabilityV1,
    StatementCoverageV1,
    StatementFactEvidenceV1,
    StatementKind,
    StatementMissingEvidenceV1,
    StatementPeriodV1,
    StatementProjectionInputV1,
    StatementReconciliationV1,
    StatementRowDefinitionV1,
    StatementRowId,
    StatementRowV1,
    StatementTableV1,
    StatementUnavailableSourceV1,
    UnavailableStatementCellV1,
    UnresolvedStatementPeriodV1,
    statement_period_id,
    value_period,
)
from .statement_profiles import annual_statement_profile


class StatementProjectionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _column(
    request: StatementProjectionInputV1,
    annual: StatementAnnualColumnV1,
    statement: StatementKind,
) -> StatementColumnV1:
    period = annual.period
    actual: StatementPeriodV1
    if statement == "balance_sheet" and isinstance(period, DurationStatementPeriodV1):
        actual = InstantStatementPeriodV1(instant=period.period_end)
    else:
        actual = period
    days = (
        period.duration_days if isinstance(period, DurationStatementPeriodV1) else None
    )
    calendar: Literal["52_week", "53_week", "calendar_year", "other", "unresolved"]
    if days == 364:
        calendar = "52_week"
    elif days == 371:
        calendar = "53_week"
    elif days in {365, 366}:
        calendar = "calendar_year"
    elif days is None:
        calendar = "unresolved"
    else:
        calendar = "other"
    return StatementColumnV1(
        period_id=statement_period_id(request.scope, actual),
        fiscal_label=annual.fiscal_label,
        period=actual,
        duration_days=days if statement != "balance_sheet" else None,
        calendar=calendar,
    )


def _candidate_rejection(
    item: StatementFactEvidenceV1,
    row: StatementRowDefinitionV1,
    request: StatementProjectionInputV1,
) -> str | None:
    fact, scope = item.fact, request.scope
    if item.mapping.confidence in {"low", "unresolved"}:
        return "STATEMENT_MAPPING_CONFIDENCE_UNRESOLVED"
    if fact.currency != scope.currency or fact.unit != scope.unit:
        return "STATEMENT_UNIT_MISMATCH"
    if (
        fact.security_id != scope.security_id
        or fact.security_scope != scope.security_scope
    ):
        return "STATEMENT_SECURITY_SCOPE_MISMATCH"
    if fact.context.entity_scope != scope.entity_scope:
        return "STATEMENT_ENTITY_SCOPE_MISMATCH"
    if (
        fact.context.dimensions
        or fact.context.consolidation_scope != scope.consolidation_scope
    ):
        return "STATEMENT_DIMENSIONAL_SCOPE_UNSUPPORTED"
    if (
        fact.concept not in row.concepts
        and item.mapping.anchor_concept not in row.concepts
    ):
        return "STATEMENT_ROW_MAPPING_UNSUPPORTED"
    return None


def _fact_matches_period(
    item: StatementFactEvidenceV1,
    column: StatementColumnV1,
    row: StatementRowDefinitionV1,
) -> bool:
    expected = value_period(column, row.value_period_role)
    fact = item.fact
    if isinstance(expected, DurationStatementPeriodV1):
        return (
            fact.context.period_type is PeriodType.DURATION
            and fact.period_start == expected.period_start
            and fact.period_end == expected.period_end
            and fact.instant is None
        )
    if isinstance(expected, InstantStatementPeriodV1):
        return (
            fact.context.period_type is PeriodType.INSTANT
            and fact.instant == expected.instant
            and fact.period_start is None
        )
    return False


def _candidate(item: StatementFactEvidenceV1) -> FactCandidateV1:
    fact, source = item.fact, item.source
    return FactCandidateV1(
        candidate_id=fact.fact_id,
        issuer_id=fact.issuer_id,
        security_id=fact.security_id,
        concept=fact.concept,
        normalized_field=fact.normalized_field,
        value=fact.value,
        unit=fact.unit,
        scale=fact.scale,
        currency=fact.currency,
        period_type=fact.context.period_type,
        period_start=fact.period_start,
        period_end=fact.context.end_date,
        instant=fact.instant,
        dimensions=fact.context.dimensions,
        entity_scope=fact.context.entity_scope,
        consolidation_scope=fact.context.consolidation_scope,
        security_scope=fact.security_scope or "",
        as_of=fact.as_of,
        available_at=max(
            fact.available_at, source.available_at, fact.source.available_at
        ),
        filed_at=fact.filed_at,
        captured_at=fact.captured_at,
        accession_number=fact.accession_number,
        filing_version=fact.filing_version or fact.accession_number or fact.fact_id,
        is_amendment=fact.is_amendment or source.is_amendment,
        amends_accession=fact.amends_accession or source.amends_accession,
        supersedes_accession=fact.supersedes_accession or source.supersedes_accession,
        amendment_scope=fact.amendment_scope or source.amendment_scope,
        decimals=fact.decimals,
        context_id=fact.context.context_id,
        unit_qname=fact.context.unit_qname,
        measure=fact.context.measure,
        source=fact.source,
        taxonomy_version=fact.taxonomy_version,
        mapping=item.mapping,
        accounting_evidence=fact.accounting_evidence,
    )


def _unavailable(
    row: StatementRowDefinitionV1,
    column: StatementColumnV1,
    *,
    missing: MissingValueV1,
    quality: QualityStatus,
    codes: tuple[str, ...],
    evidence: tuple[ArtifactRefV1, ...] = (),
    candidates: tuple[str, ...] = (),
    rejections: tuple[CandidateRejectionV1, ...] = (),
) -> UnavailableStatementCellV1:
    payload = dict(
        row_id=row.row_id,
        period_id=column.period_id,
        missing=missing,
        quality_status=quality,
        issue_codes=codes,
        evidence_refs=evidence,
        candidate_fact_ids=candidates,
        rejected_candidates=rejections,
    )
    return UnavailableStatementCellV1(
        cell_id=sha256_digest(payload),
        row_id=row.row_id,
        period_id=column.period_id,
        missing=missing,
        quality_status=quality,
        issue_codes=codes,
        evidence_refs=evidence,
        candidate_fact_ids=candidates,
        rejected_candidates=rejections,
    )


def _cell(
    request: StatementProjectionInputV1,
    row: StatementRowDefinitionV1,
    column: StatementColumnV1,
    annual: StatementAnnualColumnV1,
    missing_by_key: dict[tuple[StatementRowId, str], StatementMissingEvidenceV1],
) -> StatementCellV1:
    original = next(
        source
        for source in request.source_outcomes
        if source.accession_number == annual.original_accession
    )
    if isinstance(column.period, UnresolvedStatementPeriodV1):
        quality = (
            original.quality_status
            if isinstance(original, StatementUnavailableSourceV1)
            else QualityStatus.PROVISIONAL
        )
        codes = (
            original.issue_codes
            if isinstance(original, StatementUnavailableSourceV1)
            else ("STATEMENT_PERIOD_UNRESOLVED",)
        )
        return _unavailable(
            row,
            column,
            missing=column.period.missing,
            quality=quality,
            codes=codes,
            evidence=(column.period.source_outcome_ref,),
        )
    observations = tuple(
        item
        for item in request.facts
        if item.fact.normalized_field == row.row_id
        and _fact_matches_period(item, column, row)
    )
    rejected: dict[str, str] = {}
    eligible = []
    for item in observations:
        code = _candidate_rejection(item, row, request)
        if code is None:
            eligible.append(item)
        else:
            rejected[item.fact.fact_id] = code
    if not eligible:
        if isinstance(original, StatementUnavailableSourceV1) and not observations:
            return _unavailable(
                row,
                column,
                missing=original.missing,
                quality=original.quality_status,
                codes=original.issue_codes,
                evidence=(original.outcome_ref,),
            )
        retained = missing_by_key.get((row.row_id, column.period_id))
        if retained is not None and not observations:
            return _unavailable(
                row,
                column,
                missing=retained.missing,
                quality=retained.quality_status,
                codes=retained.issue_codes,
                evidence=retained.evidence_refs,
            )
        codes = tuple(sorted(set(rejected.values()))) or (
            "STATEMENT_ROW_EVIDENCE_UNRESOLVED",
        )
        missing = MissingValueV1(status="unresolved", reason="; ".join(codes))
        return _unavailable(
            row,
            column,
            missing=missing,
            quality=QualityStatus.PROVISIONAL,
            codes=codes,
            candidates=tuple(sorted(rejected)),
            rejections=tuple(
                CandidateRejectionV1(candidate_id=key, reason=value)
                for key, value in sorted(rejected.items())
            ),
        )
    selection = select_fact(
        tuple(_candidate(item) for item in eligible), request.cutoff_at
    )
    basis_groups: dict[CashBasis | None, list[StatementFactEvidenceV1]] = {}
    if row.statement == "cash_flow":
        for item in eligible:
            basis_groups.setdefault(item.cash_basis, []).append(item)
    if len(basis_groups) > 1 and not any(
        issue.code == "FACT_AMENDMENT_SCOPE_UNKNOWN" for issue in selection.issues
    ):
        basis_selections = tuple(
            select_fact(tuple(_candidate(item) for item in group), request.cutoff_at)
            for group in basis_groups.values()
        )
        if sum(item.fact is not None for item in basis_selections) > 1:
            for result in basis_selections:
                rejected.update(
                    {
                        item.candidate_id: item.reason
                        for item in result.rejected_candidate_reasons
                    }
                )
                if result.fact is not None:
                    rejected[result.fact.fact_id] = "cash_definition_conflict"
            return _unavailable(
                row,
                column,
                missing=MissingValueV1(
                    status="unresolved",
                    reason="eligible cash facts use different cash definitions",
                ),
                quality=QualityStatus.ABSTAIN,
                codes=("STATEMENT_CASH_DEFINITION_CONFLICT",),
                candidates=tuple(sorted(item.fact.fact_id for item in observations)),
                rejections=tuple(
                    CandidateRejectionV1(candidate_id=key, reason=value)
                    for key, value in sorted(rejected.items())
                ),
            )
    rejected.update(
        {
            item.candidate_id: item.reason
            for item in selection.rejected_candidate_reasons
        }
    )
    rejections = tuple(
        CandidateRejectionV1(candidate_id=key, reason=value)
        for key, value in sorted(rejected.items())
    )
    candidates = tuple(sorted(item.fact.fact_id for item in observations))
    if selection.fact is None:
        codes = tuple(issue.code for issue in selection.issues)
        return _unavailable(
            row,
            column,
            missing=MissingValueV1(status="unresolved", reason="; ".join(codes)),
            quality=QualityStatus.ABSTAIN,
            codes=codes,
            candidates=candidates,
            rejections=rejections,
        )
    evidence = next(
        item for item in eligible if item.fact.fact_id == selection.fact.fact_id
    )
    selected_source = next(
        source
        for source in request.source_outcomes
        if source.accession_number == evidence.fact.accession_number
    )
    selection_kind: Literal["original", "amended", "later_comparative"]
    if evidence.fact.is_amendment or evidence.source.is_amendment:
        selection_kind = "amended"
    elif selected_source.report_period_end > annual.period_end:
        selection_kind = "later_comparative"
    else:
        selection_kind = "original"
    fact = evidence.fact.model_copy(
        update={
            "rejected_candidates": tuple(item.candidate_id for item in rejections),
            "rejected_candidate_reasons": rejections,
            "point_in_time_policy": request.profile.selection_policy,
            "selection_reason": "latest_eligible_available_fact_for_exact_key",
        }
    )
    version_id = sha256_digest(
        {
            "row_id": row.row_id,
            "period_id": column.period_id,
            "fact": fact,
            "mapping": evidence.mapping,
            "cutoff_at": request.cutoff_at,
        }
    )
    return ReportedStatementCellV1(
        cell_id=sha256_digest(
            {"row_id": row.row_id, "period_id": column.period_id, "version": version_id}
        ),
        row_id=row.row_id,
        period_id=column.period_id,
        selected_version_id=version_id,
        fact=fact,
        snapshot_id=evidence.snapshot_id,
        snapshot_manifest_digest=evidence.snapshot_manifest_digest,
        mapping_digest=sha256_digest(evidence.mapping),
        mapping_evidence_refs=evidence.mapping_evidence_refs,
        cash_basis=evidence.cash_basis,
        selection_reason="latest_eligible_available_fact_for_exact_key",
        selection_kind=selection_kind,
        source_report_period_end=selected_source.report_period_end,
        candidate_fact_ids=candidates,
        rejected_candidates=rejections,
    )


def _compare(
    columns: tuple[StatementColumnV1, ...],
) -> tuple[StatementComparabilityV1, ...]:
    comparisons = []
    for earlier, later in zip(columns, columns[1:]):
        first, second = earlier.period, later.period
        status: LiteralComparison = "not_comparable"
        codes: tuple[str, ...] = ("STATEMENT_PERIOD_UNRESOLVED",)
        if isinstance(first, DurationStatementPeriodV1) and isinstance(
            second, DurationStatementPeriodV1
        ):
            if second.period_start != first.period_end + timedelta(days=1):
                codes = ("STATEMENT_NONCONTIGUOUS_ANNUAL_PERIODS",)
            elif earlier.calendar == "other" or later.calendar == "other":
                codes = ("STATEMENT_NONSTANDARD_ANNUAL_DURATION",)
            elif {earlier.calendar, later.calendar} <= {"52_week", "53_week"}:
                status = (
                    "limited" if earlier.calendar != later.calendar else "comparable"
                )
                codes = (
                    ("STATEMENT_52_53_WEEK_COMPARISON",) if status == "limited" else ()
                )
            elif (
                earlier.calendar == later.calendar == "calendar_year"
                and first.period_end.month == second.period_end.month
            ):
                status, codes = "comparable", ()
            else:
                codes = ("STATEMENT_FISCAL_CALENDAR_CHANGED",)
        comparisons.append(
            StatementComparabilityV1(
                earlier_period_id=earlier.period_id,
                later_period_id=later.period_id,
                status=status,
                issue_codes=codes,
            )
        )
    return tuple(comparisons)


LiteralComparison = Literal["comparable", "limited", "not_comparable"]


def _cash_comparability(
    table: StatementTableV1,
) -> tuple[StatementComparabilityV1, ...]:
    comparisons = []
    for ordinal in range(len(table.columns) - 1):
        affected = []
        codes = set()
        for row in table.rows:
            earlier, later = row.cells[ordinal : ordinal + 2]
            if isinstance(earlier, ReportedStatementCellV1) and isinstance(
                later, ReportedStatementCellV1
            ):
                if earlier.cash_basis is None or later.cash_basis is None:
                    codes.add("STATEMENT_CASH_DEFINITION_UNRESOLVED")
                elif earlier.cash_basis != later.cash_basis:
                    codes.add("STATEMENT_CASH_DEFINITION_CHANGED")
                else:
                    continue
                affected.append(row.definition.row_id)
        if affected:
            comparisons.append(
                StatementComparabilityV1(
                    earlier_period_id=table.columns[ordinal].period_id,
                    later_period_id=table.columns[ordinal + 1].period_id,
                    status="not_comparable",
                    issue_codes=tuple(sorted(codes)),
                    affected_row_ids=tuple(affected),
                )
            )
    return tuple(comparisons)


def _check(
    table: StatementTableV1,
    column: StatementColumnV1,
    check_id: str,
    terms: tuple[tuple[StatementRowId, int], ...],
    expression: str,
    *,
    cash_basis: bool = False,
) -> StatementReconciliationV1:
    by_row = {
        row.definition.row_id: next(
            cell for cell in row.cells if cell.period_id == column.period_id
        )
        for row in table.rows
    }
    cells = tuple(by_row[row_id] for row_id, _ in terms)
    reported = tuple(
        cell for cell in cells if isinstance(cell, ReportedStatementCellV1)
    )
    codes: tuple[str, ...] = ()
    status: Literal["passed", "rounding", "unresolved", "not_applicable", "failed"] = (
        "unresolved"
    )
    difference = tolerance = None
    severity = Severity.WARNING
    if len(reported) != len(cells):
        codes = ("STATEMENT_RECONCILIATION_INPUT_UNAVAILABLE",)
    elif cash_basis and (
        None in {cell.cash_basis for cell in reported}
        or len({cell.cash_basis for cell in reported}) != 1
    ):
        codes = ("STATEMENT_CASH_DEFINITION_UNRESOLVED",)
    elif len({(cell.fact.unit, cell.fact.currency) for cell in reported}) != 1:
        codes = ("STATEMENT_RECONCILIATION_UNIT_MISMATCH",)
        severity = Severity.ERROR
    else:
        try:
            with localcontext() as context:
                context.traps[Inexact] = True
                context.traps[Rounded] = True
                values = []
                for cell, (_, coefficient) in zip(reported, terms, strict=True):
                    assert isinstance(cell.fact.value, Decimal)
                    values.append(cell.fact.value * coefficient)
                difference = sum(values, Decimal(0))
                if all(cell.fact.decimals is not None for cell in reported):
                    tolerance = sum(
                        (
                            Decimal(5).scaleb(-cell.fact.decimals - 1)
                            for cell in reported
                            if cell.fact.decimals is not None
                        ),
                        Decimal(0),
                    )
        except DecimalException:
            difference = tolerance = None
            codes = ("STATEMENT_RECONCILIATION_PRECISION_EXCEEDED",)
        if difference == 0:
            status, severity = "passed", Severity.INFO
        elif difference is not None:
            if any(cell.fact.decimals is None for cell in reported):
                codes = ("STATEMENT_RECONCILIATION_PRECISION_UNAVAILABLE",)
            else:
                assert tolerance is not None
                if abs(difference) <= tolerance:
                    status, codes = "rounding", ("STATEMENT_REPORTED_ROUNDING",)
                else:
                    status, severity, codes = (
                        "failed",
                        Severity.ERROR,
                        ("STATEMENT_RECONCILIATION_DIFFERENCE",),
                    )
    return StatementReconciliationV1(
        statement=table.statement,
        period_id=column.period_id,
        check_id=check_id,
        status=status,
        severity=severity,
        expression=expression,
        input_fact_ids=tuple(cell.fact.fact_id for cell in reported),
        difference=difference,
        tolerance=tolerance,
        issue_codes=codes,
        policy_version="reported-decimals-half-unit-sum-v1",
    )


def _reconcile(table: StatementTableV1) -> tuple[StatementReconciliationV1, ...]:
    checks = []
    for column in table.columns:
        if table.statement == "balance_sheet":
            checks.append(
                _check(
                    table,
                    column,
                    "assets_liabilities_equity",
                    (
                        ("total_assets", 1),
                        ("total_liabilities", -1),
                        ("total_equity", -1),
                    ),
                    "total_assets - total_liabilities - total_equity",
                )
            )
        elif table.statement == "cash_flow":
            fx = next(
                cell
                for row in table.rows
                if row.definition.row_id == "effect_of_exchange_rates_on_cash"
                for cell in row.cells
                if cell.period_id == column.period_id
            )
            category_terms: tuple[tuple[StatementRowId, int], ...] = (
                ("operating_cash_flow", 1),
                ("investing_cash_flow", 1),
                ("financing_cash_flow", 1),
            )
            if isinstance(fx, ReportedStatementCellV1):
                category_terms += (("effect_of_exchange_rates_on_cash", 1),)
            category_terms += (("net_change_in_cash", -1),)
            categories = _check(
                table,
                column,
                "cash_categories_to_reported_change",
                category_terms,
                " + ".join(
                    f"{coefficient} * {role}" for role, coefficient in category_terms
                ),
                cash_basis=True,
            )
            if (
                isinstance(fx, UnavailableStatementCellV1)
                and categories.status == "failed"
            ):
                categories = categories.model_copy(
                    update={
                        "status": "unresolved",
                        "severity": Severity.WARNING,
                        "issue_codes": ("STATEMENT_FX_INPUT_UNAVAILABLE",),
                    }
                )
            checks.extend(
                (
                    categories,
                    _check(
                        table,
                        column,
                        "reported_cash_change",
                        (
                            ("cash_flow_beginning_balance", 1),
                            ("net_change_in_cash", 1),
                            ("cash_flow_ending_balance", -1),
                        ),
                        "cash_flow_beginning_balance + net_change_in_cash - cash_flow_ending_balance",
                        cash_basis=True,
                    ),
                    _check(
                        table,
                        column,
                        "cash_rollforward_with_fx",
                        (
                            ("cash_flow_beginning_balance", 1),
                            ("operating_cash_flow", 1),
                            ("investing_cash_flow", 1),
                            ("financing_cash_flow", 1),
                            ("effect_of_exchange_rates_on_cash", 1),
                            ("cash_flow_ending_balance", -1),
                        ),
                        "cash_flow_beginning_balance + operating_cash_flow + investing_cash_flow + financing_cash_flow + effect_of_exchange_rates_on_cash - cash_flow_ending_balance",
                        cash_basis=True,
                    ),
                )
            )
    return tuple(checks)


@using_valuation_context
def project_annual_statements(
    request: StatementProjectionInputV1,
    *,
    executable_digest: str,
) -> AnnualStatementsV1:
    expected_profile = annual_statement_profile(executable_digest=executable_digest)
    if request.profile != expected_profile:
        raise StatementProjectionError(
            "STATEMENT_PROFILE_UNSUPPORTED",
            "statement profile differs from the installed projector",
        )
    missing = {(item.row_id, item.period_id): item for item in request.missing_evidence}
    annuals = tuple(
        sorted(request.columns, key=lambda item: (item.period_end, item.fiscal_label))
    )
    tables = []
    statements: tuple[StatementKind, ...] = (
        "income_statement",
        "balance_sheet",
        "cash_flow",
    )
    for statement in statements:
        columns = tuple(_column(request, annual, statement) for annual in annuals)
        rows = tuple(
            StatementRowV1(
                definition=row,
                cells=tuple(
                    _cell(request, row, column, annual, missing)
                    for column, annual in zip(columns, annuals, strict=True)
                ),
            )
            for row in request.profile.rows
            if row.statement == statement
        )
        tables.append(StatementTableV1(statement=statement, columns=columns, rows=rows))
    coverage = tuple(
        StatementCoverageV1(
            period_id=column.period_id,
            statement=table.statement,
            fiscal_label=column.fiscal_label,
            reported_rows=sum(
                isinstance(cell, ReportedStatementCellV1)
                for row in table.rows
                for cell in row.cells
                if cell.period_id == column.period_id
            ),
            declared_rows=len(table.rows),
            unavailable_row_ids=tuple(
                row.definition.row_id
                for row in table.rows
                for cell in row.cells
                if cell.period_id == column.period_id
                and isinstance(cell, UnavailableStatementCellV1)
            ),
        )
        for table in tables
        for column in table.columns
    )
    reconciliations = tuple(check for table in tables for check in _reconcile(table))
    all_cells = tuple(
        cell for table in tables for row in table.rows for cell in row.cells
    )
    if any(check.status == "failed" for check in reconciliations):
        quality = QualityStatus.ABSTAIN
    elif all(isinstance(cell, ReportedStatementCellV1) for cell in all_cells) and all(
        check.status in {"passed", "rounding"} for check in reconciliations
    ):
        quality = QualityStatus.VERIFIED
    elif not any(
        isinstance(cell, ReportedStatementCellV1) for cell in all_cells
    ) and any(
        source.quality_status is QualityStatus.ERROR
        for source in request.source_outcomes
        if isinstance(source, StatementUnavailableSourceV1)
    ):
        quality = QualityStatus.ERROR
    else:
        quality = QualityStatus.PROVISIONAL
    comparability = (*_compare(tables[0].columns), *_cash_comparability(tables[2]))
    payload = dict(
        contract_version="fundamental.annual-statements.v1",
        input_digest=request.digest,
        scope=request.scope,
        cutoff_at=request.cutoff_at,
        profile=request.profile,
        tables=tuple(tables),
        source_outcomes=tuple(
            sorted(request.source_outcomes, key=lambda item: item.accession_number)
        ),
        candidate_evidence=tuple(
            sorted(request.facts, key=lambda item: item.fact.fact_id)
        ),
        coverage=coverage,
        comparability=comparability,
        reconciliations=reconciliations,
        quality_status=quality,
        valuation_eligibility="not_evaluated",
    )
    return AnnualStatementsV1.model_validate(
        {**payload, "statement_id": sha256_digest(payload)}
    )
