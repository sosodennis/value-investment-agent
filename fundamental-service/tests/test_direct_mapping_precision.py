"""Direct admission shares the canonical same-filing precision decision."""

from decimal import Decimal

import pytest

from fundamental_service.automatic_mapping import (
    AutomaticMappingDecisionV1,
    verify_automatic_mapping_replay,
)
from fundamental_service.data_releases import AutomaticMappingApprovalV1
from fundamental_service.facts import select_fact
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import sha256_digest
from test_automatic_mapping import approve, case, evaluate
from test_automatic_mapping_security import security_case, security_source
from test_issuer_operating_release import inventory


def precision_case(
    tmp_path, *, precise_decimals="-6", rounded_decimals="-8", extra=(), security=False
):
    changes = {"value": "10727000000", "decimals": precise_decimals}
    template, _, _, _ = case(tmp_path / "template", observation_changes=changes)
    precise = next(
        f for f in template.original.report.facts if f.concept == "us-gaap:Revenues"
    )
    rounded = precise.model_copy(
        update={
            "value": "10700000000",
            "decimals": rounded_decimals,
            "context_id": "rounded-original-disclosure",
        }
    )
    identity = None
    if security:
        bound, _, _ = security_case(tmp_path / "security")
        identity = bound.security_identity
        extra += tuple(
            f
            for f in bound.original.report.facts
            if f.concept
            in {
                "dei:EntityIncorporationStateCountryCode",
                "dei:TradingSymbol",
                "dei:Security12bTitle",
            }
        )
    request, store, roots, bundle = case(
        tmp_path / "actual", observation_changes=changes, extra=(rounded, *extra)
    )
    if identity is not None:
        request = request.model_copy(update={"security_identity": identity})
    return (request, store, roots, bundle), precise, rounded


@pytest.mark.parametrize("security", [False, True])
def test_precise_observation_rebuilds_and_signed_replay_reuses_without_writes(
    tmp_path, security
):
    (request, store, roots, _), precise, rounded = precision_case(
        tmp_path, security=security
    )
    receipt = approve(request, store, roots)
    decision = AutomaticMappingDecisionV1.model_validate_json(
        store.read(receipt.decision_publication.artifact.artifact_id)
    )
    assert decision.status == "approved" and not decision.reason_codes
    assert sha256_digest(precise) in decision.eligible_observation_digests
    assert sha256_digest(rounded) not in decision.eligible_observation_digests
    assert [
        (r.observation_digest, r.reason_code) for r in decision.rejected_observations
    ] == [(sha256_digest(rounded), "MAPPING_OBSERVATION_LOWER_PRECISION")]
    assert rounded in request.original.report.facts
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=security_source(request) if security else request.original.source,
        issuer_id=request.original.source.cik,
        normalized_field="revenue",
        security_id=request.security_identity.security_id if security else None,
        mapping=decision.mapping,
    )
    selection = select_fact(
        tuple(
            c
            for c in candidates
            if c.period_start == precise.period_start
            and c.period_end == precise.period_end
        ),
        request.original.decision_at,
    )
    assert selection.fact.value == Decimal("10727000000")
    assert selection.fact.decimals == -6
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(receipt.approval_publication.artifact.artifact_id)
    )
    assert (
        verify_automatic_mapping_replay(approval, decision.mapping, artifacts=store)
        == request
    )
    before = inventory(store.root)
    repeat = approve(request, store, roots)
    assert repeat.output_digest == receipt.output_digest
    assert inventory(store.root) == before
    assert all(
        not p.wrote
        for p in (
            repeat.input_publication,
            repeat.decision_publication,
            repeat.approval_publication,
        )
    )


def test_equal_precision_disagreement_still_refuses(tmp_path):
    (request, store, roots, _), _, _ = precision_case(tmp_path, rounded_decimals="-6")
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert "MAPPING_OBSERVATION_CONFLICT" in decision.reason_codes
    assert {item.reason_code for item in decision.rejected_observations} == {
        "MAPPING_OBSERVATION_CONFLICT"
    }
    assert approve(request, store, roots).approval_publication is None


def test_incompatible_lower_precision_original_cannot_be_signed(tmp_path):
    (_, _, _, _), _, rounded = precision_case(tmp_path / "seed")
    (request, store, roots, _), _, _ = precision_case(
        tmp_path / "actual",
        extra=(rounded.model_copy(update={"value": "10000000000", "decimals": "-9"}),),
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert "MAPPING_OBSERVATION_CONFLICT" in decision.reason_codes
    assert approve(request, store, roots).approval_publication is None


@pytest.mark.parametrize(
    "precise_decimals,rounded_decimals", [("INF", "-8"), ("-6", "INF")]
)
def test_mixed_exact_and_rounded_precision_refuses_until_selector_can_distinguish_it(
    tmp_path, precise_decimals, rounded_decimals
):
    (request, store, roots, _), _, _ = precision_case(
        tmp_path,
        precise_decimals=precise_decimals,
        rounded_decimals=rounded_decimals,
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert "MAPPING_PRECISION_MIXED_EXACT_UNSUPPORTED" in decision.reason_codes
    assert approve(request, store, roots).approval_publication is None


def test_lower_precision_alternative_concept_cannot_hide_scope_conflict(tmp_path):
    (_, _, _, _), _, rounded = precision_case(tmp_path / "seed")
    (request, store, _, _), _, _ = precision_case(
        tmp_path / "actual",
        extra=(rounded.model_copy(update={"concept": "us-gaap:SalesRevenueNet"}),),
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain"
    assert "MAPPING_OBSERVATION_CONFLICT" in decision.reason_codes


def test_original_fact_order_does_not_change_precision_or_mapping(tmp_path):
    (request, store, _, _), _, _ = precision_case(tmp_path)
    decision = evaluate(request, store)
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
    again = evaluate(reversed_request, store)
    assert again.status == decision.status == "approved"
    assert again.mapping == decision.mapping
    assert again.eligible_observation_digests == decision.eligible_observation_digests
    assert again.rejected_observations == decision.rejected_observations
