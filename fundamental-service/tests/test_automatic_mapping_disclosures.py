"""Exact disclosure approval retains its accounting evidence and refusal cases."""

from datetime import date
from decimal import Decimal

import pytest

from fundamental_service.automatic_mapping import (
    AutomaticMappingDecisionV1,
    automatic_mapping_proposal,
    verify_automatic_mapping_replay,
)
from fundamental_service.automatic_mapping_disclosures import (
    STOCK_COMPENSATION_DISCLOSURE,
)
from fundamental_service.data_releases import (
    AutomaticMappingApprovalV1,
    DataReleaseError,
)
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import sha256_digest
from test_automatic_mapping import approve, case, evaluate
from test_issuer_operating_release import inventory


SENTENCE = (
    "Stock-based compensation expense was $141,936 in fiscal\u00a02025 "
    "and $59,657 in fiscal 2024."
)


def expense_case(tmp_path, *, text=None, changes=None, conflict=False, extra_facts=()):
    request, _, _, _ = case(tmp_path / "base")
    base = next(
        fact
        for fact in request.original.report.facts
        if fact.concept == "us-gaap:Revenues"
    )
    disclosure = base.model_copy(
        update={
            "concept": STOCK_COMPENSATION_DISCLOSURE,
            "value": text if text is not None else "<p>" + SENTENCE + "</p>",
            "is_numeric": False,
            "unit": None,
            "period_start": date(2025, 1, 1),
            "period_end": date(2025, 12, 31),
            **(changes or {}),
        }
    )
    extra = (disclosure, *extra_facts)
    if conflict:
        extra += (
            disclosure.model_copy(
                update={
                    "context_id": "conflicting-disclosure",
                    "value": disclosure.value.replace("141,936", "141,935"),
                }
            ),
        )
    return case(
        tmp_path / "source",
        normalize_revenue=False,
        extra=extra,
        proposal_changes={
            "source_concept": STOCK_COMPENSATION_DISCLOSURE,
            "normalized_field": "stock_based_compensation",
        },
    )


def test_exact_expense_sentence_uses_existing_accounting_transcription_and_repeat(
    tmp_path,
):
    request, store, roots, _ = expense_case(tmp_path)
    proposal = automatic_mapping_proposal(
        "stock_based_compensation", mapping_version=request.proposal.mapping_version
    )
    assert proposal.source_concept == request.proposal.source_concept
    receipt = approve(request, store, roots)
    decision = AutomaticMappingDecisionV1.model_validate_json(
        store.read(receipt.decision_publication.artifact.artifact_id)
    )
    assert decision.status == "approved"
    mapping = decision.mapping
    assert mapping.source_concept == "computed:stock_based_compensation"
    assert mapping.observation_scope is None
    assert mapping.accounting_rules.security_id is None
    rule = mapping.accounting_rules.periods[0]
    amount = rule.disclosed_amount
    assert amount.exact_quote == SENTENCE
    assert amount.amount_token == "141,936"
    assert rule.period.period_end == date(2025, 12, 31)
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=request.original.source,
        issuer_id=request.original.source.cik,
        normalized_field="stock_based_compensation",
        mapping=mapping,
    )
    assert len(candidates) == 1
    assert candidates[0].value == Decimal("141936")
    assert candidates[0].decimals == 0
    assert candidates[0].accounting_evidence.rule_set == mapping.accounting_rules
    assert candidates[0].accounting_evidence.source_facts[0].value == (
        "<p>" + SENTENCE + "</p>"
    )
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(receipt.approval_publication.artifact.artifact_id)
    )
    assert (
        verify_automatic_mapping_replay(approval, mapping, artifacts=store) == request
    )
    before = inventory(store.root)
    repeated = approve(request, ArtifactStore(store.root), roots)
    assert receipt.output_digest == repeated.output_digest
    assert not repeated.approval_publication.wrote
    assert before == inventory(store.root)
    forged = mapping.model_copy(
        update={"anchor_concept": "us-gaap:ShareBasedCompensation"}
    )
    with pytest.raises(DataReleaseError, match="retained policy evaluation"):
        verify_automatic_mapping_replay(approval, forged, artifacts=store)


@pytest.mark.parametrize(
    "text",
    (
        SENTENCE.replace("expense was", "expense for options was"),
        "Option " + SENTENCE,
        SENTENCE.replace("$141,936", "$141,936 million"),
        SENTENCE.replace("$141,936", "($141,936)"),
        SENTENCE.replace("$141,936", "$141,936.50"),
        SENTENCE.replace("$141,936", "$14,1936"),
        SENTENCE.replace("2025", "2024"),
        SENTENCE.replace("2024", "2023"),
        SENTENCE + " " + SENTENCE,
        "No material stock-based compensation expense was incurred.",
    ),
)
def test_partial_scaled_ambiguous_or_other_period_sentences_abstain(tmp_path, text):
    request, store, roots, _ = expense_case(tmp_path, text=text)
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert "MAPPING_NO_ELIGIBLE_OBSERVATIONS" in decision.reason_codes
    assert decision.rejected_observations
    assert approve(request, store, roots).approval_publication is None


@pytest.mark.parametrize(
    "changes,reason",
    (
        (
            {"namespace_uri": "https://example.com/us-gaap"},
            "MAPPING_NAMESPACE_UNSUPPORTED",
        ),
        ({"entity_identifier": "999"}, "MAPPING_ISSUER_MISMATCH"),
        ({"dimensions": (("axis", "member"),)}, "MAPPING_SCOPE_UNSUPPORTED"),
        ({"security_scope": "other-class"}, "MAPPING_SCOPE_UNSUPPORTED"),
        ({"unit": "iso4217:EUR"}, "MAPPING_UNIT_UNSUPPORTED"),
        ({"period_end": date(2024, 12, 31)}, "MAPPING_PERIOD_UNSUPPORTED"),
        ({"period_start": date(2025, 10, 1)}, "MAPPING_PERIOD_UNSUPPORTED"),
        ({"period_start": date(2025, 1, 10)}, "MAPPING_PERIOD_UNSUPPORTED"),
    ),
)
def test_disclosure_requires_original_issuer_period_scope_and_unit(
    tmp_path, changes, reason
):
    request, store, _, _ = expense_case(tmp_path, changes=changes)
    decision = evaluate(request, store)
    assert decision.status == "abstain"
    assert reason in {item.reason_code for item in decision.rejected_observations}


def test_conflicting_disclosures_never_select_an_amount(tmp_path):
    request, store, roots, _ = expense_case(tmp_path, conflict=True)
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert decision.reason_codes == ("MAPPING_OBSERVATION_CONFLICT",)
    assert len(decision.eligible_observation_digests) == 2
    assert approve(request, store, roots).approval_publication is None


def test_document_scale_notice_blocks_an_otherwise_exact_dollar_sentence(tmp_path):
    request, store, roots, _ = expense_case(
        tmp_path, text="Amounts in thousands. " + SENTENCE
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain"
    assert decision.reason_codes == ("MAPPING_DISCLOSURE_SCALE_UNRESOLVED",)
    assert decision.eligible_observation_digests
    assert approve(request, store, roots).approval_publication is None


def test_unknown_second_consolidated_disclosure_cannot_be_ignored(tmp_path):
    request, store, _, _ = expense_case(tmp_path)
    original = next(
        fact
        for fact in request.original.report.facts
        if fact.concept == STOCK_COMPENSATION_DISCLOSURE
    )
    ambiguous = original.model_copy(
        update={
            "context_id": "unknown-total",
            "value": "The stock-based compensation expense was approximately $2 million.",
        }
    )
    request, store, _, _ = case(
        tmp_path / "ambiguous-original",
        extra=(original, ambiguous),
        proposal_changes={
            "source_concept": STOCK_COMPENSATION_DISCLOSURE,
            "normalized_field": "stock_based_compensation",
        },
    )
    result = evaluate(request, store)
    assert result.status == "abstain"
    assert "MAPPING_DISCLOSURE_SENTENCE_UNSUPPORTED" in result.reason_codes
    assert sha256_digest(original) in result.eligible_observation_digests


def test_second_current_period_disclosure_with_inconsistent_years_abstains(tmp_path):
    request, _, _, _ = expense_case(tmp_path)
    original = next(
        fact
        for fact in request.original.report.facts
        if fact.concept == STOCK_COMPENSATION_DISCLOSURE
    )
    conflicting_period = original.model_copy(
        update={"context_id": "wrong-year", "value": SENTENCE.replace("2025", "2023")}
    )
    request, store, _, _ = case(
        tmp_path / "inconsistent-period",
        extra=(original, conflicting_period),
        proposal_changes={
            "source_concept": STOCK_COMPENSATION_DISCLOSURE,
            "normalized_field": "stock_based_compensation",
        },
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain"
    assert decision.reason_codes == ("MAPPING_DISCLOSURE_PERIOD_MISMATCH",)
    assert sha256_digest(original) in decision.eligible_observation_digests


def test_disclosure_certificate_cannot_authorize_different_source_bytes(tmp_path):
    request, store, roots, _ = expense_case(tmp_path)
    receipt = approve(request, store, roots)
    decision = evaluate(request, store)
    certificate = AutomaticMappingApprovalV1.model_validate_json(
        store.read(receipt.approval_publication.artifact.artifact_id)
    )
    changed_rules = decision.mapping.accounting_rules.model_copy(
        update={"parser_input_hash": "f" * 64}
    )
    forged = decision.mapping.model_copy(update={"accounting_rules": changed_rules})
    assert sha256_digest(forged) != certificate.mapping_digest
    with pytest.raises(DataReleaseError, match="retained policy evaluation"):
        verify_automatic_mapping_replay(certificate, forged, artifacts=store)


OPTION_COST = (
    "There was $4,181 of unrecognized stock-based compensation as of December 31, "
    "2025 related to nonvested options, which we expect to recognize in the first "
    "quarter of fiscal 2026."
)


def option_cost_case(tmp_path, monkeypatch, *, text=OPTION_COST, **kwargs):
    from fundamental_service import automatic_mapping_disclosures as policy
    from fundamental_service.arelle_parser import fact_semantic_digest

    request, store, roots, bundle = expense_case(
        tmp_path, text="<p>" + text + "</p>", **kwargs
    )
    request = request.model_copy(
        update={
            "proposal": request.proposal.model_copy(
                update={"normalized_field": "equity_award_unrecognized_compensation"}
            )
        }
    )
    source = request.original.source
    monkeypatch.setattr(
        policy,
        "_OPTION_COST_ORIGINALS",
        {
            (source.cik, source.accession_number): (
                source.content_hash,
                fact_semantic_digest(request.original.report),
            )
        },
    )
    return request, store, roots, bundle


def test_registered_option_cost_is_dated_reconstructible_and_idempotent(
    tmp_path, monkeypatch
):
    request, store, roots, _ = option_cost_case(tmp_path, monkeypatch)
    proposal = automatic_mapping_proposal(
        "equity_award_unrecognized_compensation",
        mapping_version="synthetic-v1",
        original=request.original,
    )
    assert proposal.source_concept == STOCK_COMPENSATION_DISCLOSURE
    first = approve(request, store, roots)
    decision = AutomaticMappingDecisionV1.model_validate_json(
        store.read(first.decision_publication.artifact.artifact_id)
    )
    assert decision.status == "approved"
    rule = decision.mapping.accounting_rules.periods[0]
    assert rule.period.instant
    assert rule.disclosed_amount.date.period_end == date(2025, 12, 31)
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=request.original.source,
        issuer_id=request.original.source.cik,
        normalized_field="equity_award_unrecognized_compensation",
        mapping=decision.mapping,
    )
    assert len(candidates) == 1
    assert candidates[0].instant == date(2025, 12, 31)
    assert candidates[0].value == Decimal(4181)
    assert candidates[0].accounting_evidence.source_facts[0].instant is None
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(first.approval_publication.artifact.artifact_id)
    )
    assert (
        verify_automatic_mapping_replay(approval, decision.mapping, artifacts=store)
        == request
    )
    before = inventory(store.root)
    second = approve(request, ArtifactStore(store.root), roots)
    assert first.output_digest == second.output_digest
    assert not any(
        p.wrote
        for p in (
            second.input_publication,
            second.decision_publication,
            second.approval_publication,
        )
    )
    assert inventory(store.root) == before


@pytest.mark.parametrize("mutation", ["issuer", "source", "facts", "unregistered"])
def test_option_cost_never_inherits_another_originals_classification(
    tmp_path, monkeypatch, mutation
):
    from fundamental_service import automatic_mapping_disclosures as policy

    request, store, _, _ = option_cost_case(tmp_path, monkeypatch)
    original = request.original
    if mutation == "facts":
        original = original.model_copy(
            update={
                "report": original.report.model_copy(
                    update={"facts": original.report.facts[:-1]}
                )
            }
        )
    elif mutation == "unregistered":
        monkeypatch.setattr(policy, "_OPTION_COST_ORIGINALS", {})
    else:
        original = original.model_copy(
            update={
                "source": original.source.model_copy(
                    update={"cik": "0000000999"}
                    if mutation == "issuer"
                    else {"content_hash": "f" * 64}
                )
            }
        )
    request = request.model_copy(update={"original": original})
    assert (
        automatic_mapping_proposal(
            "equity_award_unrecognized_compensation",
            mapping_version="synthetic-v1",
            original=original,
        )
        is None
    )
    result = evaluate(request, store)
    assert result.status == "abstain" and result.mapping is None
    assert any(code.startswith("MAPPING_OPTION_COST_") for code in result.reason_codes)


@pytest.mark.parametrize(
    "text",
    [
        OPTION_COST.replace("December 31", "December 30"),
        OPTION_COST.replace("2025 related", "2024 related"),
        OPTION_COST.replace("fiscal 2026", "fiscal 2027"),
        OPTION_COST.replace("$4,181", "$4,181 million"),
        OPTION_COST.replace("$4,181", "$4,181.50"),
        OPTION_COST.replace("nonvested options", "some nonvested options"),
        OPTION_COST.replace("nonvested options", "restricted stock units"),
        OPTION_COST + " " + OPTION_COST,
    ],
)
def test_unsupported_option_cost_sentences_retain_abstention(
    tmp_path, monkeypatch, text
):
    request, store, roots, _ = option_cost_case(tmp_path, monkeypatch, text=text)
    result = evaluate(request, store)
    assert result.status == "abstain" and result.mapping is None
    assert result.rejected_observations
    assert approve(request, store, roots).approval_publication is None
