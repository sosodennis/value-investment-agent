from __future__ import annotations

import hashlib
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import Protocol

from .artifact_evidence import EvidenceArtifactReader, require_retained_artifact
from .command_artifacts import EvidenceArtifactStore
from .data_releases import ArtifactRefV1, DataReleaseError
from .fiscal_discovery import FiscalDiscovery
from .fiscal_validation_contracts import (
    FiscalOriginalValidationEvidenceV1,
    FiscalOriginalValidationRequestV1,
    FiscalValidationIncompleteV1,
    FiscalValidationMatchedV1,
    FiscalValidationOutcomeV1,
    FiscalValidationPinV1,
    ResolvedFiscalValidationRequestV1,
    ValidatedFiscalOriginalV1,
)
from .replay import (
    ArtifactPublicationDeadlineExceeded,
    ArtifactPublicationV1,
    ArtifactRecordV1,
)
from .sec_capture import sec_response_artifact_id
from .sec_source import SecSourceError
from .serialization import canonical_bytes
from .snapshots import ContentAddressedStore, SnapshotError


class FiscalSourceValidationRead(Protocol):
    def check_current(self) -> None: ...


class FiscalSourceValidationPort(Protocol):
    def observe(
        self,
        request: ResolvedFiscalValidationRequestV1,
        outcome: FiscalValidationOutcomeV1,
        *,
        artifacts: EvidenceArtifactReader,
        deadline_at: datetime,
    ) -> FiscalSourceValidationRead: ...

    def validate(
        self, request: ResolvedFiscalValidationRequestV1, *, deadline_at: datetime
    ) -> FiscalValidationOutcomeV1: ...

    def verify(
        self,
        request: ResolvedFiscalValidationRequestV1,
        outcome: FiscalValidationOutcomeV1,
        *,
        artifacts: EvidenceArtifactReader,
        deadline_at: datetime,
    ) -> None:
        """Rebuild SEC receipt/source and parser/action semantics using current pins.

        Read consumed artifact metadata and bodies through this reader so the
        closure can recheck their status after verification. The port owns source
        content reads, action/body dependencies, delivery, and current build checks.
        """
        ...


def _invalid(message: str) -> SnapshotError:
    return SnapshotError("FISCAL_VALIDATION_INVALID", message)


class FiscalArtifactRead:
    def __init__(
        self, artifacts: EvidenceArtifactStore, check_deadline: Callable[[], float]
    ) -> None:
        self._artifacts = artifacts
        self._check_deadline = check_deadline
        self._records: dict[str, ArtifactRecordV1 | None] = {}
        self._bodies: dict[str, tuple[str, int]] = {}
        self._parent: FiscalArtifactRead | None = None

    def for_consumer(self) -> FiscalArtifactRead:
        reader = FiscalArtifactRead(self._artifacts, self._check_deadline)
        reader._parent = self
        return reader

    def current(self, identity: str) -> ArtifactRecordV1 | None:
        self._check_deadline()
        try:
            record = self._artifacts.get(identity)
        except SnapshotError as error:
            if error.code != "ARTIFACT_NOT_FOUND":
                raise
            record = None
        self._check_deadline()
        return record

    def expect(self, identity: str, record: ArtifactRecordV1 | None) -> None:
        if self._records.setdefault(identity, record) != record:
            raise _invalid("fiscal validation artifact metadata changed")
        if self._parent is not None:
            self._parent.expect(identity, record)

    def _expect_body(self, identity: str, body: tuple[str, int]) -> None:
        if self._bodies.setdefault(identity, body) != body:
            raise _invalid("fiscal validation artifact bytes changed")
        if self._parent is not None:
            self._parent._expect_body(identity, body)

    def get(self, artifact_id: str) -> ArtifactRecordV1:
        record = self.current(artifact_id)
        self.expect(artifact_id, record)
        if record is None:
            raise SnapshotError(
                "ARTIFACT_NOT_FOUND", "fiscal validation evidence is missing"
            )
        if (
            record.artifact_id != artifact_id
            or record.status != "valid"
            or record.retention != "evidence"
        ):
            raise _invalid("fiscal validation requires current retained evidence")
        return record

    def read(self, artifact_id: str) -> bytes:
        record = self.get(artifact_id)
        raw = self._artifacts.read(artifact_id)
        self._check_deadline()
        if hashlib.sha256(raw).hexdigest() != record.content_hash:
            raise _invalid("fiscal validation artifact bytes changed")
        self._expect_body(artifact_id, (record.content_hash, len(raw)))
        return raw

    def check_bodies(self) -> None:
        for identity in tuple(self._bodies):
            self.read(identity)
        self.check_current()

    def check_current(self) -> None:
        for identity, expected in self._records.items():
            if self.current(identity) != expected:
                raise _invalid("fiscal validation artifact metadata changed")
        self._check_deadline()

    @property
    def records(self) -> tuple[tuple[str, ArtifactRecordV1 | None], ...]:
        return tuple(self._records.items())


@dataclass(frozen=True)
class FiscalSourceMetadataRead:
    evidence: FiscalOriginalValidationEvidenceV1
    records: tuple[tuple[str, ArtifactRecordV1 | None], ...]


class FiscalSourceContentRead:
    def __init__(
        self, content: ContentAddressedStore, check_deadline: Callable[[], float]
    ) -> None:
        self._content = content
        self._check_deadline = check_deadline
        self._consumed: dict[tuple[str, str], int] = {}

    def get(self, digest: str, *, media_type: str) -> bytes:
        self._check_deadline()
        raw = self._content.get(digest, media_type=media_type)
        self._check_deadline()
        key = (digest, media_type)
        if hashlib.sha256(raw).hexdigest() != digest or self._consumed.setdefault(
            key, len(raw)
        ) != len(raw):
            raise _invalid("retained fiscal source content changed")
        return raw

    def put(self, content: bytes, *, media_type: str) -> str:
        raise _invalid("source observation cannot publish content")

    def check_current(self) -> None:
        for digest, media_type in tuple(self._consumed):
            self.get(digest, media_type=media_type)


@dataclass(frozen=True)
class FiscalSourceRead:
    owner: FiscalSourceClosure
    source_owner: FiscalSourceValidationPort
    reader: FiscalArtifactRead
    validation: FiscalSourceValidationRead
    _evidence: FiscalOriginalValidationEvidenceV1
    deadline_at: datetime
    artifacts: EvidenceArtifactStore
    discovery: FiscalDiscovery

    @property
    def evidence(self) -> FiscalOriginalValidationEvidenceV1:
        return self._evidence.model_copy(deep=True)

    @property
    def records(self) -> tuple[tuple[str, ArtifactRecordV1 | None], ...]:
        return self.reader.records

    def check_current(self) -> None:
        with self.owner._operation(self.deadline_at):
            self._check_current()

    def _check_current(self) -> None:
        self.owner._before_deadline(self.deadline_at)
        if (
            self.owner._configured_source() is not self.source_owner
            or self.owner._artifacts is not self.artifacts
            or self.owner._discovery is not self.discovery
        ):
            raise _invalid("configured fiscal source owner changed")
        if (
            self.owner._resolve(
                self._evidence.request.selection, self.reader, self.deadline_at
            )
            != self._evidence.request
        ):
            raise _invalid("fiscal source discovery changed during admission")
        self.validation.check_current()
        self.reader.check_bodies()
        self.owner._before_deadline(self.deadline_at)


def _read_json(
    reader: FiscalArtifactRead,
    identity: str,
    value: object,
    dependencies: tuple[str, ...],
) -> None:
    record = reader.get(identity)
    if (
        record.media_type != "application/json"
        or record.dependency_hashes != dependencies
        or reader.read(identity) != canonical_bytes(value)
    ):
        raise _invalid("fiscal validation artifact identity differs")


class FiscalSourceClosure:
    def __init__(
        self,
        *,
        discovery: FiscalDiscovery,
        artifacts: EvidenceArtifactStore,
        pin: FiscalValidationPinV1,
        source: FiscalSourceValidationPort | None,
        capture_lock: Callable[[str, datetime], AbstractContextManager[None]],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        operation: Callable[
            [datetime], AbstractContextManager[None]
        ] = lambda _: nullcontext(),
    ) -> None:
        self._discovery = discovery
        self._artifacts = artifacts
        self._pin = pin
        self._source = source
        self._capture_lock = capture_lock
        self._clock = clock
        self._operation = operation

    def _before_deadline(self, deadline_at: datetime) -> float:
        now = self._clock()
        if (
            deadline_at.utcoffset() is None
            or now.utcoffset() is None
            or deadline_at <= now
        ):
            raise SecSourceError(
                "REQUEST_DEADLINE_EXCEEDED",
                "fiscal source validation deadline expired",
                retryable=True,
            )
        return (deadline_at - now).total_seconds()

    def _configured_source(self) -> FiscalSourceValidationPort:
        if self._source is None:
            raise SecSourceError(
                "FISCAL_VALIDATION_UNCONFIGURED",
                "fiscal source validation requires a configured source owner",
            )
        return self._source

    def _resolve(
        self,
        request: FiscalOriginalValidationRequestV1,
        reader: FiscalArtifactRead,
        deadline_at: datetime,
    ) -> ResolvedFiscalValidationRequestV1:
        ref = request.discovery_ref
        if ref.role != "fiscal-discovery" or ref.media_type != "application/json":
            raise _invalid("fiscal validation requires a discovery artifact reference")
        require_retained_artifact(reader, ref)
        discovery, filing, records = self._discovery.read_for_validation(
            ref.artifact_id, request.accession_number, deadline_at=deadline_at
        )
        for identity, record in records:
            reader.expect(identity, record)
        if discovery.declared_source_revision != self._pin.declared_source_revision:
            raise _invalid(
                "fiscal discovery source revision differs from configured revision"
            )
        return ResolvedFiscalValidationRequestV1(
            selection=request,
            filing=filing,
            valuation_timestamp=discovery.valuation_timestamp,
            pin=self._pin,
        )

    def _verify(
        self,
        evidence: FiscalOriginalValidationEvidenceV1,
        reader: FiscalArtifactRead,
        deadline_at: datetime,
    ) -> None:
        self._verify_artifacts(evidence, reader)
        self._configured_source().verify(
            evidence.request,
            evidence.outcome,
            artifacts=reader,
            deadline_at=deadline_at,
        )
        reader.check_current()

    def _verify_artifacts(
        self, evidence: FiscalOriginalValidationEvidenceV1, reader: FiscalArtifactRead
    ) -> None:
        request, outcome = evidence.request, evidence.outcome
        _read_json(
            reader,
            request.artifact_id,
            request,
            (request.selection.discovery_ref.content_hash,),
        )
        if not isinstance(outcome, FiscalValidationIncompleteV1):
            for receipt in outcome.responses:
                _read_json(
                    reader,
                    sec_response_artifact_id(request.scope, receipt.uri),
                    receipt,
                    (receipt.content_hash,),
                )
            for ref in outcome.action_refs:
                if ref.media_type != "application/json":
                    raise _invalid("fiscal parser actions require JSON evidence")
                require_retained_artifact(reader, ref)
                reader.read(ref.artifact_id)

    def _read_evidence(
        self,
        artifact_id: str,
        reader: FiscalArtifactRead,
        deadline_at: datetime,
        *,
        expected_request: ResolvedFiscalValidationRequestV1 | None = None,
    ) -> FiscalOriginalValidationEvidenceV1:
        try:
            record = reader.get(artifact_id)
            raw = reader.read(artifact_id)
            evidence = FiscalOriginalValidationEvidenceV1.model_validate_json(raw)
            if (
                evidence.artifact_id != artifact_id
                or record.media_type != "application/json"
                or record.dependency_hashes != evidence.dependencies
                or canonical_bytes(evidence.model_dump(mode="json")) != raw
            ):
                raise _invalid("fiscal validation closure identity differs")
            request = expected_request or self._resolve(
                evidence.request.selection, reader, deadline_at
            )
            if evidence.request != request:
                raise _invalid(
                    "fiscal validation request differs from current discovery"
                )
        except (ValueError, DataReleaseError) as error:
            raise _invalid("retained fiscal validation failed verification") from error
        return evidence

    def _read(
        self,
        artifact_id: str,
        reader: FiscalArtifactRead,
        deadline_at: datetime,
        *,
        expected_request: ResolvedFiscalValidationRequestV1 | None = None,
    ) -> FiscalOriginalValidationEvidenceV1:
        try:
            evidence = self._read_evidence(
                artifact_id, reader, deadline_at, expected_request=expected_request
            )
            self._verify(evidence, reader, deadline_at)
            return evidence
        except (ValueError, DataReleaseError) as error:
            raise _invalid("retained fiscal validation failed verification") from error

    def observe(self, artifact_id: str, *, deadline_at: datetime) -> FiscalSourceRead:
        with self._operation(deadline_at):
            artifacts, discovery = self._artifacts, self._discovery
            reader = FiscalArtifactRead(
                artifacts, partial(self._before_deadline, deadline_at)
            )
            source = self._configured_source()
            try:
                evidence = self._read_evidence(artifact_id, reader, deadline_at)
                self._verify_artifacts(evidence, reader)
                validation = source.observe(
                    evidence.request,
                    evidence.outcome,
                    artifacts=reader,
                    deadline_at=deadline_at,
                )
                reader.check_current()
                return FiscalSourceRead(
                    self,
                    source,
                    reader,
                    validation,
                    evidence,
                    deadline_at,
                    artifacts,
                    discovery,
                )
            except (ValueError, DataReleaseError) as error:
                raise _invalid(
                    "retained fiscal validation failed verification"
                ) from error

    def read(
        self, artifact_id: str, *, deadline_at: datetime
    ) -> FiscalOriginalValidationEvidenceV1:
        return self.read_with_metadata(artifact_id, deadline_at=deadline_at).evidence

    def read_with_metadata(
        self, artifact_id: str, *, deadline_at: datetime
    ) -> FiscalSourceMetadataRead:
        with self._operation(deadline_at):
            reader = FiscalArtifactRead(
                self._artifacts, partial(self._before_deadline, deadline_at)
            )
            self._before_deadline(deadline_at)
            self._configured_source()
            evidence = self._read(artifact_id, reader, deadline_at)
            return FiscalSourceMetadataRead(evidence, reader.records)

    def read_matched(
        self, ref: ArtifactRefV1, *, deadline_at: datetime
    ) -> ValidatedFiscalOriginalV1:
        with self._operation(deadline_at):
            return self._read_matched(ref, deadline_at)

    def _read_matched(
        self, ref: ArtifactRefV1, deadline_at: datetime
    ) -> ValidatedFiscalOriginalV1:
        reader = FiscalArtifactRead(
            self._artifacts, partial(self._before_deadline, deadline_at)
        )
        if ref.role != "fiscal-original-validation":
            raise _invalid("fiscal validation reference has the wrong role")
        try:
            require_retained_artifact(reader, ref)
        except DataReleaseError as error:
            raise _invalid("retained fiscal validation reference differs") from error
        evidence = self._read(ref.artifact_id, reader, deadline_at)
        if not isinstance(evidence.outcome, FiscalValidationMatchedV1):
            raise SnapshotError(
                "FISCAL_VALIDATION_REFUSED",
                "retained fiscal original did not pass validation",
            )
        return ValidatedFiscalOriginalV1(evidence_ref=ref, outcome=evidence.outcome)

    def execute(
        self, request: FiscalOriginalValidationRequestV1, *, deadline_at: datetime
    ) -> tuple[FiscalOriginalValidationEvidenceV1, ArtifactPublicationV1]:
        with self._operation(deadline_at):
            return self._execute(request, deadline_at)

    def _execute(
        self, request: FiscalOriginalValidationRequestV1, deadline_at: datetime
    ) -> tuple[FiscalOriginalValidationEvidenceV1, ArtifactPublicationV1]:
        check_deadline = partial(self._before_deadline, deadline_at)
        check_deadline()
        source = self._configured_source()
        reader = FiscalArtifactRead(self._artifacts, check_deadline)
        try:
            request = FiscalOriginalValidationRequestV1.model_validate_json(
                canonical_bytes(request)
            )
            resolved = self._resolve(request, reader, deadline_at)
            completed_id = resolved.completed_artifact_id
            check_deadline()
            with self._capture_lock(completed_id, deadline_at):
                check_deadline()
                current = reader.current(completed_id)
                if current is not None:
                    reader.expect(completed_id, current)
                    evidence = self._read(
                        completed_id, reader, deadline_at, expected_request=resolved
                    )
                    publication = ArtifactPublicationV1(artifact=current, wrote=False)
                else:
                    reader.check_current()
                    self._artifacts.put_with_receipt(
                        resolved.artifact_id,
                        resolved,
                        (request.discovery_ref.content_hash,),
                        publication_budget=check_deadline,
                    )
                    check_deadline()
                    outcome = source.validate(resolved, deadline_at=deadline_at)
                    check_deadline()
                    evidence = FiscalOriginalValidationEvidenceV1(
                        request=resolved, outcome=outcome
                    )
                    raw = canonical_bytes(evidence.model_dump(mode="json"))
                    evidence = FiscalOriginalValidationEvidenceV1.model_validate_json(
                        raw
                    )
                    self._verify(evidence, reader, deadline_at)
                    artifact_id = evidence.artifact_id
                    publication = self._artifacts.put_bytes_with_receipt(
                        artifact_id,
                        raw,
                        evidence.dependencies,
                        media_type="application/json",
                        publication_budget=check_deadline,
                    )
                    reader.expect(artifact_id, publication.artifact)
            reader.check_current()
        except ArtifactPublicationDeadlineExceeded as error:
            raise SecSourceError(
                error.code, error.message, retryable=error.retryable
            ) from error
        except (ValueError, DataReleaseError) as error:
            raise _invalid("fiscal validation failed verification") from error
        return evidence, publication
