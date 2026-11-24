"""Statement behavior over frozen original numbers with synthetic mapping authority."""

from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from itertools import permutations
import json
from pathlib import Path

from pydantic import ValidationError
import pytest

from fundamental_service.annual_statements import (
    StatementProjectionError,
    project_annual_statements,
)
from fundamental_service.contracts import (
    CanonicalFactV1,
    DimensionV1,
    MissingValueV1,
    PeriodType,
    QualityStatus,
    SourceProvenanceV1,
    SourceRecordV1,
    SourceRole,
    XbrlContextV1,
)
from fundamental_service.data_releases import ArtifactRefV1
from fundamental_service.facts import CanonicalMappingV1
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.statement_contracts import (
    AnnualStatementsV1,
    DurationStatementPeriodV1,
    ReportedStatementCellV1,
    StatementAnnualColumnV1,
    StatementAvailableSourceV1,
    StatementFactEvidenceV1,
    StatementMissingEvidenceV1,
    StatementProjectionInputV1,
    StatementScopeV1,
    StatementTableV1,
    StatementUnavailableSourceV1,
    UnavailableStatementCellV1,
    UnresolvedStatementPeriodV1,
    statement_period_id,
)
from fundamental_service.statement_profiles import (
    annual_statement_profile,
    statement_executable_digest,
)

ROOT = Path(__file__).parent / "fixtures" / "annual-statements"
COHORT = json.loads((ROOT / "issue494-cohort.json").read_text())
GOLDEN = json.loads((ROOT / "issue494-golden.json").read_text())
AAPL_2024 = "0000320193-24-000123"
AAPL_2023 = "0000320193-23-000106"


def ref(key: str) -> ArtifactRefV1:
    return ArtifactRefV1(
        artifact_id=f"fixture:{key}",
        content_hash=sha256_digest(key),
        media_type="application/json",
        role="annual-statement-test-evidence",
    )


def evidence(filing: dict) -> tuple[StatementFactEvidenceV1, ...]:
    meta = next(
        item
        for item in COHORT["filings"]
        if item["accession_number"] == filing["accession_number"]
    )
    accepted = datetime.fromisoformat(meta["accepted_at"])
    original = next(
        item for item in meta["source_records"] if item["uri"] == filing["source_url"]
    )
    captured = datetime.fromisoformat(original["captured_at"])
    source = SourceRecordV1(
        source_id="sec-filing",
        uri=filing["source_url"],
        role=SourceRole.FILING,
        available_at=accepted,
        captured_at=captured,
        publication_at=accepted,
        http_status=200,
        media_type="text/html",
        terms_reference="https://www.sec.gov/edgar",
        content_hash=filing["source_sha256"],
        parser_version="synthetic-fixture-parser",
        accession_number=filing["accession_number"],
        filed_at=accepted,
        filing_version=filing["accession_number"],
        form="10-K",
    )
    facts = []
    for statement in filing["statements"]:
        for row in statement["rows"]:
            for ordinal, observation in enumerate(row.get("values", [])):
                period = observation["source_period"]
                start = (
                    date.fromisoformat(period["start_date"])
                    if period["period_type"] == "duration"
                    else None
                )
                end = date.fromisoformat(period["end_date"]) if start else None
                instant = (
                    date.fromisoformat(period["instant"])
                    if period["period_type"] == "instant"
                    else None
                )
                identifier = f"{filing['accession_number']}:{row['row_id']}:{ordinal}"
                mapping = CanonicalMappingV1(
                    contract_version="fundamental.v1",
                    decision_id=f"mapping:{identifier}",
                    source_concept=observation["concept_qname"],
                    normalized_field=row["row_id"],
                    mapping_version="synthetic-mapping-v1",
                    confidence="high",
                    status="approved",
                )
                context = XbrlContextV1(
                    concept_qname=observation["concept_qname"],
                    period_type=PeriodType(period["period_type"]),
                    start_date=start,
                    end_date=end,
                    instant=instant,
                    unit_qname="iso4217:USD",
                    measure="iso4217:USD",
                    entity_scope=filing["issuer_id"],
                    consolidation_scope="consolidated",
                    context_id=observation["context_id"],
                )
                fact = CanonicalFactV1(
                    contract_version="fundamental.v1",
                    fact_id=identifier,
                    issuer_id=filing["issuer_id"],
                    security_id=None,
                    concept=observation["concept_qname"],
                    normalized_field=row["row_id"],
                    value=Decimal(observation["value"]),
                    unit="iso4217:USD",
                    scale=observation["scale"],
                    currency="USD",
                    period_start=start,
                    period_end=end or instant,
                    instant=instant,
                    context=context,
                    security_scope="issuer",
                    as_of=datetime.combine(
                        end or instant, datetime.min.time(), tzinfo=UTC
                    ),
                    available_at=accepted,
                    filed_at=accepted,
                    captured_at=captured,
                    accession_number=filing["accession_number"],
                    filing_version=filing["accession_number"],
                    decimals=int(observation["decimals"]),
                    taxonomy_version=meta["taxonomy_namespaces"]["us-gaap"],
                    source=SourceProvenanceV1(
                        source_url=source.uri,
                        content_hash=source.content_hash,
                        source_role=SourceRole.FILING,
                        captured_at=captured,
                        available_at=accepted,
                        filed_at=accepted,
                        accession_number=filing["accession_number"],
                        parser_version=source.parser_version,
                    ),
                    quality=QualityStatus.VERIFIED,
                    mapping_decision_id=mapping.decision_id,
                    mapping_confidence="high",
                )
                cash_basis = None
                if statement["statement"] == "cash_flow":
                    cash_basis = (
                        "cash_and_equivalents"
                        if observation["concept_qname"]
                        == "us-gaap:EffectOfExchangeRateOnCashAndCashEquivalents"
                        else "cash_equivalents_and_restricted_cash"
                    )
                facts.append(
                    StatementFactEvidenceV1(
                        fact=fact,
                        mapping=mapping,
                        source=source,
                        snapshot_id=f"snapshot:{filing['accession_number']}",
                        snapshot_manifest_digest=sha256_digest(
                            filing["accession_number"]
                        ),
                        mapping_evidence_refs=(ref(identifier),),
                        cash_basis=cash_basis,
                    )
                )
    return tuple(facts)


def request_for(
    accessions=(AAPL_2024,), *, cutoff="2024-11-02T00:00:00Z", columns=None
):
    originals = tuple(
        item for item in GOLDEN["filings"] if item["accession_number"] in accessions
    )
    facts = tuple(item for filing in originals for item in evidence(filing))
    scope = StatementScopeV1(
        issuer_id=originals[0]["issuer_id"],
        security_id=None,
        security_scope="issuer",
        entity_scope=originals[0]["issuer_id"],
        currency="USD",
        unit="iso4217:USD",
    )
    sources = tuple(
        StatementAvailableSourceV1(
            accession_number=filing["accession_number"],
            available_at=next(
                item
                for item in facts
                if item.fact.accession_number == filing["accession_number"]
            ).source.available_at,
            report_period_end=date.fromisoformat(filing["fiscal_period"]["end_date"]),
            outcome_ref=ref(filing["accession_number"]),
            fact_ids=tuple(
                item.fact.fact_id
                for item in facts
                if item.fact.accession_number == filing["accession_number"]
            ),
        )
        for filing in originals
    )
    selected = (
        originals
        if columns is None
        else tuple(item for item in originals if item["accession_number"] in columns)
    )
    annuals = tuple(
        StatementAnnualColumnV1(
            fiscal_label=f"FY{filing['primary_fiscal_year']}",
            period=DurationStatementPeriodV1(
                period_start=date.fromisoformat(filing["fiscal_period"]["start_date"]),
                period_end=date.fromisoformat(filing["fiscal_period"]["end_date"]),
            ),
            original_accession=filing["accession_number"],
        )
        for filing in selected
    )
    timestamp = datetime.fromisoformat(cutoff)
    return StatementProjectionInputV1(
        scope=scope,
        cutoff_at=timestamp,
        coverage_cutoff_at=timestamp,
        profile=annual_statement_profile(
            executable_digest=statement_executable_digest()
        ),
        discovery_ref=ref("discovery"),
        columns=annuals,
        source_outcomes=sources,
        facts=facts,
    )


def project(request):
    return project_annual_statements(
        request, executable_digest=statement_executable_digest()
    )


def cell(result, row_id, period_end=None):
    for table in result.tables:
        for row in table.rows:
            if row.definition.row_id == row_id:
                if period_end is None:
                    return row.cells[-1]
                column = next(
                    column
                    for column in table.columns
                    if getattr(
                        column.period,
                        "period_end",
                        getattr(column.period, "instant", None),
                    )
                    == date.fromisoformat(period_end)
                )
                return next(
                    value for value in row.cells if value.period_id == column.period_id
                )
    raise AssertionError(row_id)


def replace_facts(request, facts):
    sources = tuple(
        source.model_copy(
            update={
                "fact_ids": tuple(
                    item.fact.fact_id
                    for item in facts
                    if item.fact.accession_number == source.accession_number
                )
            }
        )
        for source in request.source_outcomes
    )
    return StatementProjectionInputV1(
        **{**request.model_dump(), "facts": facts, "source_outcomes": sources}
    )


def test_five_originals_remain_five_columns_with_source_values_and_independent_valuation_status():
    accessions = next(
        item["original_accessions"]
        for item in COHORT["cases"]
        if item["case_id"] == "aapl-historical"
    )
    result = project(request_for(accessions))
    assert len(result.tables) == 3
    assert [
        [column.fiscal_label for column in table.columns] for table in result.tables
    ] == [[f"FY{year}" for year in range(2020, 2025)]] * 3
    assert cell(result, "revenue").fact.value == Decimal("391035000000")
    assert cell(result, "revenue", "2020-09-26").fact.value == Decimal("274515000000")
    assert cell(result, "cash_flow_ending_balance", "2023-09-30").fact.value == Decimal(
        "30737000000"
    )
    assert cell(result, "cash_and_equivalents", "2023-09-30").fact.value == Decimal(
        "29965000000"
    )
    assert result.valuation_eligibility == "not_evaluated"
    assert result.profile.supported_history_threshold is None
    assert result.coverage[-1].declared_rows == 7


def test_apple_actual_52_53_week_periods_are_retained_and_not_annualized():
    result = project(request_for(("0000320193-22-000108", AAPL_2023, AAPL_2024)))
    columns = result.tables[0].columns
    assert [column.duration_days for column in columns] == [364, 371, 364]
    assert columns[1].period.period_start == date(2022, 9, 25)
    assert columns[1].period.period_end == date(2023, 9, 30)
    assert [item.status for item in result.comparability] == ["limited", "limited"]
    assert cell(result, "revenue", "2023-09-30").fact.value == Decimal("383285000000")


def test_later_comparative_changes_version_only_after_publication_without_a_second_column():
    before = request_for(
        (AAPL_2023, AAPL_2024), cutoff="2024-01-01T00:00:00Z", columns=(AAPL_2023,)
    )
    after = request_for((AAPL_2023, AAPL_2024), columns=(AAPL_2023,))
    original, comparative = (
        cell(project(before), "revenue"),
        cell(project(after), "revenue"),
    )
    assert original.fact.accession_number == AAPL_2023
    assert comparative.fact.accession_number == AAPL_2024
    assert original.selection_kind == "original"
    assert comparative.selection_kind == "later_comparative"
    assert comparative.source_report_period_end == date(2024, 9, 28)
    assert original.fact.value == comparative.fact.value == Decimal("383285000000")
    assert original.period_id == comparative.period_id
    assert original.selected_version_id != comparative.selected_version_id
    assert len(project(after).tables[0].columns) == 1
    assert "not_available_at_valuation_time" in {
        item.reason for item in original.rejected_candidates
    }
    assert "superseded_by_later_available_filing" in {
        item.reason for item in comparative.rejected_candidates
    }


def test_equal_precision_conflict_is_not_resolved_by_candidate_order():
    request = request_for()
    original = next(
        item
        for item in request.facts
        if item.fact.normalized_field == "revenue"
        and item.fact.period_end == date(2024, 9, 28)
    )
    duplicate = original.model_copy(
        update={
            "fact": original.fact.model_copy(
                update={"fact_id": "conflict", "value": original.fact.value + 1}
            )
        }
    )
    for pair in permutations((original, duplicate)):
        result = project(
            replace_facts(
                request,
                tuple(item for item in request.facts if item is not original) + pair,
            )
        )
        value = cell(result, "revenue")
        assert isinstance(value, UnavailableStatementCellV1)
        assert value.issue_codes == ("FACT_CONFLICT",)
        assert set(value.candidate_fact_ids) == {original.fact.fact_id, "conflict"}


@pytest.mark.parametrize(
    "scope,code",
    [
        (
            {
                "dimensions": (
                    DimensionV1(
                        name="us-gaap:StatementBusinessSegmentsAxis",
                        member="aapl:ProductsMember",
                    ),
                )
            },
            "STATEMENT_DIMENSIONAL_SCOPE_UNSUPPORTED",
        ),
        ({"entity_scope": "another-entity"}, "STATEMENT_ENTITY_SCOPE_MISMATCH"),
    ],
)
def test_scope_differences_are_unavailable_instead_of_consolidated(scope, code):
    request = request_for()
    facts = tuple(
        item.model_copy(
            update={
                "fact": item.fact.model_copy(
                    update={"context": item.fact.context.model_copy(update=scope)}
                )
            }
        )
        if item.fact.normalized_field == "revenue"
        else item
        for item in request.facts
    )
    value = cell(project(replace_facts(request, facts)), "revenue")
    assert isinstance(value, UnavailableStatementCellV1)
    assert value.issue_codes == (code,)


def test_same_end_quarter_does_not_replace_full_annual_duration():
    request = request_for()
    original = next(
        item
        for item in request.facts
        if item.fact.normalized_field == "revenue"
        and item.fact.period_end == date(2024, 9, 28)
    )
    quarterly = original.model_copy(
        update={
            "fact": original.fact.model_copy(
                update={
                    "fact_id": "quarter",
                    "period_start": date(2024, 6, 30),
                    "value": Decimal("1"),
                    "context": original.fact.context.model_copy(
                        update={"start_date": date(2024, 6, 30)}
                    ),
                }
            )
        }
    )
    result = project(replace_facts(request, (*request.facts, quarterly)))
    assert cell(result, "revenue").fact.value == Decimal("391035000000")
    assert "quarter" not in cell(result, "revenue").candidate_fact_ids


def test_annual_columns_with_one_instant_cannot_duplicate_balance_sheet_identity():
    request = request_for()
    duplicate = request.columns[0].model_dump(mode="json")
    duplicate["period"]["period_start"] = "2024-01-01"
    payload = request.model_dump(mode="json")
    payload["columns"].append(duplicate)
    with pytest.raises(ValidationError, match="STATEMENT_ANNUAL_COLUMN_COLLISION"):
        StatementProjectionInputV1.model_validate_json(canonical_bytes(payload))


def test_statement_table_rejects_duplicate_period_and_cell_identity():
    table = project(request_for()).tables[1].model_dump(mode="json")
    table["columns"].append(table["columns"][0])
    for row in table["rows"]:
        row["cells"].append(row["cells"][0])
    with pytest.raises(ValidationError, match="STATEMENT_TABLE_PERIOD_DUPLICATE"):
        StatementTableV1.model_validate_json(canonical_bytes(table))


def test_apple_reconciles_reported_cash_basis_without_manufacturing_fx():
    result = project(request_for())
    by_id = {check.check_id: check for check in result.reconciliations}
    assert by_id["assets_liabilities_equity"].difference == Decimal(0)
    assert by_id["assets_liabilities_equity"].tolerance == Decimal("1500000")
    assert by_id["reported_cash_change"].status == "passed"
    assert by_id["reported_cash_change"].difference == Decimal(0)
    assert by_id["cash_categories_to_reported_change"].status == "passed"
    assert by_id["cash_rollforward_with_fx"].status == "unresolved"
    assert cell(result, "financing_cash_flow").fact.value == Decimal("-121983000000")
    assert isinstance(
        cell(result, "effect_of_exchange_rates_on_cash"), UnavailableStatementCellV1
    )
    assert result.quality_status is QualityStatus.PROVISIONAL


def test_rounding_uses_reported_decimals_and_a_material_difference_remains_failed():
    request = request_for()
    target = next(
        item
        for item in request.facts
        if item.fact.normalized_field == "total_assets"
        and item.fact.instant == date(2024, 9, 28)
    )
    for adjustment, expected in (
        (Decimal("1000000"), "rounding"),
        (Decimal("2000000"), "failed"),
    ):
        facts = tuple(
            item.model_copy(
                update={
                    "fact": item.fact.model_copy(
                        update={"value": item.fact.value + adjustment}
                    )
                }
            )
            if item is target
            else item
            for item in request.facts
        )
        result = project(replace_facts(request, facts))
        check = next(
            check
            for check in result.reconciliations
            if check.check_id == "assets_liabilities_equity"
        )
        assert check.status == expected
        assert check.difference == adjustment
        assert check.tolerance == Decimal("1500000")
        assert len(check.input_fact_ids) == 3


def test_current_latest_unavailable_original_retains_its_column_without_an_invented_start():
    request = request_for(cutoff="2026-11-24T00:00:00Z")
    outcome = StatementUnavailableSourceV1(
        accession_number="latest",
        available_at=request.cutoff_at,
        report_period_end=date(2025, 9, 27),
        outcome_ref=ref("latest"),
        quality_status=QualityStatus.ERROR,
        missing=MissingValueV1(
            status="unresolved", reason="DTS dependency unavailable"
        ),
        issue_codes=("DQC_VALIDATION_UNAVAILABLE",),
    )
    period = UnresolvedStatementPeriodV1(
        reported_period_end=date(2025, 9, 27),
        missing=outcome.missing,
        source_outcome_ref=outcome.outcome_ref,
    )
    request = StatementProjectionInputV1(
        **{
            **request.model_dump(),
            "source_outcomes": (*request.source_outcomes, outcome),
            "columns": (
                *request.columns,
                StatementAnnualColumnV1(
                    fiscal_label="FY2025", period=period, original_accession="latest"
                ),
            ),
        }
    )
    result = project(request)
    assert len(result.tables[0].columns) == 2
    assert result.tables[0].columns[-1].period.kind == "unresolved"
    assert not hasattr(result.tables[0].columns[-1].period, "period_start")
    assert cell(result, "revenue").issue_codes == ("DQC_VALIDATION_UNAVAILABLE",)


def test_missing_not_applicable_and_numeric_zero_have_distinct_observable_cells():
    request = request_for()
    fx_column = request.columns[0].period
    period_id = statement_period_id(request.scope, fx_column)
    for status in ("missing", "not_applicable"):
        missing = StatementMissingEvidenceV1(
            row_id="effect_of_exchange_rates_on_cash",
            period_id=period_id,
            missing=MissingValueV1(status=status, reason=f"retained {status} evidence"),
            quality_status=QualityStatus.PROVISIONAL,
            issue_codes=(f"TEST_{status.upper()}",),
            evidence_refs=(ref(status),),
        )
        value = cell(
            project(
                StatementProjectionInputV1(
                    **{**request.model_dump(), "missing_evidence": (missing,)}
                )
            ),
            "effect_of_exchange_rates_on_cash",
        )
        assert value.missing.status == status
        assert value.evidence_refs == (ref(status),)
    target = next(
        item
        for item in request.facts
        if item.fact.normalized_field == "net_income"
        and item.fact.period_end == date(2024, 9, 28)
    )
    facts = tuple(
        item.model_copy(
            update={"fact": item.fact.model_copy(update={"value": Decimal(0)})}
        )
        if item is target
        else item
        for item in request.facts
    )
    assert isinstance(
        cell(project(replace_facts(request, facts)), "net_income"),
        ReportedStatementCellV1,
    )
    assert cell(
        project(replace_facts(request, facts)), "net_income"
    ).fact.value == Decimal(0)


def test_source_availability_is_not_replaced_by_earlier_fact_timestamp():
    request = request_for(
        (AAPL_2023, AAPL_2024), cutoff="2024-01-01T00:00:00Z", columns=(AAPL_2023,)
    )
    facts = tuple(
        item.model_copy(
            update={
                "fact": item.fact.model_copy(
                    update={"available_at": datetime(2023, 1, 1, tzinfo=UTC)}
                )
            }
        )
        if item.fact.accession_number == AAPL_2024
        else item
        for item in request.facts
    )
    assert (
        cell(project(replace_facts(request, facts)), "revenue").fact.accession_number
        == AAPL_2023
    )


def test_wrong_cutoff_scope_profile_and_result_corruption_refuse():
    request = request_for()
    with pytest.raises(ValidationError, match="STATEMENT_CUTOFF_OUTSIDE_COVERAGE"):
        StatementProjectionInputV1(
            **{**request.model_dump(), "cutoff_at": datetime(2026, 1, 1, tzinfo=UTC)}
        )
    with pytest.raises(ValidationError, match="STATEMENT_FACT_SOURCE_SCOPE_MISMATCH"):
        StatementProjectionInputV1(
            **{
                **request.model_dump(),
                "scope": request.scope.model_copy(update={"issuer_id": "wrong"}),
            }
        )
    with pytest.raises(StatementProjectionError) as refused:
        project_annual_statements(request, executable_digest="f" * 64)
    assert refused.value.code == "STATEMENT_PROFILE_UNSUPPORTED"
    result = project(request)
    with pytest.raises(ValidationError, match="STATEMENT_RESULT_DIGEST_MISMATCH"):
        AnnualStatementsV1.model_validate(
            {**result.model_dump(), "input_digest": "0" * 64}
        )


def test_same_retained_input_is_order_independent_and_decimal_context_isolated():
    request = request_for()
    original = project(request)
    reordered = StatementProjectionInputV1(
        **{**request.model_dump(), "facts": tuple(reversed(request.facts))}
    )
    with localcontext() as context:
        context.prec = 3
        repeated = project(reordered)
    assert canonical_bytes(original) == canonical_bytes(repeated)
    assert original.statement_id == repeated.statement_id


@pytest.mark.parametrize("accession", ("0001564590-20-034944", "0001564590-21-039151"))
def test_microsoft_legacy_fx_basis_is_not_promoted_by_a_balanced_sum(accession):
    result = project(request_for((accession,)))
    checks = {check.check_id: check for check in result.reconciliations}
    assert isinstance(
        cell(result, "effect_of_exchange_rates_on_cash"), ReportedStatementCellV1
    )
    assert checks["cash_rollforward_with_fx"].status == "unresolved"
    assert checks["cash_rollforward_with_fx"].issue_codes == (
        "STATEMENT_CASH_DEFINITION_UNRESOLVED",
    )
    assert checks["cash_categories_to_reported_change"].status == "unresolved"
    assert checks["cash_categories_to_reported_change"].issue_codes == (
        "STATEMENT_CASH_DEFINITION_UNRESOLVED",
    )
    assert checks["reported_cash_change"].difference == Decimal(0)


@pytest.mark.parametrize(
    "scope,expected_accession,code",
    [
        ("unknown", None, "FACT_AMENDMENT_SCOPE_UNKNOWN"),
        ("unrelated", AAPL_2023, None),
        ("valuation_relevant", AAPL_2024, None),
    ],
)
def test_amendment_scope_controls_only_reported_fact_keys(
    scope, expected_accession, code
):
    request = request_for((AAPL_2023, AAPL_2024), columns=(AAPL_2023,))
    facts = tuple(
        item.model_copy(
            update={
                "fact": item.fact.model_copy(
                    update={
                        "is_amendment": True,
                        "amendment_scope": scope,
                        "amends_accession": AAPL_2023,
                    }
                )
            }
        )
        if item.fact.accession_number == AAPL_2024
        and item.fact.normalized_field == "revenue"
        else item
        for item in request.facts
    )
    result = project(replace_facts(request, facts))
    value = cell(result, "revenue")
    if code:
        assert isinstance(value, UnavailableStatementCellV1)
        assert value.issue_codes == (code,)
    else:
        assert value.fact.accession_number == expected_accession
        assert value.selection_kind == (
            "amended" if scope == "valuation_relevant" else "original"
        )
    assert cell(result, "net_income").fact.accession_number == AAPL_2024


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("currency", "EUR", "STATEMENT_UNIT_MISMATCH"),
        ("unit", "iso4217:EUR", "STATEMENT_UNIT_MISMATCH"),
        ("security_scope", "another_class", "STATEMENT_SECURITY_SCOPE_MISMATCH"),
    ],
)
def test_different_units_or_security_scope_never_merge(field, value, code):
    request = request_for()
    facts = tuple(
        item.model_copy(update={"fact": item.fact.model_copy(update={field: value})})
        if item.fact.normalized_field == "revenue"
        else item
        for item in request.facts
    )
    selected = cell(project(replace_facts(request, facts)), "revenue")
    assert isinstance(selected, UnavailableStatementCellV1)
    assert selected.issue_codes == (code,)


def test_custom_qname_requires_approved_anchor_and_retains_original_concept():
    request = request_for()
    target = next(
        item
        for item in request.facts
        if item.fact.normalized_field == "revenue"
        and item.fact.period_end == date(2024, 9, 28)
    )
    concept = "aapl:CustomAnnualRevenue"
    custom_mapping = CanonicalMappingV1(
        contract_version="fundamental.v1",
        decision_id=target.mapping.decision_id,
        source_concept=concept,
        normalized_field="revenue",
        mapping_version="synthetic-mapping-v1",
        confidence="high",
        status="approved",
        anchor_concept="us-gaap:Revenues",
        reviewer="independent-fixture-review",
        evidence_refs=("fixture:anchor-evidence",),
    )
    custom = target.model_copy(
        update={
            "mapping": custom_mapping,
            "fact": target.fact.model_copy(
                update={
                    "concept": concept,
                    "context": target.fact.context.model_copy(
                        update={"concept_qname": concept}
                    ),
                }
            ),
        }
    )
    result = project(
        replace_facts(
            request, tuple(custom if item is target else item for item in request.facts)
        )
    )
    assert cell(result, "revenue").fact.concept == concept
    assert cell(result, "revenue").mapping_digest == sha256_digest(custom_mapping)
    bad_anchor = custom.model_copy(
        update={
            "mapping": custom_mapping.model_copy(
                update={"anchor_concept": "us-gaap:InventoryNet"}
            )
        }
    )
    refused = cell(
        project(
            replace_facts(
                request,
                tuple(bad_anchor if item is target else item for item in request.facts),
            )
        ),
        "revenue",
    )
    assert refused.issue_codes == ("STATEMENT_ROW_MAPPING_UNSUPPORTED",)


def test_unknown_reported_precision_does_not_create_a_rounding_tolerance():
    request = request_for()
    facts = tuple(
        item.model_copy(
            update={
                "fact": item.fact.model_copy(
                    update={
                        "decimals": None,
                        "value": item.fact.value + Decimal("1"),
                    }
                )
            }
        )
        if item.fact.normalized_field == "total_assets"
        else item
        for item in request.facts
    )
    result = project(replace_facts(request, facts))
    check = next(
        item
        for item in result.reconciliations
        if item.check_id == "assets_liabilities_equity"
    )
    assert check.status == "unresolved"
    assert check.difference == Decimal("1")
    assert check.tolerance is None
    assert check.issue_codes == ("STATEMENT_RECONCILIATION_PRECISION_UNAVAILABLE",)


def test_cash_opening_requires_exact_day_before_duration_start():
    request = request_for()
    facts = tuple(
        item
        for item in request.facts
        if not (
            item.fact.normalized_field == "cash_flow_beginning_balance"
            and item.fact.instant == date(2023, 9, 30)
        )
    )
    result = project(replace_facts(request, facts))
    opening = cell(result, "cash_flow_beginning_balance")
    assert isinstance(opening, UnavailableStatementCellV1)
    assert not opening.candidate_fact_ids
    assert (
        next(
            item
            for item in result.reconciliations
            if item.check_id == "reported_cash_change"
        ).status
        == "unresolved"
    )


def test_statement_result_rejects_forged_non_numeric_reported_value():
    result = project(request_for())
    target = cell(result, "revenue")
    with pytest.raises(ValidationError, match="finite Decimal"):
        ReportedStatementCellV1(
            **{
                **target.model_dump(),
                "fact": target.fact.model_copy(update={"value": "not-a-number"}),
            }
        )


def test_missing_mapping_cannot_be_promoted_to_a_reported_statement_fact():
    target = request_for().facts[0]
    with pytest.raises(ValidationError, match="STATEMENT_FACT_NOT_VERIFIED"):
        StatementFactEvidenceV1(
            **{
                **target.model_dump(),
                "mapping": target.mapping.model_copy(update={"status": "provisional"}),
            }
        )


def test_reconciliation_does_not_silently_round_a_value_beyond_numeric_policy():
    request = request_for()
    facts = tuple(
        item.model_copy(
            update={
                "fact": item.fact.model_copy(
                    update={
                        "value": Decimal(
                            "100000000000000000000000000000000000000000000000000000000000001"
                        ),
                    }
                )
            }
        )
        if item.fact.normalized_field == "total_assets"
        else item
        for item in request.facts
    )
    result = project(replace_facts(request, facts))
    check = next(
        item
        for item in result.reconciliations
        if item.check_id == "assets_liabilities_equity"
    )
    assert check.status == "unresolved"
    assert check.difference is None
    assert check.issue_codes == ("STATEMENT_RECONCILIATION_PRECISION_EXCEEDED",)


@pytest.mark.parametrize(
    "cutoff,amendment_scope,expected",
    [
        ("2024-01-01T00:00:00Z", None, "reported"),
        ("2024-11-02T00:00:00Z", None, "unavailable"),
        ("2024-11-02T00:00:00Z", "unrelated", "reported"),
    ],
)
def test_cash_definitions_compete_only_after_cutoff_and_amendment_eligibility(
    cutoff, amendment_scope, expected
):
    request = request_for((AAPL_2023, AAPL_2024), cutoff=cutoff, columns=(AAPL_2023,))
    facts = tuple(
        item.model_copy(
            update={
                "cash_basis": "cash_and_equivalents",
                "fact": item.fact.model_copy(
                    update={
                        "is_amendment": amendment_scope is not None,
                        "amendment_scope": amendment_scope,
                    }
                ),
            }
        )
        if item.fact.accession_number == AAPL_2024
        and item.fact.normalized_field == "cash_flow_ending_balance"
        else item
        for item in request.facts
    )
    value = cell(project(replace_facts(request, facts)), "cash_flow_ending_balance")
    assert value.status == expected
    if expected == "unavailable":
        assert value.issue_codes == ("STATEMENT_CASH_DEFINITION_CONFLICT",)
    else:
        assert value.fact.accession_number == AAPL_2023


def test_cash_definition_change_marks_affected_rows_not_comparable():
    request = request_for((AAPL_2023, AAPL_2024))
    facts = tuple(
        item.model_copy(update={"cash_basis": "cash_and_equivalents"})
        if item.fact.normalized_field == "net_change_in_cash"
        and item.fact.period_end == date(2024, 9, 28)
        else item
        for item in request.facts
    )
    result = project(replace_facts(request, facts))
    comparison = next(item for item in result.comparability if item.affected_row_ids)
    assert comparison.status == "not_comparable"
    assert comparison.issue_codes == ("STATEMENT_CASH_DEFINITION_CHANGED",)
    assert comparison.affected_row_ids == ("net_change_in_cash",)
