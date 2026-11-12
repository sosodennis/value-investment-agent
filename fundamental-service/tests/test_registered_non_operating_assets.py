"""Source-bound investment scope, reconstruction and retained refusals."""

from datetime import date
from decimal import Decimal

import pytest

from fundamental_service import registered_non_operating_assets as policy
from fundamental_service.arelle_parser import fact_semantic_digest
from fundamental_service.automatic_mapping import (
    AutomaticMappingApprovalV1,
    AutomaticMappingDecisionV1,
    automatic_mapping_proposal,
    verify_automatic_mapping_replay,
)
from fundamental_service.automatic_mapping_batch import AutomaticMappingBatchRequestV1
from fundamental_service.automatic_mapping_runner import approve_mapping_batch
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import sha256_digest
from fundamental_service.valuation_requirements import valuation_requirements_profile
from test_automatic_mapping import approve, case, evaluate, MACHINE_KEY
from test_automatic_mapping_batch import read_decision
from test_issuer_operating_release import inventory


def asset_case(tmp_path, monkeypatch, *, change=None):
    template, _, _, _ = case(tmp_path / "template")
    base = next(f for f in template.original.report.facts if f.is_numeric)
    facts = [
        base.model_copy(
            update={
                "concept": concept,
                "context_id": f"asset-{year}",
                "value": value,
                "period_start": None,
                "period_end": None,
                "instant": date(year, 12, 31),
                "decimals": "0",
            }
        )
        for year, amounts in (
            (2024, ("15513095", "36125047", "425372")),
            (2025, ("11917779", "30788301", "460627")),
        )
        for concept, value in zip(policy.COMPONENT_CONCEPTS, amounts)
    ]
    cash = facts[-1].model_copy(
        update={
            "concept": "us-gaap:CashAndCashEquivalentsAtCarryingValue",
            "value": "10283550",
        }
    )
    aggregate = facts[-1].model_copy(
        update={
            "concept": "us-gaap:AvailableForSaleSecuritiesDebtSecurities",
            "value": "52548876",
        }
    )
    facts = [cash, aggregate, *facts]
    if change is not None:
        facts = change(facts)
    request, store, roots, bundle = case(
        tmp_path / "actual",
        extra=tuple(facts),
        proposal_changes={
            "source_concept": policy.NON_OPERATING_ASSETS,
            "normalized_field": "non_operating_assets",
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


def test_investment_assets_include_interest_and_exclude_cash_with_signed_replay(
    tmp_path, monkeypatch
):
    request, store, roots, _ = asset_case(tmp_path, monkeypatch)
    assert (
        automatic_mapping_proposal(
            "non_operating_assets",
            mapping_version=request.proposal.mapping_version,
            original=request.original,
        ).source_concept
        == policy.NON_OPERATING_ASSETS
    )
    receipt = approve(request, store, roots)
    decision = AutomaticMappingDecisionV1.model_validate_json(
        store.read(receipt.decision_publication.artifact.artifact_id)
    )
    assert decision.status == "approved"
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=request.original.source,
        issuer_id=request.original.source.cik,
        normalized_field="non_operating_assets",
        mapping=decision.mapping,
    )
    assert {f.instant.year: f.value for f in candidates} == {
        2024: Decimal("52063514"),
        2025: Decimal("43166707"),
    }
    assert all(f.decimals is None for f in candidates)
    assert all(
        f.decimals == "0"
        for candidate in candidates
        for f in candidate.accounting_evidence.source_facts
    )
    assert all(
        {f.concept for f in candidate.accounting_evidence.source_facts}
        == set(policy.COMPONENT_CONCEPTS)
        for candidate in candidates
    )
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(receipt.approval_publication.artifact.artifact_id)
    )
    before = inventory(store.root)
    assert (
        verify_automatic_mapping_replay(
            approval, decision.mapping, artifacts=ArtifactStore(store.root)
        )
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
    "change,reason",
    (
        (lambda fs: fs[:-1], "MAPPING_NON_OPERATING_ASSET_COMPONENT_MISSING"),
        (
            lambda fs: [*fs, fs[-1].model_copy(update={"value": "460628"})],
            "MAPPING_OBSERVATION_CONFLICT",
        ),
        (
            lambda fs: [*fs[:-1], fs[-1].model_copy(update={"unit": "xbrli:shares"})],
            "MAPPING_NON_OPERATING_ASSET_COMPONENT_INVALID",
        ),
        (
            lambda fs: [*fs[:-1], fs[-1].model_copy(update={"decimals": None})],
            "MAPPING_NON_OPERATING_ASSET_COMPONENT_INVALID",
        ),
        (
            lambda fs: [*fs[:-1], fs[-1].model_copy(update={"value": "-1"})],
            "MAPPING_NON_OPERATING_ASSET_COMPONENT_INVALID",
        ),
        (
            lambda fs: [*fs[:-1], fs[-1].model_copy(update={"value": "NaN"})],
            "MAPPING_NON_OPERATING_ASSET_COMPONENT_INVALID",
        ),
        (
            lambda fs: [
                *fs[:-1],
                fs[-1].model_copy(update={"entity_identifier": "999"}),
            ],
            "MAPPING_NON_OPERATING_ASSET_COMPONENT_INVALID",
        ),
        (
            lambda fs: [
                *fs[:-1],
                fs[-1].model_copy(update={"instant": date(2026, 12, 31)}),
            ],
            "MAPPING_NON_OPERATING_ASSET_COMPONENT_MISSING",
        ),
    ),
)
def test_registered_investment_scope_requires_every_aligned_component(
    tmp_path, monkeypatch, change, reason
):
    request, store, _, _ = asset_case(tmp_path, monkeypatch, change=change)
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert reason in decision.reason_codes


@pytest.mark.parametrize("change", ("source", "accession", "issuer", "report"))
def test_original_classification_does_not_transfer(tmp_path, monkeypatch, change):
    request, _, _, _ = asset_case(tmp_path, monkeypatch)
    original = request.original
    if change == "report":
        original = original.model_copy(
            update={
                "report": original.report.model_copy(
                    update={"facts": original.report.facts[:-1]}
                )
            }
        )
    else:
        field, value = {
            "source": ("content_hash", "f" * 64),
            "accession": ("accession_number", "0000724910-25-000001"),
            "issuer": ("cik", "0000000999"),
        }[change]
        original = original.model_copy(
            update={"source": original.source.model_copy(update={field: value})}
        )
    selection = policy.select_registered_non_operating_assets(original)
    assert selection.rules is None and selection.reason_codes


def test_reordered_equivalent_observations_preserve_classification(
    tmp_path, monkeypatch
):
    request, _, _, _ = asset_case(
        tmp_path, monkeypatch, change=lambda fs: [*fs, fs[-1]]
    )
    original = request.original
    first = policy.select_registered_non_operating_assets(original)
    second = policy.select_registered_non_operating_assets(
        original.model_copy(
            update={
                "report": original.report.model_copy(
                    update={"facts": tuple(reversed(original.report.facts))}
                )
            }
        )
    )
    assert first.rules is not None
    assert sha256_digest(first.rules) == sha256_digest(second.rules)
    assert first.selected == second.selected


def test_batch_retains_other_missing_roles_and_rejects_cash_total_proposal(
    tmp_path, monkeypatch
):
    request, store, roots, _ = asset_case(tmp_path, monkeypatch)
    wrong = request.model_copy(
        update={
            "proposal": request.proposal.model_copy(
                update={
                    "source_concept": "us-gaap:AvailableForSaleSecuritiesDebtSecurities"
                }
            )
        }
    )
    assert evaluate(wrong, store).status == "abstain"
    batch = AutomaticMappingBatchRequestV1(
        **request.model_dump(exclude={"protocol", "proposal"}),
        mapping_version=request.proposal.mapping_version,
        model_version="fcff_dcf-v2",
        requirements=valuation_requirements_profile("fcff_dcf"),
    )
    receipt = approve_mapping_batch(
        batch, artifacts=store, trust_roots=roots, private_key=MACHINE_KEY
    )
    roles = {r.normalized_field: r for r in read_decision(receipt, store).roles}
    assert roles["non_operating_assets"].status == "approved"
    assert roles["convertible_instruments"].status == "abstain"
    assert roles["convertible_instruments"].approval is None
    assert batch.requirements.supported_history_threshold is None
