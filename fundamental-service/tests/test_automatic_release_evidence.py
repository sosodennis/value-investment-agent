"""Regulatory selection keeps complete-original ambiguity after shared indexing."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from fundamental_service import automatic_release_evidence as evidence
from fundamental_service.automatic_mapping_runner import approve_mapping
from fundamental_service.contracts import QualityStatus
from fundamental_service.data_releases import (
    AutomaticMappingApprovalV1,
    DataReleaseError,
)
from fundamental_service.serialization import sha256_digest
from test_automatic_mapping import case, MACHINE_KEY


@pytest.mark.parametrize("conflicting", (False, True))
def test_regulatory_selection_coalesces_equal_originals_and_rejects_conflicts(
    tmp_path, monkeypatch, conflicting
):
    request, store, roots, _ = case(tmp_path)
    receipt = approve_mapping(
        request, artifacts=store, trust_roots=roots, private_key=MACHINE_KEY
    )
    review = AutomaticMappingApprovalV1.model_validate_json(
        store.read(receipt.approval_publication.artifact.artifact_id)
    )
    original = request.original
    other = request.model_copy(
        update={
            "original": original.model_copy(
                update={
                    "decision_at": original.decision_at + timedelta(seconds=1),
                }
                if conflicting
                else {}
            )
        }
    )
    replayed = iter((request, other))
    # Isolate source selection; mapping replay/signature validation has its own
    # retained-evidence tests and remains the producer of both source claims.
    monkeypatch.setattr(
        evidence, "verify_automatic_mapping_replay", lambda *a, **kw: next(replayed)
    )
    snapshot = SimpleNamespace(
        sec_integrity_evidence=request.integrity,
        parser_version=original.report.parser_version,
        validation_profile_digest=original.report.validation_profile_digest,
        coverage_status=QualityStatus.VERIFIED,
        source_records=(
            SimpleNamespace(
                source_id="sec-filing",
                accession_number=original.source.accession_number,
                uri=original.source.uri,
                content_hash=original.source.content_hash,
            ),
        ),
        identity=SimpleNamespace(issuer_id=original.source.cik),
        valuation_timestamp=original.decision_at + timedelta(days=1),
    )
    manifest = SimpleNamespace(
        snapshot_refs=(SimpleNamespace(snapshot_id="snapshot"),),
        parser_version=original.report.parser_version,
    )
    content = SimpleNamespace(
        mapping_reviews=(
            review,
            review.model_copy(update={"mapping_id": "second-mapping"}),
        ),
        evidence_refs=(),
    )
    options = dict(
        snapshots=SimpleNamespace(get=lambda _: snapshot),
        mappings=SimpleNamespace(get_mapping=lambda _: None),
        artifacts=store,
        validation_profile_digest=original.report.validation_profile_digest,
    )
    if conflicting:
        with pytest.raises(DataReleaseError) as error:
            evidence.require_automatic_release_sources(manifest, content, **options)
        assert error.value.code == "AUTOMATIC_RELEASE_REGULATORY_EVIDENCE_MISSING"
    else:
        assert evidence.require_automatic_release_sources(
            manifest, content, **options
        ) == (
            sha256_digest(
                {
                    "snapshot_id": "snapshot",
                    "original": sha256_digest(original),
                    "integrity": sha256_digest(request.integrity),
                    "parser_replay": original.report.replay_digest(),
                }
            ),
        )
