"""Persist issuer/date annual discovery and resume already captured SEC originals."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import Field, model_validator

from .annual_discovery import (
    AnnualDiscoveryRequestV1,
    AnnualSelectionV1,
    decode_history,
    decode_submissions,
    required_history_files,
    select_original_annuals,
)
from .command_artifacts import EvidenceArtifactStore
from .contracts import StrictModel
from .replay import ArtifactPublicationV1
from .sec_capture import (
    RetainedSecSourceAdapter,
    SecCaptureStore,
    SecResponseReceiptV1,
    SecSubmissionsCaptureScopeV1,
)
from .sec_source import SecRequestTransportPort, SecSourceError
from .sec_submissions import SecRecentFilingsV1
from .serialization import canonical_bytes, sha256_digest
from .snapshots import ContentAddressedStore, SnapshotError


class AnnualDiscoveryArtifacts(EvidenceArtifactStore, SecCaptureStore, Protocol):
    pass


class AnnualSourceCaptureV1(StrictModel):
    filename: str = Field(pattern=r"^CIK[0-9]{10}(?:-submissions-[0-9]{3})?\.json$")
    receipt: SecResponseReceiptV1 | None
    issue_codes: tuple[str, ...] = ()
    retryable: bool = False

    @model_validator(mode="after")
    def capture_outcome(self) -> AnnualSourceCaptureV1:
        if self.issue_codes != tuple(sorted(set(self.issue_codes))):
            raise ValueError("annual capture issues must be canonical")
        if (self.receipt is None or self.retryable) and not self.issue_codes:
            raise ValueError("unsuccessful annual capture requires a reason")
        return self


class AnnualDiscoveryEvidenceV1(StrictModel):
    protocol: Literal["sec-original-annual-discovery-evidence-v1"] = (
        "sec-original-annual-discovery-evidence-v1"
    )
    request: AnnualDiscoveryRequestV1
    sources: tuple[AnnualSourceCaptureV1, ...]
    selection: AnnualSelectionV1

    @property
    def retryable(self) -> bool:
        return any(source.retryable for source in self.sources)

    @property
    def digest(self) -> str:
        return sha256_digest(self)

    @property
    def artifact_id(self) -> str:
        if self.retryable:
            return f"annual-discovery-attempt:{self.digest}"
        return f"annual-discovery:{self.request.digest}"

    @property
    def dependencies(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    self.request.digest,
                    *(
                        digest
                        for source in self.sources
                        if source.receipt is not None
                        for digest in (
                            sha256_digest(source.receipt),
                            source.receipt.content_hash,
                        )
                    ),
                }
            )
        )


class AnnualDiscovery:
    def __init__(
        self,
        *,
        provider: SecRequestTransportPort,
        artifacts: AnnualDiscoveryArtifacts,
        content: ContentAddressedStore,
        capture_lock: Callable[[str], AbstractContextManager[None]],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._provider = provider
        self._artifacts = artifacts
        self._content = content
        self._capture_lock = capture_lock
        self._clock = clock

    def _adapter(self, request: AnnualDiscoveryRequestV1) -> RetainedSecSourceAdapter:
        return RetainedSecSourceAdapter(
            self._provider,
            scope=SecSubmissionsCaptureScopeV1(
                cik=request.cik, valuation_timestamp=request.valuation_timestamp
            ),
            receipts=self._artifacts,
            content=self._content,
            capture_lock=self._capture_lock,
        )

    @staticmethod
    def _uri(filename: str) -> str:
        return f"https://data.sec.gov/submissions/{filename}"

    def _capture(
        self,
        adapter: RetainedSecSourceAdapter,
        filename: str,
        *,
        deadline_at: datetime,
    ) -> AnnualSourceCaptureV1:
        codes: tuple[str, ...] = ()
        retryable = False
        try:
            if "-submissions-" in filename:
                adapter.capture_submission_history(
                    cik=adapter.scope.cik,
                    filename=filename,
                    deadline_at=deadline_at,
                )
            else:
                adapter.capture_submissions(adapter.scope.cik, deadline_at=deadline_at)
        except SecSourceError as error:
            codes = (error.code,)
            retryable = error.retryable
        # Malformed JSON still has a durable original response, captured before
        # adapter decoding. Transport failures have no successful receipt.
        receipt = adapter.read_retained_response(self._uri(filename))
        return AnnualSourceCaptureV1(
            filename=filename,
            receipt=receipt,
            issue_codes=codes,
            retryable=retryable,
        )

    def _payload(self, source: AnnualSourceCaptureV1) -> bytes:
        if source.receipt is None:
            raise ValueError("annual source has no captured response")
        return self._content.get(
            source.receipt.content_hash,
            media_type=source.receipt.media_type or "application/octet-stream",
        )

    def _history_names(
        self, request: AnnualDiscoveryRequestV1, recent: AnnualSourceCaptureV1
    ) -> tuple[str, ...]:
        if recent.receipt is None:
            return ()
        try:
            source = decode_submissions(self._payload(recent), request.cik)
            return required_history_files(source, request)
        except ValueError:
            return ()

    def _assess(
        self,
        request: AnnualDiscoveryRequestV1,
        sources: tuple[AnnualSourceCaptureV1, ...],
    ) -> AnnualSelectionV1:
        expected = (
            f"CIK{request.cik}.json",
            *self._history_names(request, sources[0]),
        )
        if tuple(source.filename for source in sources) != expected:
            raise ValueError(
                "annual discovery must retain every required page in order"
            )
        issues = {code for source in sources for code in source.issue_codes}
        rows: list[tuple[str, SecRecentFilingsV1]] = []
        for index, source in enumerate(sources):
            if source.receipt is None:
                continue
            payload = self._payload(source)
            try:
                if index == 0:
                    submissions = decode_submissions(payload, request.cik)
                    decoded = submissions.filings.recent
                else:
                    decoded = decode_history(payload)
            except ValueError:
                issues.add(
                    "ANNUAL_SUBMISSIONS_INVALID"
                    if index == 0
                    else "ANNUAL_HISTORY_INVALID"
                )
                continue
            rows.append((source.receipt.content_hash, decoded))
            if index == 0:
                try:
                    required_history_files(submissions, request)
                except ValueError:
                    issues.add("ANNUAL_HISTORY_REFERENCES_INVALID")
        selection = select_original_annuals(request, rows)
        issues.update(selection.issue_codes)
        return AnnualSelectionV1(
            selected=() if issues else selection.selected,
            dispositions=selection.dispositions,
            issue_codes=tuple(sorted(issues)),
        )

    def read(self, artifact_id: str) -> AnnualDiscoveryEvidenceV1:
        record = self._artifacts.get(artifact_id)
        raw = self._artifacts.read(artifact_id)
        try:
            evidence = AnnualDiscoveryEvidenceV1.model_validate_json(raw)
            if (
                record.status != "valid"
                or record.retention != "evidence"
                or record.media_type != "application/json"
                or raw != canonical_bytes(evidence)
                or hashlib.sha256(raw).hexdigest() != record.content_hash
                or record.dependency_hashes != evidence.dependencies
                or evidence.artifact_id != artifact_id
                or not evidence.sources
            ):
                raise ValueError("annual evidence differs from its retained identity")
            adapter = self._adapter(evidence.request)
            for source in evidence.sources:
                # A transient attempt remains a record of that failure even
                # after a later attempt successfully captures the missing page.
                if source.receipt is not None:
                    retained = adapter.read_retained_response(
                        self._uri(source.filename)
                    )
                    if source.receipt != retained:
                        raise ValueError(
                            "annual capture differs from its retained response"
                        )
            if evidence.selection != self._assess(evidence.request, evidence.sources):
                raise ValueError("annual selection cannot be reproduced from originals")
            request_id = f"annual-discovery-request:{evidence.request.digest}"
            request_record = self._artifacts.get(request_id)
            if (
                request_record.status != "valid"
                or request_record.retention != "evidence"
                or request_record.media_type != "application/json"
                or request_record.dependency_hashes
                or request_record.content_hash != evidence.request.digest
                or self._artifacts.read(request_id) != canonical_bytes(evidence.request)
            ):
                raise ValueError("annual discovery request evidence changed")
        except ValueError as error:
            raise SnapshotError(
                "ANNUAL_DISCOVERY_INVALID",
                "annual discovery evidence failed verification",
            ) from error
        return evidence

    def execute(
        self, request: AnnualDiscoveryRequestV1, *, deadline_at: datetime
    ) -> tuple[AnnualDiscoveryEvidenceV1, ArtifactPublicationV1]:
        request = AnnualDiscoveryRequestV1.model_validate_json(canonical_bytes(request))
        with self._capture_lock(sha256_digest(("annual-discovery", request.digest))):
            now = self._clock()
            if now.tzinfo is None or deadline_at.tzinfo is None or deadline_at <= now:
                raise SecSourceError(
                    "REQUEST_DEADLINE_EXCEEDED",
                    "annual discovery deadline expired",
                    retryable=True,
                )
            artifact_id = f"annual-discovery:{request.digest}"
            try:
                record = self._artifacts.get(artifact_id)
            except SnapshotError as error:
                if error.code != "ARTIFACT_NOT_FOUND":
                    raise
            else:
                evidence = self.read(artifact_id)
                if evidence.request != request:
                    raise SnapshotError(
                        "ANNUAL_DISCOVERY_INVALID", "annual request identity differs"
                    )
                return evidence, ArtifactPublicationV1(artifact=record, wrote=False)
            if request.valuation_timestamp > now:
                raise SecSourceError(
                    "ANNUAL_VALUATION_TIME_INVALID",
                    "annual discovery cannot select filings for a future valuation",
                )
            adapter = self._adapter(request)
            recent = self._capture(
                adapter, f"CIK{request.cik}.json", deadline_at=deadline_at
            )
            sources = (
                recent,
                *(
                    self._capture(adapter, filename, deadline_at=deadline_at)
                    for filename in self._history_names(request, recent)
                ),
            )
            evidence = AnnualDiscoveryEvidenceV1(
                request=request,
                sources=sources,
                selection=self._assess(request, sources),
            )
            self._artifacts.put_with_receipt(
                f"annual-discovery-request:{request.digest}", request
            )
            publication = self._artifacts.put_with_receipt(
                evidence.artifact_id, evidence, evidence.dependencies
            )
            return evidence, publication
