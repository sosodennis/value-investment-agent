"""Reported equity components, source scope and signed mapping reconstruction."""

from datetime import date
from decimal import Decimal

import pytest

from fundamental_service import registered_noncontrolling_equity as policy
from fundamental_service.arelle_parser import fact_semantic_digest
from fundamental_service.automatic_mapping import (
    AutomaticMappingApprovalV1,
    AutomaticMappingDecisionV1,
    automatic_mapping_proposal,
    verify_automatic_mapping_replay,
)
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import sha256_digest
from test_automatic_mapping import approve, case, evaluate
from test_issuer_operating_release import inventory


def equity_case(tmp_path, monkeypatch, *, totals=("100", "90"), change=None):
    template, _, _, _ = case(tmp_path / "template")
    base = next(f for f in template.original.report.facts if f.is_numeric)
    facts = [
        base.model_copy(
            update={
                "concept": concept,
                "context_id": f"equity-{year}",
                "value": value,
                "instant": date(year, 12, 31),
                "period_start": None,
                "period_end": None,
                "decimals": "0",
            }
        )
        for year, amounts in ((2024, (totals[0], "100")), (2025, (totals[1], "80")))
        for concept, value in zip((policy.TOTAL_EQUITY, policy.PARENT_EQUITY), amounts)
    ]
    if change:
        facts = change(facts)
    request, store, roots, bundle = case(
        tmp_path / "actual",
        extra=tuple(facts),
        proposal_changes={
            "source_concept": policy.NONCONTROLLING_EQUITY,
            "normalized_field": "noncontrolling_interests",
        },
    )
    source = request.original.source
    monkeypatch.setattr(
        policy,
        "_ORIGINALS",
        {
            (source.cik, source.accession_number): policy.OriginalClassification(
                source.content_hash,
                fact_semantic_digest(request.original.report),
                (date(2024, 12, 31), date(2025, 12, 31)),
            )
        },
    )
    return request, store, roots, bundle


def test_reported_equity_difference_survives_signed_replay_and_unchanged_repeat(
    tmp_path, monkeypatch
):
    request, store, roots, _ = equity_case(tmp_path, monkeypatch)
    proposal = automatic_mapping_proposal(
        "noncontrolling_interests",
        original=request.original,
        mapping_version=request.proposal.mapping_version,
    )
    assert proposal.source_concept == policy.NONCONTROLLING_EQUITY
    receipt = approve(request, store, roots)
    decision = AutomaticMappingDecisionV1.model_validate_json(
        store.read(receipt.decision_publication.artifact.artifact_id)
    )
    assert decision.status == "approved"
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=request.original.source,
        issuer_id=request.original.source.cik,
        normalized_field="noncontrolling_interests",
        mapping=decision.mapping,
    )
    assert {f.instant.year: f.value for f in candidates} == {
        2024: Decimal("0"),
        2025: Decimal("10"),
    }
    assert all(
        c.accounting_evidence.period_rule.disposition == "derived"
        and {f.concept for f in c.accounting_evidence.source_facts}
        == {policy.TOTAL_EQUITY, policy.PARENT_EQUITY}
        and {f.decimals for f in c.accounting_evidence.source_facts} == {"0"}
        for c in candidates
    )
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(receipt.approval_publication.artifact.artifact_id)
    )
    before = inventory(store.root)
    assert (
        verify_automatic_mapping_replay(approval, decision.mapping, artifacts=store)
        == request
    )
    repeat = approve(request, store, roots)
    assert repeat.output_digest == receipt.output_digest
    assert not any(
        p.wrote
        for p in (
            repeat.input_publication,
            repeat.decision_publication,
            repeat.approval_publication,
        )
    )
    assert inventory(store.root) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"unit": "iso4217:EUR"},
        {"namespace_uri": "https://example.test/extension"},
        {"entity_identifier": "9999999"},
        {"entity_scheme": "https://example.test/issuer"},
        {"consolidation_scope": "unconsolidated"},
        {"security_scope": "foreign-security"},
        {"decimals": None},
        {"decimals": "-3"},
        {"value": "NaN"},
        {"value": "-1"},
        {"period_start": date(2024, 1, 1)},
    ],
)
def test_invalid_equity_component_retains_refusal(tmp_path, monkeypatch, changes):
    request, store, _, _ = equity_case(
        tmp_path,
        monkeypatch,
        change=lambda facts: [facts[0].model_copy(update=changes), *facts[1:]],
    )
    result = evaluate(request, store)
    assert result.status == "abstain" and result.mapping is None
    assert "MAPPING_NONCONTROLLING_COMPONENT_INVALID" in result.reason_codes


@pytest.mark.parametrize(
    "change",
    [lambda fs: fs[1:], lambda fs: [*fs, fs[0].model_copy(update={"value": "101"})]],
)
def test_missing_or_conflicting_total_is_not_assumed_zero(
    tmp_path, monkeypatch, change
):
    request, store, _, _ = equity_case(tmp_path, monkeypatch, change=change)
    result = evaluate(request, store)
    assert result.status == "abstain" and result.mapping is None
    assert any(
        reason in result.reason_codes
        for reason in (
            "MAPPING_NONCONTROLLING_COMPONENT_MISSING",
            "MAPPING_OBSERVATION_CONFLICT",
        )
    )


def test_total_below_parent_refuses_inconsistent_equity(tmp_path, monkeypatch):
    request, store, _, _ = equity_case(tmp_path, monkeypatch, totals=("99", "90"))
    assert (
        "MAPPING_NONCONTROLLING_EQUITY_INCONSISTENT"
        in evaluate(request, store).reason_codes
    )


def test_changed_original_and_unregistered_issuer_cannot_reuse_scope(
    tmp_path, monkeypatch
):
    request, _, _, _ = equity_case(tmp_path, monkeypatch)
    source = request.original.source
    foreign = request.original.model_copy(
        update={"source": source.model_copy(update={"cik": "0009999999"})}
    )
    assert policy.select_registered_noncontrolling_equity(foreign).reason_codes == (
        "MAPPING_NONCONTROLLING_SCOPE_UNREVIEWED",
    )
    facts = request.original.report.facts
    changed = request.original.model_copy(
        update={
            "report": request.original.report.model_copy(
                update={"facts": (*facts, facts[-1].model_copy(update={"value": "81"}))}
            )
        }
    )
    assert policy.select_registered_noncontrolling_equity(changed).reason_codes == (
        "MAPPING_NONCONTROLLING_SOURCE_MISMATCH",
    )
    assert (
        automatic_mapping_proposal(
            "noncontrolling_interests", mapping_version="test", original=foreign
        )
        is None
    )


def test_equivalent_duplicates_and_source_order_preserve_decision(
    tmp_path, monkeypatch
):
    request, store, _, _ = equity_case(
        tmp_path, monkeypatch, change=lambda fs: [*fs, fs[0]]
    )
    before = evaluate(request, store)
    assert before.status == "approved"
    reversed_request = request.model_copy(
        update={
            "original": request.original.model_copy(
                update={
                    "report": request.original.report.model_copy(
                        update={"facts": tuple(reversed(request.original.report.facts))}
                    )
                }
            )
        }
    )
    after = evaluate(reversed_request, store)
    assert sha256_digest(after.mapping) == sha256_digest(before.mapping)
    assert after.eligible_observation_digests == before.eligible_observation_digests


def test_raw_original_hash_and_original_period_are_required(tmp_path, monkeypatch):
    request, _, _, _ = equity_case(tmp_path, monkeypatch)
    changed_hash = request.original.model_copy(
        update={
            "source": request.original.source.model_copy(
                update={"content_hash": "f" * 64}
            )
        }
    )
    assert policy.select_registered_noncontrolling_equity(
        changed_hash
    ).reason_codes == ("MAPPING_NONCONTROLLING_SCOPE_UNREVIEWED",)
    earlier_period = request.original.model_copy(
        update={"report_period_end": date(2024, 12, 31)}
    )
    assert policy.select_registered_noncontrolling_equity(
        earlier_period
    ).reason_codes == ("MAPPING_PERIOD_AFTER_ORIGINAL",)
