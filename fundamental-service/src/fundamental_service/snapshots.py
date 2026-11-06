"""Immutable public-source snapshots and point-in-time selection primitives."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .contracts import (
    IdentityV1,
    IssueV1,
    QualityStatus,
    SecIntegrityEvidenceV1,
    Severity,
    SourceRecordV1,
    SourceRole,
    SourceSnapshotV1,
)
from .serialization import canonical_bytes, is_digest, sha256_digest


class SnapshotError(RuntimeError):
    """Stable source-plane failures exposed to callers and operational logs."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        evidence_ref: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.evidence_ref = evidence_ref


class ContentAddressedStore(Protocol):
    def put(self, content: bytes, *, media_type: str) -> str: ...

    def get(self, content_hash: str, *, media_type: str) -> bytes: ...


class FilesystemContentStore:
    """A service-owned SHA-256 store. Writes are atomic and never overwrite bytes."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, content_hash: str, media_type: str) -> Path:
        if not is_digest(content_hash) or content_hash != content_hash.lower():
            raise SnapshotError(
                "SOURCE_HASH_INVALID", "content hash must be lowercase SHA-256"
            )
        suffix = ".json" if media_type == "application/json" else ".bin"
        path = (self.root / content_hash[:2] / f"{content_hash}{suffix}").resolve()
        if self.root.resolve() not in path.parents:
            raise SnapshotError(
                "SOURCE_PATH_INVALID", "content path escapes store root"
            )
        return path

    def put(self, content: bytes, *, media_type: str) -> str:
        content_hash = hashlib.sha256(content).hexdigest()
        path = self._path(content_hash, media_type)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != content:
                raise SnapshotError(
                    "CONTENT_HASH_COLLISION",
                    "stored content hash does not match existing bytes",
                )
            return content_hash
        fd, temporary = tempfile.mkstemp(prefix="snapshot-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return content_hash

    def get(self, content_hash: str, *, media_type: str) -> bytes:
        path = self._path(content_hash, media_type)
        try:
            content = path.read_bytes()
        except FileNotFoundError as exc:
            raise SnapshotError(
                "SOURCE_BYTES_UNAVAILABLE", f"content {content_hash} is unavailable"
            ) from exc
        actual = hashlib.sha256(content).hexdigest()
        if actual != content_hash:
            raise SnapshotError(
                "SOURCE_HASH_MISMATCH", f"content {content_hash} failed verification"
            )
        return content


class SnapshotRepository(Protocol):
    def publish(self, snapshot: SourceSnapshotV1) -> None: ...

    def get(self, snapshot_id: str) -> SourceSnapshotV1: ...

    def find(
        self, *, identity: IdentityV1, valuation_timestamp: datetime
    ) -> tuple[SourceSnapshotV1, ...]: ...


class FilesystemSnapshotRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def publish(self, snapshot: SourceSnapshotV1) -> None:
        path = self._path(snapshot.snapshot_id)
        payload = canonical_bytes(snapshot)
        if path.exists():
            if path.read_bytes() != payload:
                raise SnapshotError(
                    "SNAPSHOT_IMMUTABLE", "published snapshot cannot be replaced"
                )
            return
        fd, temporary = tempfile.mkstemp(prefix="manifest-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def get(self, snapshot_id: str) -> SourceSnapshotV1:
        try:
            path = self._path(snapshot_id)
            payload = path.read_bytes()
        except (FileNotFoundError, ValueError) as exc:
            raise SnapshotError(
                "SNAPSHOT_NOT_FOUND", f"snapshot {snapshot_id} is unavailable"
            ) from exc
        return SourceSnapshotV1.model_validate_json(payload)

    def find(
        self, *, identity: IdentityV1, valuation_timestamp: datetime
    ) -> tuple[SourceSnapshotV1, ...]:
        matches: list[SourceSnapshotV1] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                snapshot = SourceSnapshotV1.model_validate_json(path.read_bytes())
            except (OSError, ValueError):
                continue
            if (
                snapshot.identity.issuer_id == identity.issuer_id
                and snapshot.identity.security_id == identity.security_id
                and snapshot.identity.share_class == identity.share_class
                and snapshot.identity.currency == identity.currency
                and snapshot.valuation_timestamp <= valuation_timestamp
            ):
                matches.append(snapshot)
        return tuple(
            sorted(
                matches,
                key=lambda item: (item.valuation_timestamp, item.snapshot_id),
                reverse=True,
            )
        )

    def _path(self, snapshot_id: str) -> Path:
        if (
            not snapshot_id
            or snapshot_id in {".", ".."}
            or any(char in snapshot_id for char in "/\\")
        ):
            raise ValueError("snapshot identifier contains an unsafe path")
        path = (self.root / f"{snapshot_id}.json").resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("snapshot path escapes repository root")
        return path


@dataclass(frozen=True)
class LegalSource:
    source_id: str
    role: SourceRole
    terms_reference: str
    retention: str
    permitted: bool = True


class SourceRegister:
    """Explicit free/public source terms; disallowed sources fail before capture."""

    def __init__(self, entries: tuple[LegalSource, ...] = ()) -> None:
        self._entries = {entry.source_id: entry for entry in entries}

    @property
    def entries(self) -> tuple[LegalSource, ...]:
        return tuple(self._entries.values())

    def require(self, source_id: str, *, role: SourceRole | None = None) -> LegalSource:
        entry = self._entries.get(source_id)
        if entry is None:
            raise SnapshotError(
                "SOURCE_NOT_REGISTERED", f"source {source_id} has no legal-use entry"
            )
        if not entry.permitted:
            raise SnapshotError(
                "SOURCE_TERMS_EXCLUDED", f"source {source_id} is excluded by its terms"
            )
        if role is not None and entry.role is not role:
            raise SnapshotError(
                "SOURCE_ROLE_MISMATCH",
                f"source {source_id} is registered as {entry.role.value}, "
                f"not {role.value}",
            )
        return entry


class RecordedSourceAdapter(Protocol):
    def fetch(
        self, source: LegalSource, uri: str
    ) -> tuple[bytes, int, str, datetime]: ...


class FixtureSourceAdapter:
    """Offline adapter for fixtures; it never performs network access."""

    def __init__(self, responses: dict[str, tuple[bytes, int, str, datetime]]) -> None:
        self.responses = responses

    def fetch(self, source: LegalSource, uri: str) -> tuple[bytes, int, str, datetime]:
        try:
            return self.responses[uri]
        except KeyError as exc:
            raise SnapshotError(
                "SOURCE_UNAVAILABLE", f"no recorded response for {uri}", retryable=True
            ) from exc


@dataclass(frozen=True)
class CapturedSource:
    source_id: str
    uri: str
    role: SourceRole
    content: bytes
    media_type: str
    http_status: int
    available_at: datetime
    publication_at: datetime | None = None
    accession_number: str | None = None
    form: str | None = None
    filed_at: datetime | None = None
    filing_version: str | None = None
    is_amendment: bool = False
    amends_accession: str | None = None
    supersedes_accession: str | None = None
    amendment_scope: str | None = None
    taxonomy_manifest_id: str | None = None
    captured_at: datetime | None = None
    response_headers: tuple[tuple[str, str], ...] = ()
    declared_size: int | None = None
    received_size: int | None = None


class SnapshotBuilder:
    def __init__(
        self,
        content_store: ContentAddressedStore,
        repository: SnapshotRepository,
        source_register: SourceRegister | None = None,
    ) -> None:
        self.content_store = content_store
        self.repository = repository
        self.source_register = source_register

    def build(
        self,
        *,
        identity: IdentityV1,
        valuation_timestamp: datetime,
        captured_at: datetime,
        parser_version: str,
        policy_version: str,
        sources: tuple[CapturedSource, ...],
        taxonomy_manifest_id: str | None = None,
        sec_integrity_evidence: SecIntegrityEvidenceV1 | None = None,
    ) -> SourceSnapshotV1:
        snapshot = self.prepare(
            identity=identity,
            valuation_timestamp=valuation_timestamp,
            captured_at=captured_at,
            parser_version=parser_version,
            policy_version=policy_version,
            sources=sources,
            taxonomy_manifest_id=taxonomy_manifest_id,
            sec_integrity_evidence=sec_integrity_evidence,
        )
        self.publish(snapshot)
        return snapshot

    def prepare(
        self,
        *,
        identity: IdentityV1,
        valuation_timestamp: datetime,
        captured_at: datetime,
        parser_version: str,
        policy_version: str,
        sources: tuple[CapturedSource, ...],
        taxonomy_manifest_id: str | None = None,
        sec_integrity_evidence: SecIntegrityEvidenceV1 | None = None,
    ) -> SourceSnapshotV1:
        """Persist source bytes and prepare a manifest without publishing it."""
        if not sources:
            raise SnapshotError(
                "SNAPSHOT_EMPTY", "a snapshot requires at least one source"
            )
        for timestamp_name, timestamp in (
            ("valuation_timestamp", valuation_timestamp),
            ("captured_at", captured_at),
        ):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise SnapshotError(
                    "SNAPSHOT_TIMESTAMP_TIMEZONE_REQUIRED",
                    f"{timestamp_name} must include a timezone",
                )
        records: list[SourceRecordV1] = []
        issues: list[IssueV1] = []
        for source in sources:
            if self.source_register is None:
                raise SnapshotError(
                    "SOURCE_REGISTER_REQUIRED",
                    "snapshot publication requires a legal source register",
                )
            legal_source = self.source_register.require(
                source.source_id, role=source.role
            )
            for timestamp_name, timestamp in (
                ("available_at", source.available_at),
                ("publication_at", source.publication_at),
                ("filed_at", source.filed_at),
            ):
                if timestamp is not None and timestamp.tzinfo is None:
                    raise SnapshotError(
                        "SOURCE_TIMESTAMP_TIMEZONE_REQUIRED",
                        f"{timestamp_name} must include a timezone",
                    )
            if source.available_at > captured_at:
                issues.append(
                    IssueV1(
                        code="SOURCE_CAPTURE_ORDER",
                        severity=Severity.ERROR,
                        message=(
                            f"source {source.source_id} is not available before capture"
                        ),
                    )
                )
            if not 200 <= source.http_status < 300:
                issues.append(
                    IssueV1(
                        code="SOURCE_PROVIDER_ERROR",
                        severity=Severity.ERROR,
                        message=(
                            f"source {source.source_id} returned HTTP "
                            f"{source.http_status}"
                        ),
                    )
                )
            if source.role is SourceRole.FILING and (
                not source.accession_number or not source.form or not source.filed_at
            ):
                issues.append(
                    IssueV1(
                        code="FILING_METADATA_MISSING",
                        severity=Severity.ERROR,
                        message=(
                            f"filing source {source.source_id} lacks "
                            "accession/form/filed_at"
                        ),
                    )
                )
            content_hash = self.content_store.put(
                source.content, media_type=source.media_type
            )
            records.append(
                SourceRecordV1(
                    source_id=source.source_id,
                    uri=source.uri,
                    role=source.role,
                    available_at=source.available_at,
                    captured_at=source.captured_at or captured_at,
                    publication_at=source.publication_at,
                    http_status=source.http_status,
                    media_type=source.media_type,
                    terms_reference=legal_source.terms_reference,
                    content_hash=content_hash,
                    parser_input_hash=(
                        sec_integrity_evidence.parser_input_hash
                        if sec_integrity_evidence is not None
                        and source.source_id == "sec-filing"
                        else None
                    ),
                    parser_version=parser_version,
                    accession_number=source.accession_number,
                    form=source.form,
                    filed_at=source.filed_at,
                    filing_version=source.filing_version,
                    is_amendment=source.is_amendment,
                    amends_accession=source.amends_accession,
                    supersedes_accession=source.supersedes_accession,
                    amendment_scope=source.amendment_scope,
                    taxonomy_manifest_id=source.taxonomy_manifest_id,
                    response_headers=source.response_headers,
                    declared_size=source.declared_size,
                    received_size=(
                        source.received_size
                        if source.received_size is not None
                        else len(source.content)
                    ),
                )
            )
        records.sort(
            key=lambda record: (record.source_id, record.uri, record.content_hash)
        )
        identity_payload = {
            "identity": identity,
            "valuation_timestamp": valuation_timestamp,
            "parser_version": parser_version,
            "policy_version": policy_version,
            "captured_at": captured_at,
            "taxonomy_manifest_id": taxonomy_manifest_id,
            "sec_integrity_evidence": sec_integrity_evidence,
            "sources": [
                record.model_dump(exclude={"captured_at"}) for record in records
            ],
        }
        snapshot_id = f"snapshot-{sha256_digest(identity_payload)[:32]}"
        coverage_status = QualityStatus.VERIFIED
        if any(record.available_at > valuation_timestamp for record in records):
            coverage_status = QualityStatus.PROVISIONAL
            issues.append(
                IssueV1(
                    code="SOURCE_AFTER_VALUATION",
                    severity=Severity.WARNING,
                    message=(
                        "snapshot contains sources published after valuation "
                        "timestamp; they require point-in-time filtering"
                    ),
                )
            )
        if any(issue.severity in {Severity.ERROR, Severity.FATAL} for issue in issues):
            coverage_status = QualityStatus.ABSTAIN
        snapshot = SourceSnapshotV1(
            contract_version="fundamental.v1",
            snapshot_id=snapshot_id,
            identity=identity,
            valuation_timestamp=valuation_timestamp,
            captured_at=captured_at,
            source_records=tuple(records),
            taxonomy_manifest_id=taxonomy_manifest_id,
            parser_version=parser_version,
            policy_version=policy_version,
            coverage_status=coverage_status,
            issues=tuple(issues),
            sec_integrity_evidence=sec_integrity_evidence,
            manifest_digest=sha256_digest(
                {
                    "contract_version": "fundamental.v1",
                    "identity": identity,
                    "valuation_timestamp": valuation_timestamp,
                    "captured_at": captured_at,
                    "source_records": records,
                    "taxonomy_manifest_id": taxonomy_manifest_id,
                    "parser_version": parser_version,
                    "policy_version": policy_version,
                    "coverage_status": coverage_status,
                    "issues": issues,
                    "sec_integrity_evidence": sec_integrity_evidence,
                }
            ),
        )
        return snapshot

    def publish(self, snapshot: SourceSnapshotV1) -> None:
        """Make a prepared manifest selectable after its gates have passed."""
        is_sec_filing = any(
            record.source_id == "sec-filing" for record in snapshot.source_records
        )
        if is_sec_filing and snapshot.coverage_status is QualityStatus.ABSTAIN:
            raise SnapshotError(
                "SNAPSHOT_NOT_PUBLISHABLE", "abstained snapshots cannot be published"
            )
        if (
            snapshot.sec_integrity_evidence is not None
            and snapshot.sec_integrity_evidence.quality_decision != "pass"
        ):
            raise SnapshotError(
                "SNAPSHOT_NOT_PUBLISHABLE",
                "SEC integrity evidence does not permit snapshot publication",
            )
        if is_sec_filing:
            if snapshot.sec_integrity_evidence is None:
                raise SnapshotError(
                    "SEC_INTEGRITY_EVIDENCE_REQUIRED",
                    "SEC filing snapshots require parser-bound integrity evidence",
                )
        self.repository.publish(snapshot)


def select_available_sources(snapshot: SourceSnapshotV1) -> tuple[SourceRecordV1, ...]:
    """Select only records known at the requested valuation timestamp."""
    return tuple(
        record
        for record in snapshot.source_records
        if record.available_at <= snapshot.valuation_timestamp
    )
