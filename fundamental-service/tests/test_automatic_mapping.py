"""Synthetic SEC-shaped evidence verifies policy behavior, never real financials."""

import base64
import json
from datetime import date
from decimal import Decimal

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fundamental_service.arelle_parser import fact_semantic_digest
from fundamental_service.automatic_mapping import (
    AutomaticMappingDecisionV1,
    AutomaticMappingRequestV1,
    automatic_mapping_policy_digest,
    evaluate_automatic_mapping,
    verify_automatic_mapping_replay,
)
from fundamental_service.automatic_mapping_runner import approve_mapping, main
from fundamental_service.contracts import SecIntegrityEvidenceV1
from fundamental_service.data_releases import (
    ArtifactRefV1,
    AutomaticMappingApprovalV1,
    AutomaticMappingEvaluatorV1,
    DataReleaseError,
    FactRefV1,
    MappingRefV1,
    SnapshotRefV1,
    sign_automatic_mapping_approval,
    sign_data_release_verification,
    verify_data_release_candidate,
    verify_mapping_review_evidence,
)
from fundamental_service.facts import CanonicalMappingV1, canonical_fact_digest
from fundamental_service.issuer_operating_release import IssuerOperatingReleaseService
from fundamental_service.issuer_release_evidence import original_rebuilt_facts
from fundamental_service.original_issuer import (
    compose_issuer_operating_source,
    evaluate_original_issuer,
)
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from test_issuer_operating_release import fixture, inventory, resign, VERIFIER

MACHINE_KEY = Ed25519PrivateKey.from_private_bytes(
    b"synthetic-machine-key".ljust(32, b"0")
)
REVISION = "a" * 40
EVALUATOR = "synthetic-automatic-mapper"


def case(tmp_path, *, observation_changes=None, proposal_changes=None, extra=()):
    bundle, _, evidence, roots, _ = fixture(tmp_path)
    original = bundle.sources[0].originals[0]
    facts = tuple(
        fact.model_copy(update={"concept": "us-gaap:Revenues"})
        if fact.concept == "us-gaap:revenue"
        else fact
        for fact in original.report.facts
    )
    if observation_changes:
        facts = tuple(
            fact.model_copy(update=observation_changes)
            if fact.concept == "us-gaap:Revenues"
            else fact
            for fact in facts
        )
    report = original.report.model_copy(update={"facts": (*facts, *extra)})
    claim = evaluate_original_issuer(
        report, source=original.source, decision_at=original.decision_at
    )
    integrity = SecIntegrityEvidenceV1.model_validate_json(
        evidence.read("synthetic-integrity")
    ).model_copy(
        update={
            "normalized_fact_count": len(report.facts),
            "archive_fact_count": len(report.facts),
            "normalized_fact_digest": fact_semantic_digest(report),
            "archive_fact_digest": fact_semantic_digest(report),
        }
    )
    evidence.values["synthetic-integrity"] = canonical_bytes(integrity)
    store = ArtifactStore(tmp_path / "automatic-evidence")
    refs = []
    for name, raw in sorted(evidence.values.items()):
        publication = store.put_bytes_with_receipt(name, raw)
        refs.append(
            ArtifactRefV1(
                artifact_id=name,
                content_hash=publication.artifact.content_hash,
                media_type=publication.artifact.media_type,
                role="synthetic-source-evidence",
            )
        )
    proposal = CanonicalMappingV1(
        contract_version="fundamental.v1",
        decision_id="synthetic-proposal",
        source_concept="us-gaap:Revenues",
        normalized_field="revenue",
        mapping_version=bundle.manifest.mapping_version,
        confidence="unresolved",
        status="provisional",
    )
    request = AutomaticMappingRequestV1(
        source_revision=REVISION,
        evaluator_id=EVALUATOR,
        original=claim,
        integrity=integrity,
        proposal=proposal.model_copy(update=proposal_changes or {}),
        evidence_refs=tuple(refs),
    )
    roots = roots.model_copy(
        update={
            "automatic_mapping_evaluators": {
                EVALUATOR: AutomaticMappingEvaluatorV1(
                    public_key_ed25519_base64=base64.b64encode(
                        MACHINE_KEY.public_key().public_bytes_raw()
                    ).decode(),
                    policy_digest=automatic_mapping_policy_digest(),
                )
            }
        }
    )
    return request, store, roots, bundle


def evaluate(request, store):
    return evaluate_automatic_mapping(
        request,
        contents={
            r.content_hash: store.read(r.artifact_id) for r in request.evidence_refs
        },
    )


def approve(request, store, roots):
    return approve_mapping(
        request, artifacts=store, trust_roots=roots, private_key=MACHINE_KEY
    )


@pytest.mark.parametrize("concept", ("us-gaap:Revenues", "us-gaap:SalesRevenueNet"))
def test_machine_approval_repeats_without_new_artifacts_or_human_review(
    tmp_path, concept
):
    request, store, roots, _ = case(
        tmp_path,
        observation_changes={"concept": concept},
        proposal_changes={"source_concept": concept},
    )
    first = approve(request, store, roots)
    before = inventory(store.root)
    second = approve(request, ArtifactStore(store.root), roots)
    assert inventory(store.root) == before
    assert first.input_digest == second.input_digest == sha256_digest(request)
    assert first.output_digest == second.output_digest
    for receipt in (
        second.input_publication,
        second.decision_publication,
        second.approval_publication,
    ):
        assert receipt.wrote is False
    decision = AutomaticMappingDecisionV1.model_validate_json(
        store.read(first.decision_publication.artifact.artifact_id)
    )
    mapping = decision.mapping
    assert decision.status == "approved" and not decision.reason_codes
    assert decision.policy_version == "consolidated-direct-us-gaap-v2"
    assert mapping.source_concept == concept
    assert mapping.reviewer == f"automatic:{EVALUATOR}" and mapping.reviewed_at is None
    assert mapping.observation_scope.issuer_id == request.original.source.cik
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(first.approval_publication.artifact.artifact_id)
    )
    verify_mapping_review_evidence(approval, roots)
    assert (
        verify_automatic_mapping_replay(approval, mapping, artifacts=store) == request
    )


@pytest.mark.parametrize(
    "changes,reason",
    (
        (
            {"namespace_uri": "https://example.org/us-gaap"},
            "MAPPING_NAMESPACE_UNSUPPORTED",
        ),
        ({"entity_identifier": "999"}, "MAPPING_ISSUER_MISMATCH"),
        ({"entity_scheme": "https://example.org"}, "MAPPING_ISSUER_MISMATCH"),
        ({"dimensions": (("axis", "member"),)}, "MAPPING_SCOPE_UNSUPPORTED"),
        ({"consolidation_scope": "segment"}, "MAPPING_SCOPE_UNSUPPORTED"),
        ({"security_scope": "other-class"}, "MAPPING_SCOPE_UNSUPPORTED"),
        ({"unit": "iso4217:EUR"}, "MAPPING_UNIT_UNSUPPORTED"),
        ({"is_numeric": False}, "MAPPING_UNIT_UNSUPPORTED"),
        ({"value": "NaN"}, "MAPPING_VALUE_INVALID"),
        ({"value": "nil"}, "MAPPING_VALUE_INVALID"),
        ({"decimals": None}, "MAPPING_PRECISION_UNAVAILABLE"),
        ({"instant": date(2025, 12, 31)}, "MAPPING_PERIOD_UNSUPPORTED"),
        ({"period_start": date(2025, 11, 1)}, "MAPPING_PERIOD_UNSUPPORTED"),
        (
            {"period_start": date(2026, 1, 1), "period_end": date(2026, 12, 31)},
            "MAPPING_PERIOD_AFTER_ORIGINAL",
        ),
    ),
)
@pytest.mark.parametrize("concept", ("us-gaap:Revenues", "us-gaap:SalesRevenueNet"))
def test_ineligible_observations_abstain_and_remain_auditable(
    tmp_path, changes, reason, concept
):
    request, store, roots, _ = case(
        tmp_path,
        observation_changes={**changes, "concept": concept},
        proposal_changes={"source_concept": concept},
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert "MAPPING_NO_ELIGIBLE_OBSERVATIONS" in decision.reason_codes
    assert reason in {
        rejection.reason_code for rejection in decision.rejected_observations
    }
    receipt = approve(request, store, roots)
    assert receipt.approval_publication is None
    retained = json.loads(store.read(receipt.decision_publication.artifact.artifact_id))
    assert retained["status"] == "abstain"
    assert not approve(request, store, roots).decision_publication.wrote


def test_segment_net_income_is_excluded_while_consolidated_is_approved(tmp_path):
    request, store, _, _ = case(tmp_path)
    income = next(
        f for f in request.original.report.facts if f.concept == "us-gaap:Revenues"
    )
    segment = income.model_copy(
        update={
            "context_id": "retained-earnings",
            "concept": "us-gaap:NetIncomeLoss",
            "dimensions": (
                (
                    "us-gaap:StatementEquityComponentsAxis",
                    "us-gaap:RetainedEarningsMember",
                ),
            ),
        }
    )
    request, store, _, _ = case(
        tmp_path / "scoped",
        observation_changes={"concept": "us-gaap:NetIncomeLoss"},
        proposal_changes={
            "source_concept": "us-gaap:NetIncomeLoss",
            "normalized_field": "net_income",
        },
        extra=(segment,),
    )
    decision = evaluate(request, store)
    assert decision.status == "approved"
    assert (
        sha256_digest(segment)
        not in decision.mapping.observation_scope.observation_digests
    )
    assert decision.rejected_observations[0].reason_code == "MAPPING_SCOPE_UNSUPPORTED"
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=request.original.source,
        issuer_id=request.original.source.cik,
        normalized_field="net_income",
        mapping=decision.mapping,
    )
    assert candidates and all(not item.dimensions for item in candidates)


@pytest.mark.parametrize(
    "proposal",
    (
        {"source_concept": "us-gaap:SalesRevenueGoodsNet"},
        {"source_concept": "us-gaap:SalesRevenueServicesNet"},
        {"source_concept": "example:SalesRevenueNet"},
        {
            "source_concept": "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax"
        },
        {
            "source_concept": "us-gaap:DepreciationDepletionAndAmortization",
            "normalized_field": "depreciation_and_amortization",
        },
        {
            "source_concept": "example:OperatingTaxPartition",
            "normalized_field": "operating_current_payables",
        },
        {
            "source_concept": "us-gaap:NonoptionStockUnitsOutstandingNumber",
            "normalized_field": "common_shares_outstanding",
        },
    ),
)
def test_unsupported_semantics_have_no_automatic_approval(tmp_path, proposal):
    request, store, _, _ = case(tmp_path, proposal_changes=proposal)
    assert "MAPPING_AUTOMATIC_RULE_UNSUPPORTED" in evaluate(request, store).reason_codes


def test_conflicting_annual_amounts_abstain_even_with_valid_source(tmp_path):
    request, _, _, _ = case(tmp_path)
    observed = next(
        f for f in request.original.report.facts if f.concept == "us-gaap:Revenues"
    )
    conflict = observed.model_copy(
        update={"value": str(Decimal(observed.value) + 1), "context_id": "conflict"}
    )
    request, store, _, _ = case(tmp_path / "conflict", extra=(conflict,))
    assert "MAPPING_OBSERVATION_CONFLICT" in evaluate(request, store).reason_codes


@pytest.mark.parametrize("difference", ("0", "1"))
@pytest.mark.parametrize("concept", ("us-gaap:Revenues", "us-gaap:SalesRevenueNet"))
def test_total_revenue_concepts_require_agreement_for_the_same_period(
    tmp_path, difference, concept
):
    request, _, _, _ = case(tmp_path)
    observed = next(
        f for f in request.original.report.facts if f.concept == "us-gaap:Revenues"
    )
    peer_concept = (
        "us-gaap:SalesRevenueNet"
        if concept == "us-gaap:Revenues"
        else "us-gaap:Revenues"
    )
    peer = observed.model_copy(
        update={
            "concept": peer_concept,
            "value": str(Decimal(observed.value) + Decimal(difference)),
        }
    )
    request, store, roots, _ = case(
        tmp_path / "totals",
        observation_changes={"concept": concept},
        proposal_changes={"source_concept": concept},
        extra=(peer,),
    )
    decision = evaluate(request, store)
    if difference == "0":
        assert decision.status == "approved"
        assert (
            sha256_digest(peer)
            not in decision.mapping.observation_scope.observation_digests
        )
    else:
        assert decision.status == "abstain" and decision.mapping is None
        assert "MAPPING_OBSERVATION_CONFLICT" in decision.reason_codes
        assert any(
            r.observation_digest == sha256_digest(peer)
            and r.reason_code == "MAPPING_OBSERVATION_CONFLICT"
            for r in decision.rejected_observations
        )
        first = approve(request, store, roots)
        before = inventory(store.root)
        second = approve(request, store, roots)
        assert (
            first.approval_publication is None and second.approval_publication is None
        )
        assert not second.decision_publication.wrote and inventory(store.root) == before


@pytest.mark.parametrize(
    "changes",
    (
        {"entity_identifier": "999"},
        {"unit": "iso4217:EUR"},
        {"dimensions": (("axis", "member"),)},
        {"period_start": date(2025, 11, 1)},
    ),
)
def test_ineligible_peer_total_does_not_override_requested_observations(
    tmp_path, changes
):
    request, _, _, _ = case(tmp_path)
    observed = next(
        f for f in request.original.report.facts if f.concept == "us-gaap:Revenues"
    )
    peer = observed.model_copy(
        update={
            "concept": "us-gaap:SalesRevenueNet",
            "value": str(Decimal(observed.value) + 1),
            **changes,
        }
    )
    request, store, _, _ = case(tmp_path / "peer", extra=(peer,))
    assert evaluate(request, store).status == "approved"


def test_valid_peer_total_does_not_substitute_for_missing_requested_concept(tmp_path):
    request, store, _, _ = case(
        tmp_path, proposal_changes={"source_concept": "us-gaap:SalesRevenueNet"}
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert "MAPPING_NO_ELIGIBLE_OBSERVATIONS" in decision.reason_codes


def test_missing_bytes_or_integrity_never_produce_approval(tmp_path):
    request, store, _, _ = case(tmp_path)
    decision = evaluate_automatic_mapping(request, contents={})
    assert decision.status == "abstain"
    assert "MAPPING_SOURCE_ARTIFACT_UNAVAILABLE" in decision.reason_codes
    changed = request.model_copy(
        update={
            "integrity": request.integrity.model_copy(
                update={"quality_decision": "fail"}
            )
        }
    )
    assert (
        "DATA_RELEASE_ORIGINAL_INTEGRITY_MISMATCH"
        in evaluate(changed, store).reason_codes
    )


def test_missing_retained_source_persists_an_unchanged_abstention(tmp_path):
    request, _, roots, _ = case(tmp_path)
    empty = ArtifactStore(tmp_path / "missing-source")
    first = approve(request, empty, roots)
    assert first.approval_publication is None
    result = AutomaticMappingDecisionV1.model_validate_json(
        empty.read(first.decision_publication.artifact.artifact_id)
    )
    assert result.status == "abstain"
    assert "MAPPING_SOURCE_ARTIFACT_UNAVAILABLE" in result.reason_codes
    before = inventory(empty.root)
    second = approve(request, empty, roots)
    assert not second.decision_publication.wrote
    assert inventory(empty.root) == before


def test_mapping_cannot_escape_original_or_observation_scope(tmp_path):
    request, store, _, _ = case(tmp_path)
    mapping = evaluate(request, store).mapping
    kwargs = {
        "issuer_id": request.original.source.cik,
        "normalized_field": "revenue",
        "mapping": mapping,
    }
    other_source = request.original.source.model_copy(
        update={"accession_number": "0000000001-25-999999"}
    )
    assert (
        parsed_facts_to_candidates(
            request.original.report, source=other_source, **kwargs
        )
        == ()
    )
    changed_report = request.original.report.model_copy(
        update={"taxonomy_version": "changed-taxonomy"}
    )
    with pytest.raises(SnapshotError, match="exact approved parser report"):
        parsed_facts_to_candidates(
            changed_report, source=request.original.source, **kwargs
        )


def test_signed_approval_must_reproduce_policy_decision(tmp_path):
    request, store, roots, _ = case(tmp_path)
    receipt = approve(request, store, roots)
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(receipt.approval_publication.artifact.artifact_id)
    )
    mapping = evaluate(request, store).mapping
    forged = sign_automatic_mapping_approval(
        {**approval.model_dump(exclude={"signature"}), "output_digest": "0" * 64},
        MACHINE_KEY,
    )
    verify_mapping_review_evidence(forged, roots)
    with pytest.raises(DataReleaseError) as error:
        verify_automatic_mapping_replay(forged, mapping, artifacts=store)
    assert error.value.code == "DATA_RELEASE_MAPPING_REPLAY_MISMATCH"
    with pytest.raises(DataReleaseError) as error:
        verify_mapping_review_evidence(
            approval.model_copy(update={"policy_digest": "0" * 64}), roots
        )
    assert error.value.code == "DATA_RELEASE_MAPPING_POLICY_UNTRUSTED"


def test_automatic_mapping_passes_existing_release_and_read_only_canary(tmp_path):
    request, store, roots, bundle = case(tmp_path)
    receipt = approve(request, store, roots)
    decision = evaluate(request, store)
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(receipt.approval_publication.artifact.artifact_id)
    )
    view = compose_issuer_operating_source(
        (request.original,), valuation_timestamp=request.original.decision_at
    )
    mappings = tuple(
        sorted(
            (
                decision.mapping,
                *(m for m in bundle.mappings if m.normalized_field != "revenue"),
            ),
            key=lambda m: m.decision_id,
        )
    )
    facts = tuple(
        sorted(
            original_rebuilt_facts(view, {m.decision_id: m for m in mappings}),
            key=lambda f: f.fact_id,
        )
    )
    refs = tuple(
        FactRefV1(fact_id=f.fact_id, fact_digest=canonical_fact_digest(f))
        for f in facts
    )
    snapshot_ref = SnapshotRefV1(
        snapshot_id=view.snapshot_id,
        manifest_digest=view.manifest_digest,
        facts=refs,
        fact_set_digest=sha256_digest(refs),
    )
    mapping_refs = tuple(
        MappingRefV1(mapping_id=m.decision_id, mapping_digest=sha256_digest(m))
        for m in mappings
    )
    artifact_refs = tuple(
        r.model_copy(update={"content_hash": store.get(r.artifact_id).content_hash})
        for r in bundle.manifest.artifact_refs
    )
    changed = resign(
        bundle.model_copy(
            update={"sources": (view,), "facts": facts, "mappings": mappings}
        ),
        snapshot_refs=(snapshot_ref,),
        mapping_refs=mapping_refs,
        artifact_refs=artifact_refs,
    )
    reviews = tuple(
        r
        for r in bundle.verification.mapping_reviews
        if r.mapping_id in {m.decision_id for m in mappings}
    ) + (approval,)
    verification = sign_data_release_verification(
        {
            **changed.verification.model_dump(
                exclude={"signature", "verification_digest"}
            ),
            "mapping_reviews": reviews,
        },
        VERIFIER,
    )
    changed = changed.model_copy(update={"verification": verification})
    verify_data_release_candidate(changed.manifest, verification, roots)
    releases = ArtifactStore(tmp_path / "machine-release")
    service = IssuerOperatingReleaseService(
        releases=releases, evidence=store, trust_roots=roots
    )
    assert service.publish(changed).wrote
    before = inventory(releases.root), inventory(store.root)
    assert not service.publish(changed).wrote
    assert before == (inventory(releases.root), inventory(store.root))
    forged_approval = sign_automatic_mapping_approval(
        {**approval.model_dump(exclude={"signature"}), "output_digest": "f" * 64},
        MACHINE_KEY,
    )
    forged_verification = sign_data_release_verification(
        {
            **verification.model_dump(exclude={"signature", "verification_digest"}),
            "mapping_reviews": (*reviews[:-1], forged_approval),
        },
        VERIFIER,
    )
    with pytest.raises(DataReleaseError) as error:
        service.publish(
            changed.model_copy(update={"verification": forged_verification})
        )
    assert error.value.code == "DATA_RELEASE_MAPPING_REPLAY_MISMATCH"
    assert before == (inventory(releases.root), inventory(store.root))
    altered = decision.mapping.model_copy(update={"confidence": "medium"})
    with pytest.raises(DataReleaseError):
        verify_automatic_mapping_replay(approval, altered, artifacts=store)


def test_policy_digest_is_available_without_storage_or_a_human(tmp_path, capsys):
    assert main(["--print-policy-digest"]) == 0
    assert capsys.readouterr().out.strip() == automatic_mapping_policy_digest()


@pytest.mark.parametrize(
    "role,concept,instant",
    (
        (
            "basic_weighted_average_shares",
            "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",
            False,
        ),
        (
            "diluted_weighted_average_shares",
            "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
            False,
        ),
        ("common_shares_outstanding", "us-gaap:CommonStockSharesOutstanding", True),
    ),
)
def test_parser_xbrli_share_units_are_approved_without_relabelling_periods(
    tmp_path, role, concept, instant
):
    request, _, _, _ = case(tmp_path)
    observed = next(
        f for f in request.original.report.facts if f.concept == "us-gaap:Revenues"
    )
    changes = {
        "concept": concept,
        "unit": "xbrli:shares",
        "context_id": "canonical-share-unit",
    }
    if instant:
        changes.update(
            {"period_start": None, "period_end": None, "instant": date(2025, 12, 31)}
        )
    shares = observed.model_copy(update=changes)
    request, store, _, _ = case(
        tmp_path / "share-case",
        proposal_changes={"source_concept": concept, "normalized_field": role},
        extra=(shares,),
    )
    result = evaluate(request, store)
    assert result.status == "approved"
    assert result.mapping.observation_scope.observation_digests == (
        sha256_digest(shares),
    )
    wrong_unit = shares.model_copy(update={"unit": "shares"})
    request, store, _, _ = case(
        tmp_path / "noncanonical-share-unit",
        proposal_changes={"source_concept": concept, "normalized_field": role},
        extra=(wrong_unit,),
    )
    refused = evaluate(request, store)
    assert refused.status == "abstain"
    assert refused.rejected_observations[0].reason_code == "MAPPING_UNIT_UNSUPPORTED"
