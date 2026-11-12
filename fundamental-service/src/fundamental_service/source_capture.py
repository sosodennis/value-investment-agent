"""Pure, injectable public-source request and capture profiles."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from urllib.parse import urlsplit

from .contracts import SourceRole
from .macro_series import MacroSeriesProviderPort, reproduce_macro_vintage
from .snapshots import SnapshotError
from .source_evidence import RetainedSourceV1


@dataclass(frozen=True)
class SourceCaptureRequest:
    source_id: str
    uri: str
    terms_reference: str
    available_at: datetime | None = None
    publication_at: datetime | None = None
    captured_at: datetime | None = None


@dataclass(frozen=True)
class SourceCaptureResponse:
    content: bytes
    media_type: str
    retrieved_at: datetime


@dataclass(frozen=True)
class SourceCaptureTimes:
    available_at: datetime
    publication_at: datetime | None
    captured_at: datetime | None


class PublicSourceCaptureProfilePort(Protocol):
    """Validate before HTTP, then resolve time from the actual response."""

    def validate_request(self, request: SourceCaptureRequest) -> None: ...

    def resolve_capture(
        self, request: SourceCaptureRequest, response: SourceCaptureResponse
    ) -> SourceCaptureTimes: ...


@dataclass(frozen=True)
class PublicSourceSpec:
    source_id: str
    role: SourceRole
    uri_prefix: str
    terms_reference: str
    path_match: Literal["prefix", "exact"] = "prefix"

    def __post_init__(self) -> None:
        uri = urlsplit(self.uri_prefix)
        if (
            not self.source_id.strip()
            or not self.terms_reference.strip()
            or self.path_match not in {"exact", "prefix"}
            or uri.scheme != "https"
            or not uri.hostname
            or uri.port is not None
            or uri.username is not None
            or uri.password is not None
            or uri.query
            or uri.fragment
        ):
            raise ValueError("invalid public source registration boundary")


@dataclass(frozen=True)
class PublicSourceRegistration:
    spec: PublicSourceSpec
    profile: PublicSourceCaptureProfilePort

    def __post_init__(self) -> None:
        if not callable(
            getattr(self.profile, "validate_request", None)
        ) or not callable(getattr(self.profile, "resolve_capture", None)):
            raise ValueError("public source registration requires a capture profile")


def _reject_timestamp_overrides(request: SourceCaptureRequest) -> None:
    if any(
        value is not None
        for value in (request.available_at, request.publication_at, request.captured_at)
    ):
        raise SnapshotError(
            "SOURCE_AVAILABILITY_UNVERIFIED",
            "source timestamps require service capture and retained evidence",
        )


def _validate_payload(
    response: SourceCaptureResponse, *, require_nonempty: bool
) -> None:
    if require_nonempty and not response.content.strip():
        raise SnapshotError(
            "SOURCE_PAYLOAD_INVALID", "public source returned empty bytes"
        )
    if "json" in response.media_type:
        try:
            json.loads(response.content)
        except (ValueError, UnicodeError) as error:
            raise SnapshotError(
                "SOURCE_PAYLOAD_INVALID", "public source JSON is invalid"
            ) from error


@dataclass(frozen=True)
class ProvidedAvailabilityCaptureProfile:
    """Legacy registered sources whose caller supplies publication evidence."""

    require_nonempty: bool = False

    def validate_request(self, request: SourceCaptureRequest) -> None:
        if request.available_at is None:
            raise SnapshotError(
                "SOURCE_AVAILABILITY_REQUIRED",
                "source capture requires publisher availability metadata",
            )

    def resolve_capture(
        self, request: SourceCaptureRequest, response: SourceCaptureResponse
    ) -> SourceCaptureTimes:
        assert request.available_at is not None
        _validate_payload(response, require_nonempty=self.require_nonempty)
        return SourceCaptureTimes(
            available_at=request.available_at,
            publication_at=request.publication_at or request.available_at,
            captured_at=request.captured_at,
        )


@dataclass(frozen=True)
class RetainedAvailabilityCaptureProfile:
    """Retain actual capture time; paired/table reproduction happens separately."""

    validate_uri: Callable[[str], None]
    require_nonempty: bool = False

    def validate_request(self, request: SourceCaptureRequest) -> None:
        self.validate_uri(request.uri)
        _reject_timestamp_overrides(request)

    def resolve_capture(
        self, request: SourceCaptureRequest, response: SourceCaptureResponse
    ) -> SourceCaptureTimes:
        _validate_payload(response, require_nonempty=self.require_nonempty)
        return SourceCaptureTimes(
            available_at=response.retrieved_at,
            publication_at=None,
            captured_at=response.retrieved_at,
        )


@dataclass(frozen=True)
class ReproducedMacroCaptureProfile:
    """Reproduce a configured canonical series through its injected provider."""

    provider: MacroSeriesProviderPort
    series_id: str
    source_version: str
    validate_uri: Callable[[str], None]

    def validate_request(self, request: SourceCaptureRequest) -> None:
        self.validate_uri(request.uri)
        _reject_timestamp_overrides(request)
        if not self.provider.supports(self.series_id):
            raise SnapshotError(
                "SOURCE_PROFILE_UNSUPPORTED",
                "capture provider does not support the series",
            )

    def resolve_capture(
        self, request: SourceCaptureRequest, response: SourceCaptureResponse
    ) -> SourceCaptureTimes:
        try:
            vintage = reproduce_macro_vintage(
                self.provider,
                series_id=self.series_id,
                sources=(
                    RetainedSourceV1(
                        source_id=request.source_id,
                        uri=request.uri,
                        source_version=self.source_version,
                        terms_reference=request.terms_reference,
                        content=response.content,
                        captured_at=response.retrieved_at,
                    ),
                ),
            )
        except ValueError as error:
            raise SnapshotError(
                "SOURCE_REPRODUCTION_FAILED",
                "capture provider did not reproduce its source",
            ) from error
        if vintage.captured_at != response.retrieved_at:
            raise SnapshotError(
                "SOURCE_CAPTURE_TIME_MISMATCH",
                "provider capture time differs from service retrieval time",
            )
        return SourceCaptureTimes(
            available_at=vintage.available_at,
            publication_at=None,
            captured_at=response.retrieved_at,
        )
