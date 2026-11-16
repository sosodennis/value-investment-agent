"""Candidate restriction preserves mapping rejections without hashing unrelated facts."""

from decimal import Decimal

import pytest

from fundamental_service import automatic_mapping
from fundamental_service.arelle_parser import ParsedXbrlFactV1
from fundamental_service.serialization import sha256_digest
from test_automatic_mapping import case, evaluate
from test_automatic_mapping_disclosures import expense_case


@pytest.mark.parametrize("specialized", [False, True])
def test_unrelated_facts_are_not_generic_sort_candidates(
    tmp_path, monkeypatch, specialized
):
    initial, _, _, _ = case(tmp_path / "initial")
    base = next(
        f for f in initial.original.report.facts if f.concept == "us-gaap:Revenues"
    )
    noise = tuple(
        base.model_copy(
            update={
                "concept": "us-gaap:UnrelatedObservation",
                "context_id": f"noise-{i}",
            }
        )
        for i in range(30)
    )
    if specialized:
        request, store, _, _ = expense_case(tmp_path / "expense", extra_facts=noise)
    else:
        request, store, _, _ = case(tmp_path / "direct", extra=noise)
    digested = []
    original_digest = automatic_mapping.sha256_digest

    def digest(value):
        if isinstance(value, ParsedXbrlFactV1):
            digested.append(value.concept)
        return original_digest(value)

    monkeypatch.setattr(automatic_mapping, "sha256_digest", digest)
    decision = evaluate(request, store)
    assert decision.status == "approved"
    assert "us-gaap:UnrelatedObservation" not in digested
    assert not decision.rejected_observations
    assert decision.eligible_observation_digests


def test_all_selected_concept_rejections_and_alternative_conflicts_remain(tmp_path):
    initial, _, _, _ = case(tmp_path / "initial")
    base = next(
        f for f in initial.original.report.facts if f.concept == "us-gaap:Revenues"
    )
    invalid = base.model_copy(
        update={"context_id": "wrong-unit", "unit": "iso4217:EUR"}
    )
    peers = tuple(
        base.model_copy(
            update={
                "concept": "us-gaap:SalesRevenueNet",
                "context_id": f"peer-{i}",
                "value": str(Decimal(base.value) + i),
            }
        )
        for i in range(3)
    )
    request, store, _, _ = case(tmp_path / "conflict", extra=(invalid, *peers))
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert "MAPPING_OBSERVATION_CONFLICT" in decision.reason_codes
    rejections = {
        (r.observation_digest, r.reason_code) for r in decision.rejected_observations
    }
    assert (sha256_digest(invalid), "MAPPING_UNIT_UNSUPPORTED") in rejections
    assert {
        (sha256_digest(p), "MAPPING_OBSERVATION_CONFLICT") for p in peers[1:]
    } <= rejections
    assert tuple(
        (r.observation_digest, r.reason_code) for r in decision.rejected_observations
    ) == (
        (sha256_digest(invalid), "MAPPING_UNIT_UNSUPPORTED"),
        *(
            (sha256_digest(p), "MAPPING_OBSERVATION_CONFLICT")
            for p in sorted(peers[1:], key=sha256_digest)
        ),
    )
    assert sha256_digest(base) in decision.eligible_observation_digests
    assert evaluate(request, store) == decision
