"""Persistent evidence storage shared by Fundamental operator commands."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, Protocol

from .data_releases import DataReleaseError
from .metadata import PostgresArtifactStore, PostgresContentStore, PostgresMetadataStore
from .replay import ArtifactPublicationV1, ArtifactRecordV1, ArtifactStore


class EvidenceArtifactStore(Protocol):
    def get(self, artifact_id: str) -> ArtifactRecordV1: ...

    def read(self, artifact_id: str) -> bytes: ...

    def put_with_receipt(
        self,
        artifact_id: str,
        value: object,
        dependency_hashes: tuple[str, ...] = (),
        *,
        media_type: str = "application/json",
        retention: Literal["evidence", "operational_cache"] = "evidence",
    ) -> ArtifactPublicationV1: ...

    def put_bytes_with_receipt(
        self,
        artifact_id: str,
        payload: bytes,
        dependency_hashes: tuple[str, ...] = (),
        *,
        media_type: str = "application/octet-stream",
        retention: Literal["evidence", "operational_cache"] = "evidence",
    ) -> ArtifactPublicationV1: ...


@contextmanager
def command_artifacts(
    offline_root: Path | None,
    *,
    storage_error_code: str = "EVIDENCE_STORAGE_UNCONFIGURED",
) -> Iterator[EvidenceArtifactStore]:
    if offline_root is not None:
        yield ArtifactStore(offline_root)
        return
    database_url = os.getenv("FUNDAMENTAL_SERVICE_DATABASE_URL")
    data_root = os.getenv("FUNDAMENTAL_SERVICE_DATA_ROOT")
    if not database_url or not data_root:
        raise DataReleaseError(
            storage_error_code,
            "service database and content root must be configured",
        )
    metadata = PostgresMetadataStore(database_url, auto_migrate=False)
    try:
        metadata.start()
        yield PostgresArtifactStore(
            metadata, PostgresContentStore(Path(data_root) / "content", metadata)
        )
    finally:
        metadata.close()
