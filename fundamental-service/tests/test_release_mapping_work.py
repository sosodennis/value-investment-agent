"""Mapping canaries consume current facts without scanning unrelated mappings."""

from collections import Counter
from decimal import Decimal
from types import SimpleNamespace

import pytest

from fundamental_service.automatic_mapping_evidence import (
    AutomaticMappingEvidenceChecks,
)
from fundamental_service.data_releases import (
    AutomaticMappingApprovalV1,
    DataReleaseError,
    FactRefV1,
)
from fundamental_service.facts import canonical_fact_digest
from fundamental_service.issuer_release_evidence import original_rebuilt_facts
from fundamental_service.original_issuer import compose_issuer_operating_source
from fundamental_service.release_runner import DataReleaseCanaryRunner
from fundamental_service.snapshots import SnapshotError
from test_automatic_mapping import approve, case, evaluate


def mapping_canary(tmp_path):
    initial = case(tmp_path / "initial")[0]
    revenue = next(
        f for f in initial.original.report.facts if f.concept == "us-gaap:Revenues"
    )
    request, store, roots, _ = case(
        tmp_path / "actual",
        extra=(
            revenue.model_copy(
                update={"concept": "us-gaap:OperatingIncomeLoss", "value": "10"}
            ),
        ),
    )
    requests = (
        request,
        request.model_copy(
            update={
                "proposal": request.proposal.model_copy(
                    update={
                        "source_concept": "us-gaap:OperatingIncomeLoss",
                        "normalized_field": "operating_income",
                    }
                )
            }
        ),
    )
    mappings = {}
    reviews = []
    for item in requests:
        mapping = evaluate(item, store).mapping
        assert mapping is not None
        mappings[mapping.decision_id] = mapping
        receipt = approve(item, store, roots)
        reviews.append(
            AutomaticMappingApprovalV1.model_validate_json(
                store.read(receipt.approval_publication.artifact.artifact_id)
            )
        )
    snapshot = compose_issuer_operating_source(
        (request.original,), valuation_timestamp=request.original.decision_at
    )
    facts = {fact.fact_id: fact for fact in original_rebuilt_facts(snapshot, mappings)}
    assert {fact.mapping_decision_id for fact in facts.values()} == set(mappings)
    references = tuple(
        FactRefV1(fact_id=f.fact_id, fact_digest=canonical_fact_digest(f))
        for f in facts.values()
    )
    manifest = SimpleNamespace(
        snapshot_refs=(
            SimpleNamespace(snapshot_id=snapshot.snapshot_id, facts=references),
        )
    )
    content = SimpleNamespace(mapping_reviews=tuple(reviews))
    reads = Counter()

    def get(identity):
        reads[identity] += 1
        return facts[identity].model_copy(deep=True)

    reader = SimpleNamespace(get=get)
    runner = DataReleaseCanaryRunner(
        snapshot_repository=SimpleNamespace(get=lambda _: snapshot),
        fact_repository=reader,
        mapping_reader=None,
        artifact_reader=store,
        trust_roots=roots,
    )
    return runner, manifest, content, mappings, facts, reader, reads


def test_automatic_canary_fact_reads_are_linear_and_scopes_are_fresh(tmp_path):
    runner, manifest, content, mappings, _, _, reads = mapping_canary(tmp_path)
    for _ in range(2):
        before = reads.copy()
        runner._verify_automatic_mappings(
            manifest,
            content,
            mappings,
            evidence_checks=AutomaticMappingEvidenceChecks(),
        )
        assert reads - before == Counter(
            {ref.fact_id: 2 for ref in manifest.snapshot_refs[0].facts}
        )


@pytest.mark.parametrize("change", ["value", "decision", "missing"])
def test_fact_replacement_between_index_and_consumption_refuses(tmp_path, change):
    runner, manifest, content, mappings, facts, reader, _ = mapping_canary(tmp_path)
    original = reader.get
    counts = Counter()

    def get(identity):
        counts[identity] += 1
        if counts[identity] == 2:
            if change == "missing":
                raise SnapshotError("FACT_NOT_FOUND", "removed")
            return facts[identity].model_copy(
                update={"value": Decimal("999")}
                if change == "value"
                else {"mapping_decision_id": "replaced"}
            )
        return original(identity)

    reader.get = get
    with pytest.raises((DataReleaseError, SnapshotError)) as error:
        runner._verify_automatic_mappings(
            manifest,
            content,
            mappings,
            evidence_checks=AutomaticMappingEvidenceChecks(),
        )
    assert error.value.code == (
        "FACT_NOT_FOUND" if change == "missing" else "DATA_RELEASE_FACT_MISMATCH"
    )


@pytest.mark.parametrize(
    "limits", [{"max_entries": 0}, {"max_retained_bytes": 0}, {"max_entries": 1}]
)
def test_reference_index_capacity_falls_back_to_complete_checks(
    tmp_path, monkeypatch, limits
):
    runner, manifest, content, mappings, _, _, reads = mapping_canary(tmp_path)
    build = runner._mapping_fact_references
    assert build(manifest, **limits) is None
    monkeypatch.setattr(
        runner, "_mapping_fact_references", lambda value: build(value, **limits)
    )
    reads.clear()
    runner._verify_automatic_mappings(
        manifest, content, mappings, evidence_checks=AutomaticMappingEvidenceChecks()
    )
    assert all(value >= len(mappings) for value in reads.values())
