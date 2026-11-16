"""Require current retained metadata when consuming immutable release bytes."""

from contextlib import contextmanager
from collections.abc import Iterator
from typing import Protocol

from .data_releases import ArtifactRefV1, DataReleaseError
from .replay import ArtifactRecordV1


class EvidenceArtifactReader(Protocol):
    def get(self, artifact_id: str) -> ArtifactRecordV1: ...

    def read(self, artifact_id: str) -> bytes: ...


@contextmanager
def retained_artifact_operation(
    artifacts: EvidenceArtifactReader, artifact_ids: tuple[str, ...]
) -> Iterator[EvidenceArtifactReader]:
    """Let a repository batch one check, retaining its end-of-read state guard."""
    operation = getattr(artifacts, "retained_read_operation", None)
    if callable(operation):
        with operation(artifact_ids) as reader:
            yield reader
    else:
        yield artifacts


def require_retained_artifact(
    artifacts: EvidenceArtifactReader,
    ref: ArtifactRefV1,
    *,
    dependency_hashes: tuple[str, ...] | None = None,
) -> ArtifactRecordV1:
    """Require current exact metadata even when immutable bytes are already checked."""
    record = artifacts.get(ref.artifact_id)
    if (
        record.artifact_id != ref.artifact_id
        or record.status != "valid"
        or record.retention != "evidence"
        or record.content_hash != ref.content_hash
        or record.media_type != ref.media_type
        or dependency_hashes is not None
        and record.dependency_hashes != dependency_hashes
    ):
        raise DataReleaseError(
            "ARTIFACT_EVIDENCE_INVALID",
            "release inputs require exact valid retained artifact evidence",
        )
    return record


def read_retained_artifact(
    artifacts: EvidenceArtifactReader,
    ref: ArtifactRefV1,
    *,
    dependency_hashes: tuple[str, ...] | None = None,
) -> bytes:
    """Check exact, stable metadata; the consumer checks bytes and domain meaning."""
    record = require_retained_artifact(
        artifacts, ref, dependency_hashes=dependency_hashes
    )
    raw = artifacts.read(ref.artifact_id)
    if artifacts.get(ref.artifact_id) != record:
        raise DataReleaseError(
            "ARTIFACT_EVIDENCE_CHANGED",
            "release artifact metadata changed during its read",
        )
    return raw
