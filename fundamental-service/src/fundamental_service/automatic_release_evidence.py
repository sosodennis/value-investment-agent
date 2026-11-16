"""Require regulatory evidence for every original before machine signing."""

from __future__ import annotations

import hashlib

from .automatic_mapping import (
    AutomaticMappingSourceV1,
    verify_automatic_mapping_replay,
)
from .automatic_mapping_batch import AutomaticMappingBatchRequestV1
from .contracts import (
    QualityStatus,
    SecHistoryIntegrityEvidenceV1,
    SecIntegrityEvidenceV1,
)
from .data_releases import (
    AutomaticMappingApprovalV1,
    DataReleaseContentRequestV1,
    DataReleaseError,
    DataReleaseManifestV1,
)
from .issuer_release_evidence import verify_original_bytes, verify_original_integrity
from .original_issuer import IssuerOperatingSourceV1, OriginalIssuerEvidenceV1
from .release_runner import (
    ReleaseArtifactReader,
    ReleaseMappingReader,
    ReleaseSnapshotReader,
)
from .mapping_input_storage import resolve_mapping_input
from .serialization import canonical_bytes, sha256_digest
from .taxonomy_evidence import require_original_taxonomy


def _retained_original_inputs(
    request: DataReleaseContentRequestV1,
    *,
    artifacts: ReleaseArtifactReader,
    parser_version: str,
) -> tuple[AutomaticMappingBatchRequestV1, ...]:
    sources = []
    for ref in request.evidence_refs:
        if ref.role != "automatic-mapping-batch-input-v1":
            continue
        raw = artifacts.read(ref.artifact_id)
        if (
            ref.media_type != "application/json"
            or hashlib.sha256(raw).hexdigest() != ref.content_hash
        ):
            raise DataReleaseError(
                "AUTOMATIC_RELEASE_ORIGINAL_ARTIFACT_MISMATCH",
                "retained original inputs require exact JSON evidence bytes",
            )
        source = resolve_mapping_input(
            raw, AutomaticMappingBatchRequestV1, artifacts=artifacts
        )
        if (
            source.source_revision != request.source_revision
            or source.original.status != "matched"
            or any(item not in request.evidence_refs for item in source.evidence_refs)
        ):
            raise DataReleaseError(
                "AUTOMATIC_RELEASE_ORIGINAL_EVIDENCE_MISMATCH",
                "retained originals must bind the release revision and evidence closure",
            )
        contents = {}
        for item in source.evidence_refs:
            content = artifacts.read(item.artifact_id)
            if hashlib.sha256(content).hexdigest() != item.content_hash:
                raise DataReleaseError(
                    "AUTOMATIC_RELEASE_ORIGINAL_ARTIFACT_MISMATCH",
                    "retained original source bytes differ from their references",
                )
            contents[item.content_hash] = content
        verify_original_integrity(
            source.original, source.integrity, parser_version=parser_version
        )
        require_original_taxonomy(
            source.original.report.taxonomy_cache_hash or "",
            source.evidence_refs,
            contents,
        )
        verify_original_bytes(source.integrity, contents)
        sources.append(source)
    return tuple(sources)


def require_automatic_release_sources(
    manifest: DataReleaseManifestV1,
    request: DataReleaseContentRequestV1,
    *,
    snapshots: ReleaseSnapshotReader,
    mappings: ReleaseMappingReader,
    artifacts: ReleaseArtifactReader,
    validation_profile_digest: str,
) -> tuple[str, ...]:
    """Complement content checks with mandatory, profile-bound SEC coverage.

    The content runner replays issuer original bytes and mapped facts. Security
    releases require automatic approvals, which replay the same source checks
    and additionally bind every released observation to its parser report.
    """
    automatic = tuple(
        review
        for review in request.mapping_reviews
        if isinstance(review, AutomaticMappingApprovalV1)
    )
    sources: tuple[AutomaticMappingSourceV1, ...] = tuple(
        verify_automatic_mapping_replay(
            review, mappings.get_mapping(review.mapping_id), artifacts=artifacts
        )
        for review in automatic
    )
    sources += _retained_original_inputs(
        request, artifacts=artifacts, parser_version=manifest.parser_version
    )
    evidence: set[str] = set()
    for reference in manifest.snapshot_refs:
        snapshot = snapshots.get(reference.snapshot_id)
        if isinstance(snapshot, IssuerOperatingSourceV1):
            integrities = tuple(
                SecIntegrityEvidenceV1.model_validate_json(
                    artifacts.read(ref.artifact_id)
                )
                for ref in manifest.artifact_refs
                if ref.role == "sec-issuer-integrity-v1"
            )
            originals = snapshot.originals
            pairs: list[tuple[OriginalIssuerEvidenceV1, SecIntegrityEvidenceV1]] = []
            for original in originals:
                sec_matches = tuple(
                    item
                    for item in integrities
                    if item.accession_number == original.source.accession_number
                )
                if len(sec_matches) != 1:
                    raise DataReleaseError(
                        "AUTOMATIC_RELEASE_REGULATORY_EVIDENCE_MISSING",
                        "each original requires one exact regulatory report",
                    )
                pairs.append((original, sec_matches[0]))
        else:
            if len(automatic) != len(request.mapping_reviews):
                raise DataReleaseError(
                    "AUTOMATIC_RELEASE_MAPPING_METHOD_UNSUPPORTED",
                    "security machine releases require source-replayed automatic mappings",
                )
            integrity = snapshot.sec_integrity_evidence
            expected = (
                tuple(item.integrity for item in integrity.components)
                if isinstance(integrity, SecHistoryIntegrityEvidenceV1)
                else (integrity,)
                if isinstance(integrity, SecIntegrityEvidenceV1)
                else ()
            )
            if not expected:
                raise DataReleaseError(
                    "AUTOMATIC_RELEASE_REGULATORY_EVIDENCE_MISSING",
                    "machine signing requires SEC integrity for every snapshot",
                )
            if (
                snapshot.parser_version != manifest.parser_version
                or snapshot.validation_profile_digest != validation_profile_digest
                or snapshot.coverage_status is not QualityStatus.VERIFIED
                or {
                    (source.accession_number, source.uri, source.content_hash)
                    for source in snapshot.source_records
                    if source.source_id == "sec-filing"
                }
                != {
                    (
                        item.accession_number,
                        item.primary_document_uri,
                        item.raw_content_hash,
                    )
                    for item in expected
                }
            ):
                raise DataReleaseError(
                    "AUTOMATIC_RELEASE_SOURCE_PROFILE_MISMATCH",
                    "security snapshot must cover exactly its validated SEC originals",
                )
            pairs = []
            for integrity in expected:
                original_matches = {
                    canonical_bytes(source.original): source.original
                    for source in sources
                    if source.integrity == integrity
                }
                if len(original_matches) != 1:
                    raise DataReleaseError(
                        "AUTOMATIC_RELEASE_REGULATORY_EVIDENCE_MISSING",
                        "each security original requires one unambiguous replayed report",
                    )
                pairs.append((next(iter(original_matches.values())), integrity))
        if not pairs:
            raise DataReleaseError(
                "AUTOMATIC_RELEASE_REGULATORY_EVIDENCE_MISSING",
                "machine signing cannot accept an empty original set",
            )
        for original, integrity in pairs:
            if (
                original.source.cik != snapshot.identity.issuer_id
                or original.source.available_at > snapshot.valuation_timestamp
                or original.decision_at > snapshot.valuation_timestamp
            ):
                raise DataReleaseError(
                    "AUTOMATIC_RELEASE_SOURCE_PROFILE_MISMATCH",
                    "original must match the snapshot issuer and valuation cutoff",
                )
            verify_original_integrity(
                original, integrity, parser_version=manifest.parser_version
            )
            if (
                integrity.validation_profile_digest != validation_profile_digest
                or original.report.validation_profile_digest
                != validation_profile_digest
            ):
                raise DataReleaseError(
                    "AUTOMATIC_RELEASE_VALIDATION_PROFILE_MISMATCH",
                    "regulatory evidence must use the deployed validation profile",
                )
            evidence.add(
                sha256_digest(
                    {
                        "snapshot_id": reference.snapshot_id,
                        "original": sha256_digest(original),
                        "integrity": sha256_digest(integrity),
                        "parser_replay": original.report.replay_digest(),
                    }
                )
            )
    return tuple(sorted(evidence))
