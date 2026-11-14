"""Cash-purchase tags cannot silently establish continuing-operations scope."""

from datetime import date

import pytest

from fundamental_service import registered_capital_expenditure as policy
from fundamental_service.arelle_parser import fact_semantic_digest
from fundamental_service.automatic_mapping import (
    AutomaticMappingApprovalV1,
    AutomaticMappingDecisionV1,
    verify_automatic_mapping_replay,
)
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import sha256_digest
from test_automatic_mapping import approve, case, evaluate
from test_issuer_operating_release import inventory


def capital_expenditure_case(
    tmp_path, monkeypatch, *, register=True, continuing=(2025,)
):
    template, _, _, _ = case(tmp_path / "template")
    base = next(
        f for f in template.original.report.facts if f.concept == "us-gaap:Revenues"
    )
    facts = tuple(
        base.model_copy(
            update={
                "concept": policy.CAPITAL_EXPENDITURE,
                "value": "58476000",
                "decimals": "-3",
                "context_id": f"cash-capex-{year}",
                "period_start": date(year, 1, 1),
                "period_end": date(year, 12, 31),
            }
        )
        for year in (2024, 2025)
    )
    note = base.model_copy(
        update={
            "concept": "us-gaap:DisposalGroupsIncludingDiscontinuedOperationsDisclosureTextBlock",
            "is_numeric": False,
            "unit": None,
            "value": "Cash flows summarize discontinued and continuing operations together.",
            "context_id": "discontinued-scope",
        }
    )
    request, store, roots, bundle = case(
        tmp_path / "actual",
        extra=(*facts, note),
        proposal_changes={
            "source_concept": policy.CAPITAL_EXPENDITURE,
            "normalized_field": "capital_expenditure",
        },
    )
    if register:
        source = request.original.source
        monkeypatch.setattr(
            policy,
            "_ORIGINALS",
            {
                (
                    source.cik,
                    source.accession_number,
                ): policy.OriginalCapitalExpenditureScope(
                    source.parser_input_hash,
                    fact_semantic_digest(request.original.report),
                    continuing,
                )
            },
        )
    return request, store, roots, bundle


def test_unclassified_original_cannot_approve_cash_tag(tmp_path, monkeypatch):
    request, store, _, _ = capital_expenditure_case(
        tmp_path, monkeypatch, register=False
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert "MAPPING_CAPEX_SCOPE_UNREVIEWED" in decision.reason_codes


def test_only_classified_period_is_signed_replayed_and_reused(tmp_path, monkeypatch):
    request, store, roots, _ = capital_expenditure_case(tmp_path, monkeypatch)
    receipt = approve(request, store, roots)
    decision = AutomaticMappingDecisionV1.model_validate_json(
        store.read(receipt.decision_publication.artifact.artifact_id)
    )
    assert decision.status == "approved" and decision.mapping is not None
    rejected = {
        r.observation_digest: r.reason_code for r in decision.rejected_observations
    }
    by_digest = {sha256_digest(f): f for f in request.original.report.facts}
    assert {by_digest[k].period_end.year for k in rejected} == {2024}
    assert set(rejected.values()) == {"MAPPING_CAPEX_CONTINUING_SCOPE_UNRESOLVED"}
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=request.original.source,
        issuer_id=request.original.source.cik,
        normalized_field="capital_expenditure",
        mapping=decision.mapping,
    )
    assert len(candidates) == 1 and candidates[0].period_end == date(2025, 12, 31)
    before = inventory(store.root)
    repeat = approve(request, store, roots)
    assert (repeat.input_digest, repeat.output_digest) == (
        receipt.input_digest,
        receipt.output_digest,
    )
    assert not any(
        p.wrote
        for p in (
            repeat.input_publication,
            repeat.decision_publication,
            repeat.approval_publication,
        )
    )
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(receipt.approval_publication.artifact.artifact_id)
    )
    assert (
        verify_automatic_mapping_replay(
            approval, decision.mapping, artifacts=ArtifactStore(store.root)
        )
        == request
    )
    assert inventory(store.root) == before


@pytest.mark.parametrize(
    "change",
    (
        "issuer",
        "accession",
        "parser_input",
        "amount",
        "precision",
        "passage",
        "dimension",
        "period",
    ),
)
def test_registered_scope_refuses_changed_source(tmp_path, monkeypatch, change):
    request, store, _, _ = capital_expenditure_case(tmp_path, monkeypatch)
    original = request.original
    if change in {"issuer", "accession", "parser_input"}:
        field, value = {
            "issuer": ("cik", "0000000002"),
            "accession": ("accession_number", "0000000001-25-999999"),
            "parser_input": ("parser_input_hash", "f" * 64),
        }[change]
        original = original.model_copy(
            update={"source": original.source.model_copy(update={field: value})}
        )
    else:
        facts = list(original.report.facts)
        index = next(
            i
            for i, f in enumerate(facts)
            if f.concept
            == (
                "us-gaap:DisposalGroupsIncludingDiscontinuedOperationsDisclosureTextBlock"
                if change == "passage"
                else policy.CAPITAL_EXPENDITURE
            )
        )
        updates = {
            "amount": {"value": "58476001"},
            "precision": {"decimals": "-6"},
            "passage": {"value": "Changed classification passage."},
            "dimension": {"dimensions": (("axis", "member"),)},
            "period": {"period_end": date(2023, 12, 31)},
        }
        facts[index] = facts[index].model_copy(update=updates[change])
        original = original.model_copy(
            update={
                "report": original.report.model_copy(update={"facts": tuple(facts)})
            }
        )
    decision = evaluate(request.model_copy(update={"original": original}), store)
    assert decision.status == "abstain" and decision.mapping is None
    assert any(code.startswith("MAPPING_CAPEX_") for code in decision.reason_codes)


def test_no_classified_period_retains_all_unresolved_observations(
    tmp_path, monkeypatch
):
    request, store, _, _ = capital_expenditure_case(
        tmp_path, monkeypatch, continuing=()
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert decision.reason_codes == ("MAPPING_NO_ELIGIBLE_OBSERVATIONS",)
    assert len(decision.rejected_observations) == 2
    assert {r.reason_code for r in decision.rejected_observations} == {
        "MAPPING_CAPEX_CONTINUING_SCOPE_UNRESOLVED"
    }


def test_source_order_does_not_change_scope_or_rejection_order(tmp_path, monkeypatch):
    request, store, _, _ = capital_expenditure_case(tmp_path, monkeypatch)
    first = evaluate(request, store)
    original = request.original.model_copy(
        update={
            "report": request.original.report.model_copy(
                update={"facts": tuple(reversed(request.original.report.facts))}
            )
        }
    )
    second = evaluate(request.model_copy(update={"original": original}), store)
    assert first.status == second.status == "approved"
    assert first.mapping == second.mapping
    assert first.rejected_observations == second.rejected_observations
    assert first.eligible_observation_digests == second.eligible_observation_digests
