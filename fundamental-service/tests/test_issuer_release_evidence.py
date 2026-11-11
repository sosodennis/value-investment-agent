"""A valid signature cannot replace the existing SEC byte-integrity proof."""

import json

import pytest

from fundamental_service.data_releases import DataReleaseError
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_issuer_operating_release import fixture, resign


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
