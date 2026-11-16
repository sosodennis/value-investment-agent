"""Mapping evidence reuses immutable originals across fields and revisions."""

import json

from fundamental_service.automatic_mapping_runner import approve_mapping
from fundamental_service.serialization import sha256_digest
from test_automatic_mapping import case, MACHINE_KEY


def test_fields_and_revisions_share_one_original_without_inline_reports(tmp_path):
    request, store, roots, _ = case(tmp_path)
    requests = (
        request,
        request.model_copy(update={"source_revision": "b" * 40}),
        request.model_copy(
            update={
                "proposal": request.proposal.model_copy(
                    update={"normalized_field": "unsupported-role"}
                )
            }
        ),
    )
    references = []
    for item in requests:
        receipt = approve_mapping(
            item, artifacts=store, trust_roots=roots, private_key=MACHINE_KEY
        )
        raw = store.read(receipt.input_publication.artifact.artifact_id)
        envelope = json.loads(raw)
        assert envelope["protocol"] == "fundamental.mapping-input-artifact.v2"
        assert "original" not in envelope["request"]
        assert envelope["input_digest"] == sha256_digest(item)
        reference = envelope["original_ref"]
        references.append(reference)
        assert reference["content_hash"] == sha256_digest(
            item.original.report.model_dump(mode="json")
        )
        assert len(raw) < len(store.read(reference["artifact_id"]))
    assert references[0] == references[1] == references[2]


def test_report_reuse_is_independent_of_evidence_set(tmp_path):
    from fundamental_service.data_releases import ArtifactRefV1

    request, store, roots, _ = case(tmp_path)
    first = approve_mapping(
        request, artifacts=store, trust_roots=roots, private_key=MACHINE_KEY
    )
    extra = store.put_bytes_with_receipt("additional-proof", b"additional proof")
    ref = ArtifactRefV1(
        artifact_id=extra.artifact.artifact_id,
        content_hash=extra.artifact.content_hash,
        media_type=extra.artifact.media_type,
        role="additional-proof",
    )
    changed = request.model_copy(
        update={
            "evidence_refs": tuple(
                sorted((*request.evidence_refs, ref), key=lambda r: r.artifact_id)
            )
        }
    )
    second = approve_mapping(
        changed, artifacts=store, trust_roots=roots, private_key=MACHINE_KEY
    )

    def original(receipt):
        return json.loads(store.read(receipt.input_publication.artifact.artifact_id))[
            "original_ref"
        ]

    assert original(first) == original(second)


def test_retained_inline_input_still_replays(tmp_path):
    from fundamental_service.automatic_mapping import AutomaticMappingRequestV1
    from fundamental_service.mapping_input_storage import resolve_mapping_input
    from fundamental_service.serialization import canonical_bytes

    request, store, _, _ = case(tmp_path)
    assert (
        resolve_mapping_input(
            canonical_bytes(request), AutomaticMappingRequestV1, artifacts=store
        )
        == request
    )


def test_shared_original_is_checked_against_its_digest_and_semantic_input(tmp_path):
    import pytest

    from fundamental_service.automatic_mapping import AutomaticMappingRequestV1
    from fundamental_service.data_releases import DataReleaseError
    from fundamental_service.mapping_input_storage import resolve_mapping_input
    from fundamental_service.serialization import canonical_bytes
    from fundamental_service.snapshots import SnapshotError

    request, store, roots, _ = case(tmp_path)
    receipt = approve_mapping(
        request, artifacts=store, trust_roots=roots, private_key=MACHINE_KEY
    )
    raw = store.read(receipt.input_publication.artifact.artifact_id)
    envelope = json.loads(raw)
    reference = envelope["original_ref"]
    record = store.get(reference["artifact_id"])
    path = store._artifact_path(record.content_hash, record.media_type)
    original = path.read_bytes()
    path.write_bytes(b"corrupt")
    with pytest.raises(SnapshotError, match="failed verification"):
        resolve_mapping_input(raw, AutomaticMappingRequestV1, artifacts=store)
    path.unlink()
    with pytest.raises(SnapshotError, match="bytes are unavailable"):
        resolve_mapping_input(raw, AutomaticMappingRequestV1, artifacts=store)
    path.write_bytes(original)
    envelope["original_ref"]["content_hash"] = "0" * 64
    with pytest.raises(DataReleaseError) as error:
        resolve_mapping_input(
            canonical_bytes(envelope), AutomaticMappingRequestV1, artifacts=store
        )
    assert error.value.code == "MAPPING_ORIGINAL_HASH_MISMATCH"
    envelope["original_ref"] = reference | {"content_hash": record.content_hash}
    envelope["request"]["source_revision"] = "f" * 40
    with pytest.raises(DataReleaseError) as error:
        resolve_mapping_input(
            canonical_bytes(envelope), AutomaticMappingRequestV1, artifacts=store
        )
    assert error.value.code == "MAPPING_INPUT_IDENTITY_MISMATCH"


def test_valuation_date_change_reuses_the_same_parser_report(tmp_path):
    from datetime import timedelta

    from fundamental_service.original_issuer import evaluate_original_issuer

    request, store, roots, _ = case(tmp_path)
    original = request.original
    later = request.model_copy(
        update={
            "original": evaluate_original_issuer(
                original.report,
                source=original.source,
                decision_at=original.decision_at + timedelta(seconds=1),
            )
        }
    )
    references = []
    for item in (request, later):
        receipt = approve_mapping(
            item, artifacts=store, trust_roots=roots, private_key=MACHINE_KEY
        )
        references.append(
            json.loads(store.read(receipt.input_publication.artifact.artifact_id))[
                "original_ref"
            ]
        )
    assert sha256_digest(request) != sha256_digest(later)
    assert references[0] == references[1]


def test_batch_children_share_the_report_and_repeat_without_writes(tmp_path):
    from fundamental_service.automatic_mapping_runner import approve_mapping_batch
    from test_automatic_mapping_batch import batch_case
    from test_issuer_operating_release import inventory

    request, store, roots = batch_case(tmp_path)
    first = approve_mapping_batch(
        request, artifacts=store, trust_roots=roots, private_key=MACHINE_KEY
    )
    publications = [
        first.input_publication,
        *(r.input_publication for r in first.mapping_receipts),
    ]
    references = {
        json.loads(store.read(p.artifact.artifact_id))["original_ref"]["content_hash"]
        for p in publications
    }
    assert len(references) == 1
    before = inventory(store.root)
    second = approve_mapping_batch(
        request, artifacts=store, trust_roots=roots, private_key=MACHINE_KEY
    )
    assert not second.wrote
    assert inventory(store.root) == before


def test_substituted_report_and_unknown_envelope_version_are_rejected(tmp_path):
    import pytest
    from pydantic import ValidationError

    from fundamental_service.automatic_mapping import AutomaticMappingRequestV1
    from fundamental_service.mapping_input_storage import resolve_mapping_input
    from fundamental_service.serialization import canonical_bytes

    request, store, roots, _ = case(tmp_path / "first")
    other, _, _, _ = case(tmp_path / "other", observation_changes={"value": "999"})
    receipt = approve_mapping(
        request, artifacts=store, trust_roots=roots, private_key=MACHINE_KEY
    )
    envelope = json.loads(store.read(receipt.input_publication.artifact.artifact_id))
    replacement = store.put_with_receipt(
        "different-report", other.original.report.model_dump(mode="json")
    )
    envelope["original_ref"].update(
        artifact_id=replacement.artifact.artifact_id,
        content_hash=replacement.artifact.content_hash,
    )
    with pytest.raises(ValidationError, match="issuer evidence digest mismatch"):
        resolve_mapping_input(
            canonical_bytes(envelope), AutomaticMappingRequestV1, artifacts=store
        )
    envelope["protocol"] = "fundamental.mapping-input-artifact.v999"
    with pytest.raises(ValidationError):
        resolve_mapping_input(
            canonical_bytes(envelope), AutomaticMappingRequestV1, artifacts=store
        )


def test_invalidated_shared_report_cannot_replay_valid_input(tmp_path):
    import pytest

    from fundamental_service.automatic_mapping import AutomaticMappingRequestV1
    from fundamental_service.data_releases import DataReleaseError
    from fundamental_service.mapping_input_storage import resolve_mapping_input

    request, store, roots, _ = case(tmp_path)
    receipt = approve_mapping(
        request, artifacts=store, trust_roots=roots, private_key=MACHINE_KEY
    )
    raw = store.read(receipt.input_publication.artifact.artifact_id)
    reference = json.loads(raw)["original_ref"]
    store.invalidate(reference["artifact_id"])
    with pytest.raises(DataReleaseError, match="valid retained"):
        resolve_mapping_input(raw, AutomaticMappingRequestV1, artifacts=store)


def test_interleaved_batch_counts_the_shared_report_write(tmp_path, monkeypatch):
    from fundamental_service.automatic_mapping_runner import approve_mapping_batch
    from test_automatic_mapping_batch import batch_case

    request, store, roots = batch_case(tmp_path)
    publish = store.put_with_receipt
    interleaved = False

    def publish_with_contender(artifact_id, *args, **kwargs):
        nonlocal interleaved
        publication = publish(artifact_id, *args, **kwargs)
        if (
            artifact_id.startswith("automatic-mapping-parser-report-")
            and not interleaved
        ):
            assert publication.wrote
            interleaved = True
            other = approve_mapping_batch(
                request, artifacts=store, trust_roots=roots, private_key=MACHINE_KEY
            )
            assert other.wrote
        return publication

    monkeypatch.setattr(store, "put_with_receipt", publish_with_contender)
    receipt = approve_mapping_batch(
        request, artifacts=store, trust_roots=roots, private_key=MACHINE_KEY
    )
    assert interleaved and receipt.wrote
    assert receipt.parser_report_publication.wrote
    assert not receipt.input_publication.wrote
    assert not receipt.decision_publication.wrote
