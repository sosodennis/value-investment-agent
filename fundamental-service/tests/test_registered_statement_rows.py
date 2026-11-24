"""Reviewed primary rows select source concepts, never stored golden amounts."""

from dataclasses import replace
from datetime import date
import hashlib
from io import BytesIO
from zipfile import ZipFile

import pytest
from lxml import html

import fundamental_service.registered_statement_rows as rows
from fundamental_service.registered_statement_row_registry import (
    PrimaryStatementScope,
    PrimaryStatementRowLocator,
)
from fundamental_service.automatic_mapping import automatic_mapping_proposals
from fundamental_service.registered_revenue import CONTRACT_REVENUE
from test_automatic_mapping import case, evaluate
from test_annual_statement_fixtures import COHORT, GOLDEN, _content, _local_name, _text
from test_annual_statement_fixtures import retained_root as retained_source_fixture

retained_root = retained_source_fixture

CASH = "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
UNRESTRICTED = "us-gaap:CashAndCashEquivalentsAtCarryingValue"
CHANGE = "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect"


def registered_case(tmp_path, monkeypatch):
    base, *_ = case(tmp_path / "base")
    other = next(
        f for f in base.original.report.facts if f.concept == "us-gaap:Revenues"
    )
    changes = {
        "instant": date(2025, 12, 31),
        "period_start": None,
        "period_end": None,
        "concept": CASH,
        "value": "100",
    }
    request, store, roots, _ = case(
        tmp_path / "active",
        observation_changes=changes,
        proposal_changes={
            "source_concept": CASH,
            "normalized_field": "cash_flow_ending_balance",
        },
        extra=(
            other.model_copy(update=changes | {"concept": UNRESTRICTED, "value": "90"}),
        ),
    )
    original = request.original
    scope = PrimaryStatementScope(
        raw_content_hash=original.source.content_hash,
        annual_periods=((date(2025, 1, 1), date(2025, 12, 31)),),
        revenue_concept=CONTRACT_REVENUE,
        cash_balance_concept=CASH,
        cash_change_concept=CHANGE,
        cash_effect_concept=None,
        parser_input_hash=original.source.parser_input_hash,
        locators=(
            PrimaryStatementRowLocator(
                "cash_flow_ending_balance",
                1,
                2,
                tuple(
                    sorted(
                        {
                            f.context_id
                            for f in original.report.facts
                            if f.concept == CASH
                        }
                    )
                ),
            ),
        ),
    )
    monkeypatch.setitem(
        rows.PRIMARY_STATEMENTS,
        (original.source.cik, original.source.accession_number),
        scope,
    )
    return request, store, roots


def test_primary_cash_scope_selects_reported_basis_and_keeps_balance_sheet_cash(
    tmp_path, monkeypatch
):
    request, store, _ = registered_case(tmp_path, monkeypatch)
    proposals = automatic_mapping_proposals(
        "cash_flow_ending_balance",
        mapping_version=request.proposal.mapping_version,
        original=request.original,
        observed_only=True,
    )
    assert len(proposals) == 1 and proposals[0].source_concept == CASH
    decision = evaluate(request, store)
    assert decision.status == "approved"
    assert decision.primary_statement_scope is not None
    assert (
        decision.primary_statement_scope.selection_policy
        == "reviewed-original-primary-row-v1"
    )
    assert decision.primary_statement_scope.table_index == 1
    assert decision.primary_statement_scope.row_index == 2
    assert {
        f.value
        for f in rows.select_primary_statement_observations(
            request.original, "cash_flow_ending_balance"
        ).selected
    } == {"100"}
    assert any(
        f.concept == UNRESTRICTED and f.value == "90"
        for f in request.original.report.facts
    )


def test_other_cash_concept_cannot_reuse_primary_row_classification(
    tmp_path, monkeypatch
):
    request, store, _ = registered_case(tmp_path, monkeypatch)
    changed = request.model_copy(
        update={
            "proposal": request.proposal.model_copy(
                update={"source_concept": UNRESTRICTED}
            )
        }
    )
    decision = evaluate(changed, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert "MAPPING_STATEMENT_ROW_CONCEPT_MISMATCH" in decision.reason_codes


def test_changed_raw_original_and_unpresented_row_have_distinct_refusals(
    tmp_path, monkeypatch
):
    request, store, _ = registered_case(tmp_path, monkeypatch)
    original = request.original
    selection = rows.select_primary_statement_observations(
        original, "effect_of_exchange_rates_on_cash"
    )
    assert selection.reason_codes == ("MAPPING_STATEMENT_ROW_NOT_PRESENTED",)
    key = original.source.cik, original.source.accession_number
    monkeypatch.setitem(
        rows.PRIMARY_STATEMENTS,
        key,
        replace(rows.PRIMARY_STATEMENTS[key], raw_content_hash="b" * 64),
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert "MAPPING_STATEMENT_ROW_SOURCE_MISMATCH" in decision.reason_codes


def test_registered_primary_scopes_bind_frozen_sources_without_amounts():
    originals = {(f["issuer_id"], f["accession_number"]): f for f in GOLDEN["filings"]}
    assert rows.PRIMARY_STATEMENTS.keys() == originals.keys()
    for key, scope in rows.PRIMARY_STATEMENTS.items():
        filing = originals[key]
        assert scope.raw_content_hash == filing["source_sha256"]
        for statement in filing["statements"]:
            for row in statement["rows"]:
                if (
                    row["row_id"] != "revenue"
                    and row["row_id"] not in rows.CASH_STATEMENT_ROLES
                ):
                    continue
                expected = (
                    row["values"][0]["concept_qname"]
                    if row["status"] == "reported"
                    else None
                )
                assert scope.concept_for(row["row_id"]) == expected


@pytest.mark.parametrize(
    "filing", COHORT["filings"], ids=lambda f: f["accession_number"]
)
def test_registered_primary_scope_hash_is_the_retained_original(retained_root, filing):
    source = next(s for s in filing["source_records"] if s["uri"].endswith(".htm"))
    raw = _content(retained_root, source)
    scope = rows.PRIMARY_STATEMENTS[(filing["issuer_id"], filing["accession_number"])]
    assert hashlib.sha256(raw).hexdigest() == scope.raw_content_hash
    archive_source = next(
        s for s in filing["source_records"] if s["uri"].endswith("-xbrl.zip")
    )
    with ZipFile(BytesIO(_content(retained_root, archive_source))) as archive:
        parser_input = archive.read(filing["primary_document"])
    assert hashlib.sha256(parser_input).hexdigest() == scope.parser_input_hash
    document = html.fromstring(raw)
    contexts = {
        node.get("id"): node
        for node in document.iter()
        if _local_name(node) == "context"
    }
    golden = next(
        f
        for f in GOLDEN["filings"]
        if f["accession_number"] == filing["accession_number"]
    )
    for statement in golden["statements"]:
        table = document.xpath("//table")[statement["table_index"]]
        for row in statement["rows"]:
            if row["status"] != "reported" or (
                row["row_id"] != "revenue"
                and row["row_id"] not in rows.CASH_STATEMENT_ROLES
            ):
                continue
            original_row = table.xpath("./tbody/tr|./tr")[row["row_index"]]
            facts = [
                node
                for node in original_row.iter()
                if _local_name(node) == "nonfraction"
            ]
            assert {node.get("name") for node in facts} == {
                scope.concept_for(row["row_id"])
            }
            locator = next(
                locator for locator in scope.locators if locator.row_id == row["row_id"]
            )
            assert locator.table_index == statement["table_index"]
            assert locator.row_index == row["row_index"]
            assert set(locator.context_ids) == {
                node.get("contextref") for node in facts
            }
            if row["row_id"] == "revenue":
                periods = set()
                for fact in facts:
                    dates = {
                        _local_name(node): _text(node)
                        for node in contexts[fact.get("contextref")].iter()
                        if _local_name(node) in {"startdate", "enddate"}
                    }
                    periods.add(
                        (
                            date.fromisoformat(dates["startdate"]),
                            date.fromisoformat(dates["enddate"]),
                        )
                    )
                assert periods == set(scope.annual_periods)
