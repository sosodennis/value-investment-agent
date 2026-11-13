"""Conditional filed text never becomes a reviewed or numeric input."""

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from fundamental_service.arelle_parser import ParsedXbrlFactV1
from fundamental_service.contracts import QualityStatus
from fundamental_service.operating_disclosures import DISCLOSURE_CONCEPTS
from fundamental_service.operating_labels import replay_operating_comparison
from fundamental_service.operating_scenarios import replay_operating_scenarios
from fundamental_service.original_issuer import (
    compose_issuer_operating_source,
    evaluate_original_issuer,
)
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from fundamental_service.valuation_preparation import (
    PreparationError,
    _transition_filing_evidence,
)
from test_operating_labels import comparison_request

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from compile_transition_disclosures import compile_disclosures  # noqa: E402


def seed_with_disclosures(*, changes=None, duplicate=False):
    seed = comparison_request()
    decision = seed.decision
    original = decision.source.originals[0]
    period = decision.periods[-1]
    observations = []
    for index, concept in enumerate(DISCLOSURE_CONCEPTS):
        observation = ParsedXbrlFactV1(
            concept=concept,
            namespace_uri="http://fasb.org/us-gaap/2015-01-31",
            context_id=f"operating-disclosure-{index}",
            entity_scheme="http://www.sec.gov/CIK",
            entity_identifier=original.source.cik,
            value=f"<div>Filed operating disclosure {concept}; unchanged source text.</div>",
            period_start=period.period_start,
            period_end=period.period_end,
            consolidation_scope="consolidated",
            security_scope="unspecified",
        )
        observations.append(
            observation.model_copy(update=changes or {}) if index == 0 else observation
        )
    report = original.report.model_copy(
        update={
            "facts": (
                *original.report.facts,
                *observations,
                *((observations[0],) if duplicate else ()),
            )
        }
    )
    original = evaluate_original_issuer(
        report, source=original.source, decision_at=decision.source.valuation_timestamp
    )
    source = compose_issuer_operating_source(
        (original,), valuation_timestamp=decision.source.valuation_timestamp
    )
    decision = decision.model_copy(update={"source": source})
    return seed.model_copy(
        update={"decision": decision, "decision_input_digest": sha256_digest(decision)}
    )


def test_real_mapper_preserves_verbatim_text_scope_and_provisional_quality():
    seed = seed_with_disclosures()
    compiled, audit = compile_disclosures(seed)
    old = seed.decision
    new = compiled.decision
    assert canonical_bytes(seed.label) == canonical_bytes(compiled.label)
    assert old.periods == new.periods and old.scenarios == new.scenarios
    assert {sha256_digest(f) for f in old.facts} <= {
        sha256_digest(f) for f in new.facts
    }
    assert {sha256_digest(m) for m in old.mappings} <= {
        sha256_digest(m) for m in new.mappings
    }
    assert new.transition_disclosures is not None
    assert len(new.facts) == len(old.facts) + 2
    for fact in new.facts:
        if fact.normalized_field != "filed_operating_evidence":
            continue
        observation = next(
            f for f in new.source.originals[0].report.facts if f.concept == fact.concept
        )
        assert fact.value == observation.value
        assert fact.unit == "text" and fact.currency is None
        assert fact.quality is QualityStatus.PROVISIONAL
        mapping = next(
            m for m in new.mappings if m.decision_id == fact.mapping_decision_id
        )
        assert mapping.observation_scope.observation_digests == (
            sha256_digest(observation),
        )
        assert mapping.reviewer is None and mapping.status == "provisional"
    assert audit["supported_history_threshold"] is None
    assert audit["model_suitability_established"] is False
    assert canonical_bytes(compile_disclosures(seed)[0]) == canonical_bytes(compiled)


def test_explicit_conditional_execution_uses_shared_composer_and_retains_text_lineage():
    seed = seed_with_disclosures()
    before = canonical_bytes(seed)
    compiled, _ = compile_disclosures(seed)
    fcff, transition = replay_operating_scenarios(compiled.decision).results
    prior_fcff, prior_transition = replay_operating_scenarios(seed.decision).results
    assert prior_transition.status == "abstained"
    assert "TRANSITION_EVIDENCE_MISSING" in prior_transition.issue_codes
    assert canonical_bytes(fcff) == canonical_bytes(prior_fcff)
    assert fcff.status == transition.status == "provisional_scenario"
    assert fcff.forecast == transition.forecast
    assert [(n.node_id, n.value) for n in fcff.nodes] == [
        (n.node_id, n.value) for n in transition.nodes
    ]
    assert "TRANSITION_DISCLOSURES_UNREVIEWED" in transition.issue_codes
    assert "MODEL_SUITABILITY_UNESTABLISHED" in transition.issue_codes
    assert set(compiled.decision.transition_disclosures.fact_ids) <= set(
        transition.nodes[0].inputs
    )
    assert not set(compiled.decision.transition_disclosures.fact_ids) & set(
        fcff.nodes[0].inputs
    )
    result = replay_operating_comparison(compiled)
    assert all(
        row.status == "provisional_conditional_comparison" for row in result.comparisons
    )
    assert canonical_bytes(seed) == before


def test_conditional_text_cannot_pass_released_transition_gate_or_enable_it_by_default():
    seed = seed_with_disclosures()
    assert "transition_disclosures" not in seed.decision.model_dump(mode="json")
    compiled, _ = compile_disclosures(seed)
    with pytest.raises(PreparationError, match="verified"):
        _transition_filing_evidence(
            compiled.decision.facts, snapshot=compiled.decision.source
        )
    default = compiled.decision.model_copy(update={"transition_disclosures": None})
    result = replay_operating_scenarios(default).results[1]
    assert (
        result.status == "abstained"
        and "TRANSITION_EVIDENCE_INVALID" in result.issue_codes
    )
    with pytest.raises(ValueError, match="original missing-disclosure"):
        compile_disclosures(compiled)


@pytest.mark.parametrize(
    "changes",
    [
        {"is_numeric": True, "unit": "iso4217:USD", "value": "1"},
        {"value": "<div> </div>"},
        {"value": "1"},
        {"namespace_uri": "https://untrusted.invalid/us-gaap/2015"},
        {"entity_identifier": "9999999999"},
        {"entity_scheme": "https://untrusted.invalid/entity"},
        {"dimensions": (("segment", "subsidiary"),)},
        {"period_start": None},
    ],
)
def test_mapper_and_compiler_refuse_non_operating_or_invalid_observations(changes):
    seed = seed_with_disclosures(changes=changes)
    with pytest.raises((ValueError, SnapshotError)):
        compile_disclosures(seed)


def test_duplicate_current_observations_are_not_resolved_by_order():
    with pytest.raises(ValueError, match="one current consolidated"):
        compile_disclosures(seed_with_disclosures(duplicate=True))


@pytest.mark.parametrize(
    "change",
    ["text", "quality", "source", "future", "issuer", "missing", "review", "period"],
)
def test_changed_or_unavailable_proof_retains_transition_refusal(change):
    compiled, _ = compile_disclosures(seed_with_disclosures())
    decision = compiled.decision
    target = next(
        f for f in decision.facts if f.normalized_field == "filed_operating_evidence"
    )
    updates = {}
    if change == "text":
        updates["value"] = "Invented replacement text"
    if change == "quality":
        updates["quality"] = QualityStatus.VERIFIED
    if change == "source":
        updates["accession_number"] = "0000000001-26-000999"
    if change == "future":
        updates["available_at"] = decision.source.valuation_timestamp + timedelta(
            seconds=1
        )
    if change == "issuer":
        updates["issuer_id"] = "9999999999"
    if change == "period":
        updates["period_start"] = target.period_start - timedelta(days=1)
    facts = tuple(
        f.model_copy(update=updates) if f.fact_id == target.fact_id else f
        for f in decision.facts
        if change != "missing" or f.fact_id != target.fact_id
    )
    mappings = decision.mappings
    if change == "review":
        mappings = tuple(
            m.model_copy(update={"reviewer": "invented-reviewer"})
            if m.decision_id == target.mapping_decision_id
            else m
            for m in mappings
        )
    decision = decision.model_copy(
        update={
            "facts": facts,
            "mappings": mappings,
            "mapping_manifest_digest": sha256_digest(mappings),
        }
    )
    result = replay_operating_scenarios(decision).results[1]
    assert result.status == "abstained"
    assert result.forecast is None and not result.nodes


def test_policy_substitution_and_duplicate_ids_fail_contract_validation():
    compiled, _ = compile_disclosures(seed_with_disclosures())
    proof = compiled.decision.transition_disclosures
    for updates in (
        {"policy_digest": "0" * 64},
        {"fact_ids": (proof.fact_ids[0],) * 2},
        {"policy_version": "unknown"},
    ):
        with pytest.raises(ValidationError):
            type(proof).model_validate({**proof.model_dump(), **updates})


def test_unscoped_text_cannot_map_to_any_financial_role():
    compiled, _ = compile_disclosures(seed_with_disclosures())
    original = compiled.decision.source.originals[0]
    mapping = next(
        m
        for m in compiled.decision.mappings
        if m.normalized_field == "filed_operating_evidence"
    )
    for changed in (
        mapping.model_copy(update={"observation_scope": None}),
        mapping.model_copy(update={"normalized_field": "revenue"}),
    ):
        assert not parsed_facts_to_candidates(
            original.report,
            source=original.source,
            issuer_id=original.source.cik,
            normalized_field=changed.normalized_field,
            mapping=changed,
        )
