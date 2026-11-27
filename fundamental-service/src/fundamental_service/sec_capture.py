"""Durable original SEC responses scoped to a pinned historical acquisition."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Literal, Protocol, TypeVar

from pydantic import AwareDatetime, Field

from .artifact_evidence import EvidenceArtifactReader
from .contracts import StrictModel
from .replay import ArtifactRecordV1
from .sec_source import (
    SecEdgarSourceAdapter,
    SecSourceError,
    SecRequestTransportPort,
    _SecResponse,
)
from .serialization import canonical_bytes, sha256_digest
from .snapshots import ContentAddressedStore, SnapshotError


class SecCaptureScopeV1(StrictModel):
    cik: str = Field(pattern=r"^\d{10}$")
    accession_number: str = Field(pattern=r"^\d{10}-\d{2}-\d{6}$")
    valuation_timestamp: AwareDatetime
    source_profile: str = Field(min_length=1)


class SecSubmissionsCaptureScopeV1(StrictModel):
    protocol: Literal["sec-original-annual-discovery-v1"] = (
        "sec-original-annual-discovery-v1"
    )
    cik: str = Field(pattern=r"^[0-9]{10}$")
    valuation_timestamp: AwareDatetime


class SecFiscalSubmissionsCaptureScopeV1(StrictModel):
    protocol: Literal["sec-original-fiscal-discovery-v1"] = (
        "sec-original-fiscal-discovery-v1"
    )
    cik: str = Field(pattern=r"^[0-9]{10}$")
    valuation_timestamp: AwareDatetime


class SecStoredResponseV1(StrictModel):
    uri: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    http_status: int = Field(ge=200, lt=300)
    media_type: str
    captured_at: AwareDatetime
    response_headers: tuple[tuple[str, str], ...]
    declared_size: int | None = Field(default=None, ge=0)
    received_size: int = Field(ge=0)


class SecResponseReceiptV1(SecStoredResponseV1):
    schema_version: Literal["sec-response-receipt.v1"] = "sec-response-receipt.v1"
    scope: (
        SecCaptureScopeV1
        | SecSubmissionsCaptureScopeV1
        | SecFiscalSubmissionsCaptureScopeV1
    )


class SecArchivedResponseReceiptV1(SecStoredResponseV1):
    schema_version: Literal["sec-archived-response.v1"] = "sec-archived-response.v1"
    cik: str = Field(pattern=r"^\d{10}$")
    accession_number: str = Field(pattern=r"^\d{10}-\d{2}-\d{6}$")


Receipt = TypeVar("Receipt", bound=SecStoredResponseV1)


def sec_response_artifact_id(
    scope: (
        SecCaptureScopeV1
        | SecSubmissionsCaptureScopeV1
        | SecFiscalSubmissionsCaptureScopeV1
    ),
    uri: str,
) -> str:
    key = sha256_digest(
        {"protocol": "sec-response-receipt.v1", "scope": scope, "uri": uri}
    )
    return f"sec-response:{key}"


class SecCaptureStore(Protocol):
    def get(self, artifact_id: str) -> ArtifactRecordV1: ...

    def read(self, artifact_id: str) -> bytes: ...

    def put(
        self,
        artifact_id: str,
        value: object,
        dependency_hashes: tuple[str, ...] = (),
        *,
        media_type: str = "application/json",
        retention: Literal["evidence", "operational_cache"] = "evidence",
    ) -> ArtifactRecordV1: ...


class RetainedSecSourceAdapter(SecEdgarSourceAdapter):
    """Reuse exact original receipts before provider I/O, including after failure."""

    def __init__(
        self,
        delegate: SecRequestTransportPort,
        *,
        scope: (
            SecCaptureScopeV1
            | SecSubmissionsCaptureScopeV1
            | SecFiscalSubmissionsCaptureScopeV1
        ),
        receipts: SecCaptureStore,
        content: ContentAddressedStore,
        capture_lock: Callable[[str], AbstractContextManager[None]],
        check_deadline: Callable[[], object] = lambda: None,
        replay_reader: EvidenceArtifactReader | None = None,
        publish_receipt: Callable[[str, object, tuple[str, ...]], object] | None = None,
    ) -> None:
        super().__init__(delegate.policy)
        self._delegate = delegate
        self.scope = scope
        self._receipts: EvidenceArtifactReader = replay_reader or receipts
        self._replay_only = replay_reader is not None
        self._publish_receipt = publish_receipt or (
            lambda identity, value, dependencies: receipts.put(
                identity, value, dependencies
            )
        )
        self._content = content
        self._capture_lock = capture_lock
        self._check_deadline = check_deadline
        self._observed: dict[str, SecResponseReceiptV1] = {}

    @property
    def observed_responses(self) -> tuple[SecResponseReceiptV1, ...]:
        """Exact receipts used before success or failure of this attempt."""
        return tuple(self._observed[uri] for uri in sorted(self._observed))

    def _request(
        self, uri: str, *, deadline_at: datetime | None = None
    ) -> _SecResponse:
        self._check_deadline()
        if deadline_at is not None and deadline_at <= datetime.now(UTC):
            raise SecSourceError(
                "REQUEST_DEADLINE_EXCEEDED",
                "SEC acquisition deadline expired",
                retryable=True,
            )
        artifact_id = sec_response_artifact_id(self.scope, uri)
        retained = self.read_retained_response_with_record(uri)
        if retained is not None:
            receipt, _, response = retained
            self._observed[uri] = receipt
            return response
        if self._replay_only:
            raise SnapshotError(
                "SEC_CAPTURE_MISSING", "required scoped SEC capture is missing"
            )
        key = artifact_id.removeprefix("sec-response:")
        archive_key = self._archive_key(uri)
        with self._capture_lock(archive_key or key):
            self._check_deadline()
            retained = self.read_retained_response_with_record(uri)
            if retained is not None:
                receipt, _, response = retained
                self._observed[uri] = receipt
                return response

            archive_id = f"sec-archived-response:{archive_key}"
            retained_archive = (
                self._read_receipt(archive_id, SecArchivedResponseReceiptV1)
                if archive_key is not None
                else None
            )
            if retained_archive is not None:
                archived, _ = retained_archive
                if (
                    not isinstance(self.scope, SecCaptureScopeV1)
                    or archived.cik != self.scope.cik
                    or archived.accession_number != self.scope.accession_number
                    or archived.uri != uri
                ):
                    raise SnapshotError(
                        "SEC_CAPTURE_IDENTITY_MISMATCH",
                        "retained original SEC response differs from its key",
                    )
                response = self._response(archived)
                stored = SecStoredResponseV1.model_validate(
                    archived.model_dump(
                        exclude={"schema_version", "cik", "accession_number"}
                    )
                )
            else:
                response = self._delegate._request(uri, deadline_at=deadline_at)
                self._check_deadline()
                content_hash = self._content.put(
                    response.content,
                    media_type=response.media_type or "application/octet-stream",
                )
                self._check_deadline()
                if content_hash != hashlib.sha256(response.content).hexdigest():
                    raise SnapshotError(
                        "SEC_CAPTURE_HASH_MISMATCH",
                        "SEC response store returned a different digest",
                    )
                stored = SecStoredResponseV1(
                    uri=uri,
                    content_hash=content_hash,
                    http_status=response.http_status,
                    media_type=response.media_type,
                    captured_at=response.available_at,
                    response_headers=response.response_headers,
                    declared_size=response.declared_size,
                    received_size=len(response.content),
                )
                if archive_key is not None and isinstance(
                    self.scope, SecCaptureScopeV1
                ):
                    archived = SecArchivedResponseReceiptV1(
                        cik=self.scope.cik,
                        accession_number=self.scope.accession_number,
                        **stored.model_dump(),
                    )
                    self._publish_receipt(archive_id, archived, (content_hash,))
            receipt = SecResponseReceiptV1(scope=self.scope, **stored.model_dump())
            self._check_deadline()
            self._publish_receipt(artifact_id, receipt, (stored.content_hash,))
            self._check_deadline()
            self._observed[uri] = receipt
            return response

    def _archive_key(self, uri: str) -> str | None:
        if not isinstance(self.scope, SecCaptureScopeV1):
            return None
        prefix = (
            f"https://www.sec.gov/Archives/edgar/data/{int(self.scope.cik)}/"
            f"{self.scope.accession_number.replace('-', '')}/"
        )
        if not uri.startswith(prefix) or not re.fullmatch(
            r"[A-Za-z0-9_.-]{1,200}", uri[len(prefix) :]
        ):
            return None
        return sha256_digest(
            {
                "protocol": "sec-archived-response.v1",
                "cik": self.scope.cik,
                "accession_number": self.scope.accession_number,
                "uri": uri,
            }
        )

    def read_retained_response(self, uri: str) -> SecResponseReceiptV1 | None:
        """Read and verify a captured response without contacting the provider."""
        retained = self.read_retained_response_with_record(uri)
        return retained[0] if retained is not None else None

    def read_retained_response_with_record(
        self, uri: str
    ) -> tuple[SecResponseReceiptV1, ArtifactRecordV1, _SecResponse] | None:
        """Return the verified payload and the exact receipt metadata it used."""
        retained = self._read_receipt(
            sec_response_artifact_id(self.scope, uri), SecResponseReceiptV1
        )
        if retained is None:
            return None
        receipt, record = retained
        if receipt.scope != self.scope or receipt.uri != uri:
            raise SnapshotError(
                "SEC_CAPTURE_IDENTITY_MISMATCH",
                "retained SEC receipt differs from its key",
            )
        return receipt, record, self._response(receipt)

    def _read_receipt(
        self, artifact_id: str, receipt_type: type[Receipt]
    ) -> tuple[Receipt, ArtifactRecordV1] | None:
        self._check_deadline()
        try:
            record = self._receipts.get(artifact_id)
        except SnapshotError as error:
            if error.code != "ARTIFACT_NOT_FOUND":
                raise
            self._check_deadline()
            return None
        self._check_deadline()
        if (
            record.artifact_id != artifact_id
            or record.status != "valid"
            or record.retention != "evidence"
            or record.media_type != "application/json"
        ):
            raise SnapshotError(
                "SEC_CAPTURE_INVALID", "retained SEC receipt is not valid evidence"
            )
        try:
            raw = self._receipts.read(artifact_id)
            self._check_deadline()
            receipt = receipt_type.model_validate_json(raw)
            if (
                canonical_bytes(receipt) != raw
                or hashlib.sha256(raw).hexdigest() != record.content_hash
                or record.dependency_hashes != (receipt.content_hash,)
            ):
                raise ValueError("retained SEC receipt identity differs")
            return receipt, record
        except ValueError as error:
            raise SnapshotError(
                "SEC_CAPTURE_INVALID", "retained SEC receipt is invalid"
            ) from error

    def _response(self, receipt: SecStoredResponseV1) -> _SecResponse:
        self._check_deadline()
        payload = self._content.get(
            receipt.content_hash,
            media_type=receipt.media_type or "application/octet-stream",
        )
        if (
            len(payload) != receipt.received_size
            or hashlib.sha256(payload).hexdigest() != receipt.content_hash
        ):
            raise SnapshotError(
                "SEC_CAPTURE_HASH_MISMATCH",
                "retained SEC response failed verification",
            )
        self._check_deadline()
        return _SecResponse(
            content=payload,
            http_status=receipt.http_status,
            media_type=receipt.media_type,
            available_at=receipt.captured_at,
            response_headers=receipt.response_headers,
            declared_size=receipt.declared_size,
        )
