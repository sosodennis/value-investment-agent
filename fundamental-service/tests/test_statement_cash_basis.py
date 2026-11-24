from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

import fundamental_service.registered_statement_rows as rows
from fundamental_service.data_releases import DataReleaseError
from fundamental_service.registered_statement_row_registry import (
    PrimaryStatementRowLocator,
    PrimaryStatementScope,
)
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from test_automatic_mapping import case, evaluate

FX = "us-gaap:EffectOfExchangeRateOnCashAndCashEquivalents"
CASH = "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
CHANGE = "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect"
ROW = "effect_of_exchange_rates_on_cash"


def fx_case(tmp_path, monkeypatch, *, changes=None):
    base, *_ = case(tmp_path / "base")
    observed = next(
        fact
        for fact in base.original.report.facts
        if fact.concept == "us-gaap:Revenues" and fact.period_end == date(2025, 12, 31)
    )
    request, store, _, _ = case(
        tmp_path / "fx",
        observation_changes={"concept": FX, "value": "-201", **(changes or {})},
        proposal_changes={"source_concept": FX, "normalized_field": ROW},
    )
    original = request.original
    scope = PrimaryStatementScope(
        raw_content_hash=original.source.content_hash,
        annual_periods=((date(2025, 1, 1), date(2025, 12, 31)),),
        revenue_concept="us-gaap:Revenues",
        cash_balance_concept=CASH,
        cash_change_concept=CHANGE,
        cash_effect_concept=FX,
        parser_input_hash=original.source.parser_input_hash,
        locators=(PrimaryStatementRowLocator(ROW, 1, 2, (observed.context_id,)),),
        us_gaap_namespace=observed.namespace_uri,
    )
    monkeypatch.setitem(
        rows.PRIMARY_STATEMENTS,
        (original.source.cik, original.source.accession_number),
        scope,
    )
    return request, store, scope


def test_approved_primary_fx_preserves_raw_concept_and_uses_its_cash_rollforward(
    tmp_path, monkeypatch
):
    request, store, _ = fx_case(tmp_path, monkeypatch)
    decision = evaluate(request, store)
    assert decision.status == "approved", decision.reason_codes
    assert decision.mapping is not None
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=request.original.source,
        issuer_id=request.original.source.cik,
        normalized_field=ROW,
        mapping=decision.mapping,
    )
    assert len(candidates) == 1
    assert candidates[0].concept == FX and candidates[0].value == Decimal("-201")
    assert decision.primary_statement_scope.context_ids == (candidates[0].context_id,)
    assert (
        rows.statement_cash_basis(request.original, ROW, FX)
        == (
            rows.statement_cash_basis(
                request.original, "cash_flow_ending_balance", CASH
            )
        )
        == "cash_equivalents_and_restricted_cash"
    )


@pytest.mark.parametrize(
    "changes,reason",
    (
        (
            {"context_id": "unreviewed-note-context"},
            "MAPPING_STATEMENT_CONTEXT_SCOPE_UNREVIEWED",
        ),
        ({"dimensions": (("axis", "member"),)}, "MAPPING_SCOPE_UNSUPPORTED"),
        (
            {"period_start": date(2025, 10, 1)},
            "MAPPING_STATEMENT_PERIOD_SCOPE_UNREVIEWED",
        ),
        (
            {"namespace_uri": "https://example.org/us-gaap"},
            "MAPPING_NAMESPACE_UNSUPPORTED",
        ),
        ({"entity_identifier": "999"}, "MAPPING_ISSUER_MISMATCH"),
        ({"unit": "iso4217:EUR"}, "ORIGINAL_ISSUER_CURRENCY_UNSUPPORTED"),
    ),
)
def test_fx_inheritance_does_not_admit_unreviewed_observations(
    tmp_path, monkeypatch, changes, reason
):
    request, store, _ = fx_case(tmp_path, monkeypatch, changes=changes)
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert "MAPPING_NO_ELIGIBLE_OBSERVATIONS" in decision.reason_codes
    assert reason in set(decision.reason_codes) | {
        item.reason_code for item in decision.rejected_observations
    }


@pytest.mark.parametrize("field", ("raw_content_hash", "parser_input_hash"))
def test_fx_cannot_inherit_from_another_original(tmp_path, monkeypatch, field):
    request, store, scope = fx_case(tmp_path, monkeypatch)
    monkeypatch.setitem(
        rows.PRIMARY_STATEMENTS,
        (request.original.source.cik, request.original.source.accession_number),
        replace(scope, **{field: "b" * 64}),
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert "MAPPING_STATEMENT_ROW_SOURCE_MISMATCH" in decision.reason_codes


def test_statement_original_gate_requires_the_registered_taxonomy_namespace(
    tmp_path, monkeypatch
):
    request, _, _ = fx_case(tmp_path, monkeypatch)
    original = request.original
    changed = original.model_copy(
        update={
            "report": original.report.model_copy(
                update={
                    "facts": tuple(
                        fact.model_copy(
                            update={"namespace_uri": "http://fasb.org/us-gaap/2024"}
                        )
                        if fact.concept.startswith("us-gaap:")
                        else fact
                        for fact in original.report.facts
                    )
                }
            )
        }
    )
    with pytest.raises(DataReleaseError) as error:
        rows.require_registered_primary_statement_scope(changed)
    assert error.value.code == "STATEMENT_ORIGINAL_SCOPE_MISMATCH"


@pytest.mark.parametrize("scope_change", ("unregistered", "unpresented", "no_locator"))
def test_fx_requires_an_approved_presented_primary_row(
    tmp_path, monkeypatch, scope_change
):
    request, _, scope = fx_case(tmp_path, monkeypatch)
    key = request.original.source.cik, request.original.source.accession_number
    if scope_change == "unregistered":
        monkeypatch.delitem(rows.PRIMARY_STATEMENTS, key)
    else:
        monkeypatch.setitem(
            rows.PRIMARY_STATEMENTS,
            key,
            replace(
                scope,
                **(
                    {"cash_effect_concept": None}
                    if scope_change == "unpresented"
                    else {"locators": ()}
                ),
            ),
        )
    assert rows.statement_cash_basis(request.original, ROW, FX) is None


def test_fx_cannot_borrow_its_basis_for_another_concept(tmp_path, monkeypatch):
    request, store, _ = fx_case(tmp_path, monkeypatch)
    other = "us-gaap:EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations"
    assert rows.statement_cash_basis(request.original, ROW, other) is None
    changed = request.model_copy(
        update={
            "proposal": request.proposal.model_copy(update={"source_concept": other})
        }
    )
    decision = evaluate(changed, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert "MAPPING_STATEMENT_ROW_CONCEPT_MISMATCH" in decision.reason_codes
