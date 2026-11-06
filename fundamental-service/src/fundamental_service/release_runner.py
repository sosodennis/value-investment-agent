"""Read-only validation and canary execution for immutable data releases.

The runner is deliberately independent from the serving application. It reads
immutable repositories, validates the candidate's signed evidence, and runs a
point-in-time fact selection without reading or changing the active pointer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import CanonicalFactV1, SourceSnapshotV1
from .data_releases import (
    DataReleaseError,
    DataReleaseManifestV1,
    DataReleaseTrustRootsV1,
    DataReleaseVerificationV1,
    MappingRefV1,
    verify_data_release_candidate,
)
from .facts import (
    CanonicalFactRepository,
    CanonicalMappingV1,
    FilesystemCanonicalFactRepository,
)
from .replay import ArtifactStore
from .serialization import canonical_bytes, sha256_digest
from .snapshots import FilesystemSnapshotRepository


class ReleaseMappingReader(Protocol):
    def get_mapping(self, mapping_id: str) -> CanonicalMappingV1: ...


class ReleaseArtifactReader(Protocol):
    def read(self, artifact_id: str) -> bytes: ...


class DataReleaseCanaryReportV1(BaseModel):
    """Replayable evidence produced by a read-only candidate canary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verification: DataReleaseVerificationV1
    candidate_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    checked_snapshot_ids: tuple[str, ...] = ()
    checked_fact_digests: tuple[str, ...] = ()
    checked_artifact_digests: tuple[str, ...] = ()
    canary_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def canary_digest_matches(self) -> DataReleaseCanaryReportV1:
        payload = {
            "manifest_digest": self.candidate_manifest_digest,
            "verification_digest": self.verification.verification_digest,
            "source_revision": self.verification.source_revision,
            "snapshots": self.checked_snapshot_ids,
            "facts": self.checked_fact_digests,
            "artifacts": self.checked_artifact_digests,
        }
        if sha256_digest(payload) != self.canary_digest:
            raise ValueError("canary_digest does not match report evidence")
        return self


class DataReleaseCanaryRunner:
    """Validate one candidate without resolving or mutating active release state."""

    def __init__(
        self,
        *,
        snapshot_repository: object,
        fact_repository: CanonicalFactRepository,
        mapping_reader: ReleaseMappingReader,
        artifact_reader: ReleaseArtifactReader,
        trust_roots: DataReleaseTrustRootsV1,
    ) -> None:
        self._snapshots = snapshot_repository
        self._facts = fact_repository
        self._mappings = mapping_reader
        self._artifacts = artifact_reader
        self._trust_roots = trust_roots

    def validate(
        self,
        manifest: DataReleaseManifestV1,
        verification: DataReleaseVerificationV1,
    ) -> DataReleaseCanaryReportV1:
        verify_data_release_candidate(manifest, verification, self._trust_roots)
        self._verify_artifacts(manifest, verification)
        checked_snapshots, checked_facts = self._verify_snapshots_and_facts(manifest)
        self._verify_mappings(manifest.mapping_refs)

        canary_payload = {
            "manifest_digest": manifest.manifest_digest,
            "verification_digest": verification.verification_digest,
            "source_revision": verification.source_revision,
            "snapshots": checked_snapshots,
            "facts": checked_facts,
            "artifacts": self._artifact_digests(manifest, verification),
        }
        canary_digest = sha256_digest(canary_payload)
        report_payload = {
            "verification": verification,
            "candidate_manifest_digest": manifest.manifest_digest,
            "checked_snapshot_ids": checked_snapshots,
            "checked_fact_digests": checked_facts,
            "checked_artifact_digests": canary_payload["artifacts"],
            "canary_digest": canary_digest,
        }
        return DataReleaseCanaryReportV1.model_validate(report_payload)

    def _verify_artifacts(
        self,
        manifest: DataReleaseManifestV1,
        verification: DataReleaseVerificationV1,
    ) -> None:
        refs = (
            *manifest.taxonomy_refs,
            *manifest.artifact_refs,
            *verification.evidence_refs,
        )
        refs += tuple(
            evidence_ref
            for review in verification.mapping_reviews
            for evidence_ref in review.evidence_refs
        )
        expected: dict[str, str] = {}
        for reference in refs:
            previous = expected.setdefault(
                reference.artifact_id, reference.content_hash
            )
            if previous != reference.content_hash:
                raise DataReleaseError(
                    "DATA_RELEASE_ARTIFACT_REFERENCE_CONFLICT",
                    "candidate references one artifact ID with different hashes",
                )
            try:
                content = self._artifacts.read(reference.artifact_id)
            except Exception as exc:  # pragma: no cover - adapter boundary
                raise DataReleaseError(
                    "DATA_RELEASE_ARTIFACT_UNAVAILABLE",
                    f"release artifact {reference.artifact_id} is unavailable",
                ) from exc
            actual = hashlib.sha256(content).hexdigest()
            if actual != reference.content_hash:
                raise DataReleaseError(
                    "DATA_RELEASE_ARTIFACT_HASH_MISMATCH",
                    f"release artifact {reference.artifact_id} failed hash verification",
                )

    def _artifact_digests(
        self,
        manifest: DataReleaseManifestV1,
        verification: DataReleaseVerificationV1,
    ) -> tuple[str, ...]:
        refs = (
            *manifest.taxonomy_refs,
            *manifest.artifact_refs,
            *verification.evidence_refs,
        )
        refs += tuple(
            evidence_ref
            for review in verification.mapping_reviews
            for evidence_ref in review.evidence_refs
        )
        return tuple(sorted({reference.content_hash for reference in refs}))

    def _verify_snapshots_and_facts(
        self, manifest: DataReleaseManifestV1
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        snapshot_ids: list[str] = []
        fact_digests: list[str] = []
        declared_fields = set(manifest.required_fields)
        for reference in manifest.snapshot_refs:
            try:
                snapshot = self._snapshots.get(reference.snapshot_id)
            except Exception as exc:  # pragma: no cover - adapter boundary
                raise DataReleaseError(
                    "DATA_RELEASE_SNAPSHOT_UNAVAILABLE",
                    f"release snapshot {reference.snapshot_id} is unavailable",
                ) from exc
            if snapshot.manifest_digest != reference.manifest_digest:
                raise DataReleaseError(
                    "DATA_RELEASE_SNAPSHOT_MISMATCH",
                    f"release snapshot {reference.snapshot_id} has a different manifest digest",
                )
            resolved = self._resolve_facts(snapshot, manifest.required_fields)
            declared = {item.fact_id: item.fact_digest for item in reference.facts}
            actual = {
                item.fact_id: sha256_digest(item.model_dump(mode="json"))
                for item in resolved
            }
            if actual != declared:
                raise DataReleaseError(
                    "DATA_RELEASE_FACT_MISMATCH",
                    f"release snapshot {reference.snapshot_id} failed its fact canary",
                )
            if {item.normalized_field for item in resolved} != declared_fields:
                raise DataReleaseError(
                    "DATA_RELEASE_FIELDS_UNAVAILABLE",
                    f"release snapshot {reference.snapshot_id} does not cover required fields",
                )
            snapshot_ids.append(snapshot.snapshot_id)
            fact_digests.extend(sorted(actual.values()))
        return tuple(snapshot_ids), tuple(sorted(fact_digests))

    def _resolve_facts(
        self, snapshot: SourceSnapshotV1, required_fields: tuple[str, ...]
    ) -> tuple[CanonicalFactV1, ...]:
        try:
            return self._facts.resolve(
                snapshot=snapshot,
                valuation_timestamp=snapshot.valuation_timestamp,
                required_fields=required_fields,
            )
        except Exception as exc:  # pragma: no cover - adapter boundary
            raise DataReleaseError(
                "DATA_RELEASE_CANARY_FAILED",
                f"point-in-time canary failed for {snapshot.snapshot_id}",
            ) from exc

    def _verify_mappings(self, refs: tuple[MappingRefV1, ...]) -> None:
        for reference in refs:
            try:
                mapping = self._mappings.get_mapping(reference.mapping_id)
            except Exception as exc:  # pragma: no cover - adapter boundary
                raise DataReleaseError(
                    "DATA_RELEASE_MAPPING_UNAVAILABLE",
                    f"release mapping {reference.mapping_id} is unavailable",
                ) from exc
            actual = sha256_digest(mapping.model_dump(mode="json"))
            if actual != reference.mapping_digest:
                raise DataReleaseError(
                    "DATA_RELEASE_MAPPING_HASH_MISMATCH",
                    f"release mapping {reference.mapping_id} failed hash verification",
                )


class _FilesystemMappingReader:
    def __init__(self, root: Path) -> None:
        self._root = root

    def get_mapping(self, mapping_id: str) -> CanonicalMappingV1:
        path = (self._root / f"{mapping_id}.json").resolve()
        if self._root.resolve() not in path.parents:
            raise ValueError("mapping path escapes repository root")
        return CanonicalMappingV1.model_validate_json(path.read_bytes())


def _load_candidate(
    path: Path,
) -> tuple[DataReleaseManifestV1, DataReleaseVerificationV1]:
    payload = json.loads(path.read_bytes())
    return (
        DataReleaseManifestV1.model_validate(payload["manifest"]),
        DataReleaseVerificationV1.model_validate(payload["verification"]),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--snapshots-root", type=Path, required=True)
    parser.add_argument("--facts-root", type=Path, required=True)
    parser.add_argument("--mappings-root", type=Path, required=True)
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--trust-roots", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest, verification = _load_candidate(args.candidate)
        report = DataReleaseCanaryRunner(
            snapshot_repository=FilesystemSnapshotRepository(args.snapshots_root),
            fact_repository=FilesystemCanonicalFactRepository(args.facts_root),
            mapping_reader=_FilesystemMappingReader(args.mappings_root),
            artifact_reader=ArtifactStore(args.artifacts_root),
            trust_roots=DataReleaseTrustRootsV1.from_file(args.trust_roots),
        ).validate(manifest, verification)
    except (OSError, ValueError, DataReleaseError) as exc:
        print(f"data release canary failed: {exc}", file=sys.stderr)
        return 2
    print(canonical_bytes(report).decode("utf-8"))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by CLI integration
    raise SystemExit(main())
