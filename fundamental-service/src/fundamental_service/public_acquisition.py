"""Decision-scoped acquisition of retained public originals before preparation."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, contextmanager
from hashlib import sha256
from typing import Iterator, Literal, Protocol

from pydantic import AwareDatetime, Field, model_validator

from .contracts import SourceRole, StrictModel
from .metadata import PostgresMetadataStore
from .replay import ArtifactPublicationV1, ArtifactRecordV1
from .serialization import canonical_bytes, sha256_digest
from .snapshots import CapturedSource, ContentAddressedStore, SnapshotError
from .source_capture import SourceCaptureRequest
from .source_evidence import RetainedSourceV1, SourceArtifactV1


class PublicSourceAcquisitionRequestV1(StrictModel):
    protocol: Literal["public-source-acquisition-v1"] = "public-source-acquisition-v1"
    source_id: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    source_profile: str = Field(min_length=1)
    terms_reference: str = Field(min_length=1)
    valuation_timestamp: AwareDatetime

    @property
    def digest(self) -> str:
        return sha256_digest(self)


class PublicSourceAcquisitionEvidenceV1(StrictModel):
    protocol: Literal["public-source-acquisition-evidence-v1"] = (
        "public-source-acquisition-evidence-v1"
    )
    request: PublicSourceAcquisitionRequestV1
    status: Literal["captured", "failed"]
    source: SourceArtifactV1 | None = None
    role: SourceRole | None = None
    media_type: str | None = Field(default=None, min_length=1)
    http_status: int | None = Field(default=None, ge=200, lt=300)
    received_size: int | None = Field(default=None, ge=0)
    available_at: AwareDatetime | None = None
    publication_at: AwareDatetime | None = None
    issue_codes: tuple[str, ...] = ()
    retryable: bool = False

    @model_validator(mode="after")
    def evidence_matches_request(self) -> PublicSourceAcquisitionEvidenceV1:
        fields = (
            self.source,
            self.role,
            self.media_type,
            self.http_status,
            self.received_size,
            self.available_at,
        )
        if self.status == "failed":
            if (
                any(value is not None for value in fields)
                or self.publication_at is not None
                or len(self.issue_codes) != 1
                or not self.issue_codes[0].strip()
            ):
                raise ValueError("failed capture requires one refusal without source")
            return self
        if any(value is None for value in fields) or self.retryable:
            raise ValueError("captured source requires complete nonretryable evidence")
        assert self.source is not None and self.available_at is not None
        source = self.source
        request = self.request
        if (
            source.source_id != request.source_id
            or source.uri != request.uri
            or source.source_version != request.source_profile
            or source.terms_reference != request.terms_reference
            or self.available_at > source.captured_at
            or (
                self.publication_at is not None
                and self.publication_at > self.available_at
            )
        ):
            raise ValueError("captured source differs from its request or chronology")
        expected = (
            ("SOURCE_NOT_AVAILABLE_AT_VALUATION",)
            if self.available_at > request.valuation_timestamp
            else ()
        )
        if self.issue_codes != expected:
            raise ValueError("capture diagnostics must retain cutoff ineligibility")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)


class PublicSourceCapturePort(Protocol):
    def validate_capture(self, source_id: str, uri: str) -> SourceCaptureRequest: ...

    def capture(self, source_id: str, uri: str) -> CapturedSource: ...


class PublicAcquisitionArtifactStore(Protocol):
    def get(self, artifact_id: str) -> ArtifactRecordV1: ...

    def read(self, artifact_id: str) -> bytes: ...

    def put_with_receipt(
        self,
        artifact_id: str,
        value: object,
        dependency_hashes: tuple[str, ...] = (),
    ) -> ArtifactPublicationV1: ...


class PublicSourceAcquisition:
    """Reuse verified receipts; capture availability never grants source admission."""

    def __init__(
        self,
        *,
        provider: PublicSourceCapturePort,
        artifacts: PublicAcquisitionArtifactStore,
        content: ContentAddressedStore,
        capture_lock: Callable[[str], AbstractContextManager[None]],
    ) -> None:
        self._provider = provider
        self._artifacts = artifacts
        self._content = content
        self._capture_lock = capture_lock

    def read(self, artifact_id: str) -> PublicSourceAcquisitionEvidenceV1:
        record = self._artifacts.get(artifact_id)
        if (
            record.status != "valid"
            or record.retention != "evidence"
            or record.media_type != "application/json"
        ):
            raise SnapshotError(
                "PUBLIC_CAPTURE_INVALID", "capture receipt is not valid evidence"
            )
        raw = self._artifacts.read(artifact_id)
        try:
            evidence = PublicSourceAcquisitionEvidenceV1.model_validate_json(raw)
        except ValueError as error:
            raise SnapshotError(
                "PUBLIC_CAPTURE_INVALID", "capture receipt violates its contract"
            ) from error
        dependencies = tuple(
            sorted(
                set(
                    (evidence.request.digest,)
                    + ((evidence.source.content_sha256,) if evidence.source else ())
                )
            )
        )
        if (
            canonical_bytes(evidence) != raw
            or sha256(raw).hexdigest() != record.content_hash
            or record.dependency_hashes != dependencies
            or artifact_id != self._artifact_id(evidence)
        ):
            raise SnapshotError(
                "PUBLIC_CAPTURE_IDENTITY_MISMATCH", "capture receipt differs from key"
            )
        if evidence.source is not None:
            self.retained_source(evidence)
        return evidence

    def retained_source(
        self, evidence: PublicSourceAcquisitionEvidenceV1
    ) -> RetainedSourceV1:
        if evidence.source is None or evidence.media_type is None:
            raise SnapshotError("PUBLIC_CAPTURE_FAILED", "capture has no source bytes")
        source = evidence.source
        raw = self._content.get(source.content_sha256, media_type=evidence.media_type)
        if (
            sha256(raw).hexdigest() != source.content_sha256
            or len(raw) != evidence.received_size
        ):
            raise SnapshotError(
                "PUBLIC_CAPTURE_HASH_MISMATCH", "retained original failed verification"
            )
        return RetainedSourceV1(
            source_id=source.source_id,
            uri=source.uri,
            source_version=source.source_version,
            terms_reference=source.terms_reference,
            content=raw,
            captured_at=source.captured_at,
        )

    @staticmethod
    def _artifact_id(evidence: PublicSourceAcquisitionEvidenceV1) -> str:
        if evidence.retryable:
            return f"public-source-attempt:{evidence.digest}"
        return f"public-source-acquisition:{evidence.request.digest}"

    def execute(
        self, request: PublicSourceAcquisitionRequestV1
    ) -> ArtifactPublicationV1:
        with self._capture_lock(request.digest):
            artifact_id = f"public-source-acquisition:{request.digest}"
            # Recheck current deployment restrictions even when original bytes exist.
            validated = self._provider.validate_capture(request.source_id, request.uri)
            if (
                validated.source_id != request.source_id
                or validated.uri != request.uri
                or validated.terms_reference != request.terms_reference
                or any(
                    value is not None
                    for value in (
                        validated.available_at,
                        validated.publication_at,
                        validated.captured_at,
                    )
                )
            ):
                raise SnapshotError(
                    "SOURCE_REGISTRATION_MISMATCH",
                    "request terms differ from the configured source register",
                )
            try:
                record = self._artifacts.get(artifact_id)
            except SnapshotError as error:
                if error.code != "ARTIFACT_NOT_FOUND":
                    raise
            else:
                evidence = self.read(artifact_id)
                if evidence.request != request:
                    raise SnapshotError(
                        "PUBLIC_CAPTURE_IDENTITY_MISMATCH", "capture request changed"
                    )
                return ArtifactPublicationV1(artifact=record, wrote=False)
            try:
                source = self._provider.capture(request.source_id, request.uri)
            except SnapshotError as error:
                evidence = PublicSourceAcquisitionEvidenceV1(
                    request=request,
                    status="failed",
                    issue_codes=(error.code,),
                    retryable=error.retryable,
                )
            else:
                evidence = self._retain(request, source)
            dependencies = (request.digest,) + (
                (evidence.source.content_sha256,) if evidence.source else ()
            )
            return self._artifacts.put_with_receipt(
                self._artifact_id(evidence), evidence, dependencies
            )

    def _retain(
        self, request: PublicSourceAcquisitionRequestV1, source: CapturedSource
    ) -> PublicSourceAcquisitionEvidenceV1:
        if (
            source.source_id != request.source_id
            or source.uri != request.uri
            or source.captured_at is None
        ):
            raise SnapshotError(
                "PUBLIC_CAPTURE_IDENTITY_MISMATCH",
                "provider must return the requested original and actual capture time",
            )
        if any(
            value is not None and (value.tzinfo is None or value.utcoffset() is None)
            for value in (
                source.available_at,
                source.captured_at,
                source.publication_at,
            )
        ):
            raise SnapshotError(
                "SOURCE_TIMESTAMP_TIMEZONE_REQUIRED", "capture time must be zoned"
            )
        try:
            evidence = PublicSourceAcquisitionEvidenceV1(
                request=request,
                status="captured",
                source=SourceArtifactV1(
                    source_id=source.source_id,
                    uri=source.uri,
                    source_version=request.source_profile,
                    terms_reference=request.terms_reference,
                    content_sha256=sha256(source.content).hexdigest(),
                    captured_at=source.captured_at,
                ),
                role=source.role,
                media_type=source.media_type,
                http_status=source.http_status,
                received_size=len(source.content),
                available_at=source.available_at,
                publication_at=source.publication_at,
                issue_codes=("SOURCE_NOT_AVAILABLE_AT_VALUATION",)
                if source.available_at > request.valuation_timestamp
                else (),
            )
        except ValueError as error:
            raise SnapshotError(
                "PUBLIC_CAPTURE_INVALID", "provider returned invalid capture evidence"
            ) from error
        content_hash = self._content.put(source.content, media_type=source.media_type)
        assert evidence.source is not None
        if content_hash != evidence.source.content_sha256:
            raise SnapshotError(
                "PUBLIC_CAPTURE_HASH_MISMATCH", "source store returned a different hash"
            )
        return evidence


class PostgresPublicCaptureLock:
    """Lease a source identity before I/O; busy callers can safely retry."""

    def __init__(self, metadata: PostgresMetadataStore) -> None:
        self._metadata = metadata

    @contextmanager
    def __call__(self, key: str) -> Iterator[None]:
        lease = self._metadata.try_acquire_ingestion_lock(key)
        if lease is None:
            raise SnapshotError(
                "PUBLIC_CAPTURE_IN_PROGRESS",
                "an identical public source capture is in progress",
                retryable=True,
            )
        try:
            yield
        finally:
            self._metadata.release_ingestion_lock(lease)
