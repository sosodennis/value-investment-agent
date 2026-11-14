"""Require regulatory evidence for every original before machine signing."""

from __future__ import annotations

from .automatic_mapping import verify_automatic_mapping_replay
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
from .issuer_release_evidence import verify_original_integrity
from .original_issuer import IssuerOperatingSourceV1, OriginalIssuerEvidenceV1
from .release_runner import (
    ReleaseArtifactReader,
    ReleaseMappingReader,
    ReleaseSnapshotReader,
)
from .serialization import canonical_bytes, sha256_digest


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
    sources = tuple(
        verify_automatic_mapping_replay(
            review, mappings.get_mapping(review.mapping_id), artifacts=artifacts
        )
        for review in automatic
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
