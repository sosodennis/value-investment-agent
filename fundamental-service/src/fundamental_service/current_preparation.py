"""Freeze a current valuation cutoff after retaining required public originals."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal, Protocol

from pydantic import model_validator

from .contracts import StrictModel
from .source_plan_contracts import SOURCE_PREPARATION_PLAN, SourcePreparationPlan
from .public_acquisition import (
    CURRENT_REQUEST_WINDOW,
    PublicSourceAcquisitionEvidenceV1,
    PublicSourceAcquisitionRequestV1,
    PublicSourceCutoffV1,
)
from .replay import ArtifactPublicationV1, ArtifactRecordV1
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError


class CurrentSourcePreparationRequestV1(StrictModel):
    protocol: Literal["current-source-preparation-v1"] = "current-source-preparation-v1"
    template: SourcePreparationPlan

    @model_validator(mode="after")
    def current_template(self) -> CurrentSourcePreparationRequestV1:
        if (
            not self.template.public_sources
            or self.template.public_source_cutoff is not None
        ):
            raise ValueError(
                "current preparation requires unfrozen public source requests"
            )
        return self

    @property
    def requested_at(self) -> datetime:
        return self.template.ingestions[0].valuation_timestamp

    @property
    def digest(self) -> str:
        return sha256_digest(self)


def _freeze_plan(
    request: CurrentSourcePreparationRequestV1,
    captures: tuple[PublicSourceAcquisitionEvidenceV1, ...],
) -> SourcePreparationPlan:
    cutoff = PublicSourceCutoffV1(
        requested_at=request.requested_at,
        valuation_at=max(
            (
                request.requested_at,
                *(item.source.captured_at for item in captures if item.source),
            )
        ),
        captures=captures,
    )
    payload = request.template.model_dump()
    payload["ingestions"] = tuple(
        {**item.model_dump(), "valuation_timestamp": cutoff.valuation_at}
        for item in request.template.ingestions
    )
    payload["source_admissions"] = tuple(
        {**item.model_dump(), "valuation_at": cutoff.valuation_at}
        for item in request.template.source_admissions
    )
    if request.template.issuer_market_policy is not None:
        payload["issuer_market_policy"] = request.template.issuer_market_policy.at(
            cutoff.valuation_at
        )
    payload["public_source_cutoff"] = cutoff
    return SOURCE_PREPARATION_PLAN.validate_python(payload)


class CurrentSourcePreparationSelectionV1(StrictModel):
    protocol: Literal["current-source-preparation-selection-v1"] = (
        "current-source-preparation-selection-v1"
    )
    request: CurrentSourcePreparationRequestV1
    captures: tuple[PublicSourceAcquisitionEvidenceV1, ...]
    plan: SourcePreparationPlan | None
    issue_codes: tuple[str, ...]
    retryable: bool = False

    @model_validator(mode="after")
    def selection_matches_sources(self) -> CurrentSourcePreparationSelectionV1:
        if (
            tuple(item.request for item in self.captures)
            != self.request.template.public_sources
        ):
            raise ValueError("current preparation must retain every source request")
        if self.issue_codes != tuple(sorted(set(self.issue_codes))):
            raise ValueError("current preparation diagnostics must be canonical")
        if self.plan is not None:
            if (
                self.issue_codes
                or self.retryable
                or self.plan != _freeze_plan(self.request, self.captures)
            ):
                raise ValueError(
                    "current plan differs from its exact captures and template"
                )
        elif not self.issue_codes:
            raise ValueError("unselected current plan requires retained issues")
        if self.retryable != any(item.retryable for item in self.captures):
            raise ValueError("current preparation retryability differs from captures")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)

    @property
    def artifact_id(self) -> str:
        if self.retryable:
            return f"current-source-preparation-attempt:{self.digest}"
        return f"current-source-preparation:{self.request.digest}"

    @property
    def dependencies(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    self.request.digest,
                    *(item.digest for item in self.captures),
                    *((self.plan.digest,) if self.plan is not None else ()),
                }
            )
        )


class CurrentSourcePreparationPublicationV1(ArtifactPublicationV1):
    """Command receipt retaining the capture cutoff and the actual plan used."""

    current_selection: CurrentSourcePreparationSelectionV1
    current_selection_publication: ArtifactPublicationV1

    @model_validator(mode="after")
    def exact_selection_receipt(self) -> CurrentSourcePreparationPublicationV1:
        selection = self.current_selection
        record = self.current_selection_publication.artifact
        if (
            record.artifact_id != selection.artifact_id
            or record.content_hash != selection.digest
            or record.dependency_hashes != selection.dependencies
            or record.status != "valid"
            or record.retention != "evidence"
            or record.media_type != "application/json"
        ):
            raise ValueError("current command selection receipt differs from evidence")
        if selection.plan is None:
            if (
                self.artifact != record
                or self.wrote != self.current_selection_publication.wrote
            ):
                raise ValueError("blocked current command must retain its selection")
        elif (
            selection.plan.digest not in self.artifact.dependency_hashes
            or self.artifact.artifact_id
            != f"source-preparation:{self.artifact.content_hash}"
            or self.artifact.status != "valid"
            or self.artifact.retention != "evidence"
            or self.artifact.media_type != "application/json"
        ):
            raise ValueError("current preparation receipt must bind its effective plan")
        return self


class CurrentPublicAcquisitionPort(Protocol):
    def validate_request(self, request: PublicSourceAcquisitionRequestV1) -> None: ...

    def execute(
        self, request: PublicSourceAcquisitionRequestV1
    ) -> ArtifactPublicationV1: ...

    def read(self, artifact_id: str) -> PublicSourceAcquisitionEvidenceV1: ...


class CurrentPreparationArtifactPort(Protocol):
    def get(self, artifact_id: str) -> ArtifactRecordV1: ...

    def read(self, artifact_id: str) -> bytes: ...

    def put_with_receipt(
        self, artifact_id: str, value: object, dependency_hashes: tuple[str, ...] = ()
    ) -> ArtifactPublicationV1: ...


class CurrentSourcePreparation:
    def __init__(
        self,
        *,
        acquisitions: CurrentPublicAcquisitionPort,
        artifacts: CurrentPreparationArtifactPort,
        selection_lock: Callable[[str], AbstractContextManager[None]],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._acquisitions = acquisitions
        self._artifacts = artifacts
        self._selection_lock = selection_lock
        self._clock = clock

    def read(self, artifact_id: str) -> CurrentSourcePreparationSelectionV1:
        record = self._artifacts.get(artifact_id)
        raw = self._artifacts.read(artifact_id)
        try:
            selected = CurrentSourcePreparationSelectionV1.model_validate_json(raw)
        except ValueError as error:
            raise SnapshotError(
                "CURRENT_SELECTION_INVALID", "current selection violates its contract"
            ) from error
        if (
            record.status != "valid"
            or record.retention != "evidence"
            or record.media_type != "application/json"
            or canonical_bytes(selected) != raw
            or sha256(raw).hexdigest() != record.content_hash
            or record.dependency_hashes != selected.dependencies
            or selected.artifact_id != artifact_id
        ):
            raise SnapshotError(
                "CURRENT_SELECTION_INVALID",
                "current selection differs from its identity",
            )
        for item in selected.captures:
            self._acquisitions.validate_request(item.request)
            if self._acquisitions.read(item.artifact_id) != item:
                raise SnapshotError(
                    "CURRENT_CAPTURE_MISMATCH",
                    "current selection capture differs from retained evidence",
                )
        expected: list[tuple[str, object]] = [
            (f"current-source-request:{selected.request.digest}", selected.request)
        ]
        if selected.plan is not None:
            expected.append(
                (f"source-preparation-plan:{selected.plan.digest}", selected.plan)
            )
        for dependency_id, value in expected:
            dependency = self._artifacts.get(dependency_id)
            if (
                dependency.status != "valid"
                or dependency.retention != "evidence"
                or dependency.media_type != "application/json"
                or dependency.dependency_hashes
                or dependency.content_hash != sha256_digest(value)
                or self._artifacts.read(dependency_id) != canonical_bytes(value)
            ):
                raise SnapshotError(
                    "CURRENT_SELECTION_INVALID", "current selection dependency changed"
                )
        return selected

    def execute(
        self,
        request: CurrentSourcePreparationRequestV1,
        *,
        deadline_at: datetime,
    ) -> tuple[CurrentSourcePreparationSelectionV1, ArtifactPublicationV1]:
        with self._selection_lock(
            sha256_digest(("current-preparation", request.digest))
        ):
            now = self._clock()
            if now.tzinfo is None or deadline_at.tzinfo is None or deadline_at <= now:
                raise SnapshotError(
                    "REQUEST_DEADLINE_EXCEEDED",
                    "current preparation deadline expired",
                    retryable=True,
                )
            artifact_id = f"current-source-preparation:{request.digest}"
            try:
                record = self._artifacts.get(artifact_id)
            except SnapshotError as error:
                if error.code != "ARTIFACT_NOT_FOUND":
                    raise
            else:
                selected = self.read(artifact_id)
                if selected.request != request:
                    raise SnapshotError(
                        "CURRENT_SELECTION_INVALID",
                        "current request differs from retained identity",
                    )
                return selected, ArtifactPublicationV1(artifact=record, wrote=False)
            if request.requested_at > now:
                raise SnapshotError(
                    "CURRENT_REQUEST_TIME_INVALID",
                    "new current requests require a recent nonfuture timestamp",
                )
            resume_only = now - request.requested_at > CURRENT_REQUEST_WINDOW
            captures = []
            for source in request.template.public_sources:
                if self._clock() >= deadline_at:
                    raise SnapshotError(
                        "REQUEST_DEADLINE_EXCEEDED",
                        "current acquisition deadline expired",
                        retryable=True,
                    )
                if resume_only:
                    self._acquisitions.validate_request(source)
                    try:
                        capture = self._acquisitions.read(
                            f"public-source-acquisition:{source.digest}"
                        )
                    except SnapshotError as error:
                        if error.code != "ARTIFACT_NOT_FOUND":
                            raise
                        raise SnapshotError(
                            "CURRENT_REQUEST_TIME_INVALID",
                            "expired current requests can only resume completed captures",
                        ) from error
                else:
                    published = self._acquisitions.execute(source)
                    capture = self._acquisitions.read(published.artifact.artifact_id)
                captures.append(capture)
            final_time = self._clock()
            if final_time.tzinfo is None or final_time < now:
                raise SnapshotError(
                    "CURRENT_CAPTURE_TIME_INVALID",
                    "current capture clock moved backwards",
                )
            codes = {
                code
                for item in captures
                if item.status == "failed"
                for code in item.issue_codes
            }
            if any(
                item.source is not None
                and not (
                    request.requested_at - CURRENT_REQUEST_WINDOW
                    <= item.source.captured_at
                    <= min(final_time, request.requested_at + CURRENT_REQUEST_WINDOW)
                )
                for item in captures
            ):
                codes.add("CURRENT_CAPTURE_TIME_INVALID")
            selected = CurrentSourcePreparationSelectionV1(
                request=request,
                captures=tuple(captures),
                plan=None if codes else _freeze_plan(request, tuple(captures)),
                issue_codes=tuple(sorted(codes)),
                retryable=any(item.retryable for item in captures),
            )
            self._artifacts.put_with_receipt(
                f"current-source-request:{request.digest}", request
            )
            if selected.plan is not None:
                self._artifacts.put_with_receipt(
                    f"source-preparation-plan:{selected.plan.digest}",
                    selected.plan,
                    # Plan identity is shared with the ordinary runner.
                )
            publication = self._artifacts.put_with_receipt(
                selected.artifact_id,
                selected,
                selected.dependencies,
            )
            return selected, publication
