"""A valid signature cannot replace the existing SEC byte-integrity proof."""

import json
from datetime import date, timedelta

import pytest

from fundamental_service.data_releases import DataReleaseError
from fundamental_service.arelle_parser import fact_semantic_digest
from fundamental_service.issuer_release_evidence import original_rebuilt_facts
from fundamental_service.facts import canonical_fact_digest
from fundamental_service.original_issuer import (
    compose_issuer_operating_source,
    evaluate_original_issuer,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_issuer_operating_release import fixture, rebind_original, resign


def replace_integrity(bundle, evidence, value):
    ref = evidence.add(
        "synthetic-integrity", canonical_bytes(value), "sec-issuer-integrity-v1"
    )
    return resign(
        bundle,
        artifact_refs=tuple(
            ref if old.artifact_id == ref.artifact_id else old
            for old in bundle.manifest.artifact_refs
        ),
    )


@pytest.mark.parametrize(
    "field,value",
    (
        ("raw_received_size", 999),
        ("archive_size", 999),
        ("archive_member_size", 999),
        ("normalized_content_size", 999),
        ("declared_primary_size", 999),
        ("archive_member_name", "other.xml"),
        ("archive_member_hash", "a" * 64),
    ),
)
def test_signed_integrity_metadata_must_reproduce_retained_bytes(
    tmp_path, field, value
):
    bundle, service, evidence, _, _ = fixture(tmp_path)
    integrity = json.loads(evidence.values["synthetic-integrity"])
    integrity[field] = value
    bundle = replace_integrity(bundle, evidence, integrity)
    with pytest.raises(DataReleaseError) as error:
        service.publish(bundle)
    assert error.value.code == "DATA_RELEASE_ORIGINAL_BYTES_MISMATCH"


def test_invalid_integrity_retains_typed_refusal(tmp_path):
    bundle, service, evidence, _, _ = fixture(tmp_path)
    bundle = replace_integrity(bundle, evidence, {"not": "integrity evidence"})
    with pytest.raises(DataReleaseError) as error:
        service.publish(bundle)
    assert error.value.code == "DATA_RELEASE_ORIGINAL_INTEGRITY_INVALID"


def test_taxonomy_artifact_must_be_original_parser_manifest(tmp_path):
    bundle, service, evidence, _, _ = fixture(tmp_path)
    other = evidence.add("other-taxonomy", b"different synthetic taxonomy")
    bundle = resign(bundle, taxonomy_refs=(other,))
    with pytest.raises(DataReleaseError) as error:
        service.publish(bundle)
    assert error.value.code == "DATA_RELEASE_TAXONOMY_MANIFEST_UNAVAILABLE"


def test_changing_evidence_reader_cannot_swap_bytes_during_verification(tmp_path):
    bundle, service, evidence, _, _ = fixture(tmp_path)
    original_read = evidence.read
    reads = 0

    def changing_read(artifact_id):
        nonlocal reads
        raw = original_read(artifact_id)
        if artifact_id == "synthetic-original":
            reads += 1
            if reads > 1:
                return b"changed during verification"
        return raw

    evidence.read = changing_read
    with pytest.raises(DataReleaseError) as error:
        service.publish(bundle)
    assert error.value.code == "DATA_RELEASE_ARTIFACT_HASH_MISMATCH"


def test_release_cannot_hide_an_older_original_observation(tmp_path):
    bundle, service, _, _, _ = fixture(tmp_path)
    oldest = min(bundle.facts, key=lambda fact: fact.period_end or fact.instant)
    retained = tuple(fact for fact in bundle.facts if fact.fact_id != oldest.fact_id)
    references = tuple(
        ref
        for ref in bundle.manifest.snapshot_refs[0].facts
        if ref.fact_id != oldest.fact_id
    )
    snapshot = bundle.manifest.snapshot_refs[0].model_copy(
        update={
            "facts": references,
            "fact_set_digest": sha256_digest(references),
        }
    )
    bundle = resign(
        bundle.model_copy(update={"facts": retained}), snapshot_refs=(snapshot,)
    )
    with pytest.raises(DataReleaseError) as error:
        service.publish(bundle)
    assert error.value.code == "DATA_RELEASE_ORIGINAL_FACT_MISMATCH"


def test_complete_original_retains_segment_contexts_without_publishing_them(tmp_path):
    bundle, service, evidence, _, _ = fixture(tmp_path)
    report = bundle.sources[0].originals[0].report
    selected = next(f for f in report.facts if f.concept == "us-gaap:revenue")
    segmented = tuple(
        selected.model_copy(
            update={
                "context_id": f"segment-{year}",
                "period_start": date(year, 1, 1),
                "period_end": date(year, 12, 31),
                "value": "123",
                "consolidation_scope": "segmented",
                "dimensions": (
                    ("us-gaap:StatementBusinessSegmentsAxis", "example:Other"),
                ),
            }
        )
        for year in (2018, selected.period_end.year)
    )
    bundle = rebind_original(
        bundle, report_changes={"facts": (*report.facts, *segmented)}
    )
    original = bundle.sources[0].originals[0]
    integrity = json.loads(evidence.values["synthetic-integrity"])
    integrity.update(
        {
            "normalized_fact_digest": fact_semantic_digest(original.report),
            "archive_fact_digest": fact_semantic_digest(original.report),
            "normalized_fact_count": len(original.report.facts),
            "archive_fact_count": len(original.report.facts),
        }
    )
    bundle = replace_integrity(bundle, evidence, integrity)
    service.publish(bundle)
    expected = original_rebuilt_facts(
        bundle.sources[0], {m.decision_id: m for m in bundle.mappings}
    )
    assert tuple(map(canonical_fact_digest, expected)) == tuple(
        map(canonical_fact_digest, bundle.facts)
    )
    assert all(not fact.context.dimensions for fact in expected)
    assert all(f in original.report.facts for f in segmented)


def test_rebuilt_history_selects_overlapping_originals_through_shared_resolver(
    tmp_path,
):
    bundle, _, _, _, _ = fixture(tmp_path)
    old = bundle.sources[0].originals[0]
    accession = "0000000001-26-000002"
    source = old.source.model_copy(
        update={
            "accession_number": accession,
            "uri": "https://www.sec.gov/Archives/edgar/data/1/"
            + accession.replace("-", "")
            + "/original.xml",
            "available_at": old.source.available_at + timedelta(days=1),
            "content_hash": "f" * 64,
            "parser_input_hash": "f" * 64,
        }
    )
    newer = evaluate_original_issuer(
        old.report.model_copy(update={"source_content_hash": source.parser_input_hash}),
        source=source,
        decision_at=old.decision_at,
    )
    view = compose_issuer_operating_source(
        (old, newer), valuation_timestamp=old.decision_at
    )
    expected = original_rebuilt_facts(view, {m.decision_id: m for m in bundle.mappings})
    assert len(expected) == len(bundle.facts)
    assert {fact.accession_number for fact in expected} == {accession}
    assert view.originals == (old, newer)
    assert len(old.report.facts) == len(newer.report.facts)
