"""Free public macro/reference source capture with an explicit URI allowlist."""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .snapshots import CapturedSource, LegalSource, SnapshotError, SourceRegister
from .source_capture import (
    PublicSourceRegistration,
    SourceCaptureRequest,
    SourceCaptureResponse,
)
from .public_source_catalog import default_public_source_registrations


class PublicResponsePort(Protocol):
    headers: Message

    def read(self) -> bytes: ...


def public_source_register() -> SourceRegister:
    """Return the free/public source terms register for macro/reference data."""
    return SourceRegister(
        tuple(
            # The source ID and terms are checked before any network request.
            LegalSource(
                spec.source_id,
                spec.role,
                spec.terms_reference,
                "indefinite",
            )
            for spec in (item.spec for item in default_public_source_registrations())
        )
    )


def fundamental_source_register() -> SourceRegister:
    """Return the combined SEC, macro, and public reference source register."""
    from .sec_source import sec_source_register

    entries = tuple(
        LegalSource(
            spec.source_id,
            spec.role,
            spec.terms_reference,
            "indefinite",
        )
        for spec in (item.spec for item in default_public_source_registrations())
    )
    sec_entries = sec_source_register()
    return SourceRegister(sec_entries.entries + entries)


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        return max(0.0, (target - datetime.now(timezone.utc)).total_seconds())


class PublicSourceAdapter:
    """Capture a registered public response; callers provide the snapshot policy."""

    def __init__(
        self,
        *,
        user_agent: str,
        source_register: SourceRegister | None = None,
        registrations: tuple[PublicSourceRegistration, ...] | None = None,
        max_attempts: int = 3,
        min_interval_seconds: float = 0.11,
        timeout_seconds: float = 30.0,
        opener: Callable[..., AbstractContextManager[PublicResponsePort]] = urlopen,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not user_agent.strip() or "@" not in user_agent:
            raise ValueError(
                "public requests require an identifiable User-Agent with contact"
            )
        if max_attempts < 1 or min_interval_seconds < 0 or timeout_seconds <= 0:
            raise ValueError("invalid public source request policy")
        self.user_agent = user_agent
        entries = (
            default_public_source_registrations()
            if registrations is None
            else registrations
        )
        self._registrations = {item.spec.source_id: item for item in entries}
        if len(self._registrations) != len(entries):
            raise ValueError("public source registrations repeat a source identity")
        self.source_register = source_register or SourceRegister(
            tuple(
                LegalSource(
                    item.spec.source_id,
                    item.spec.role,
                    item.spec.terms_reference,
                    "indefinite",
                )
                for item in entries
            )
        )
        self.max_attempts = max_attempts
        self.min_interval_seconds = min_interval_seconds
        self.timeout_seconds = timeout_seconds
        self._opener = opener
        self._sleep = sleep
        self._last_request_at: float | None = None

    def capture(
        self,
        source_id: str,
        uri: str,
        *,
        available_at: datetime | None = None,
        publication_at: datetime | None = None,
        captured_at: datetime | None = None,
    ) -> CapturedSource:
        registration = self._registrations.get(source_id)
        if registration is None:
            raise SnapshotError(
                "SOURCE_NOT_REGISTERED", f"source {source_id} is not registered"
            )
        spec, profile = registration.spec, registration.profile
        registered = self.source_register.require(source_id)
        if (
            registered.role != spec.role
            or registered.terms_reference != spec.terms_reference
        ):
            raise SnapshotError(
                "SOURCE_REGISTRATION_MISMATCH", "capture source and register disagree"
            )
        try:
            parsed = urlsplit(uri)
            prefix = urlsplit(spec.uri_prefix)
            port = parsed.port
            hostname = parsed.hostname
        except ValueError as error:
            raise SnapshotError(
                "SOURCE_URI_NOT_ALLOWED", "source URI is malformed"
            ) from error
        path_allowed = (
            parsed.path == prefix.path
            if spec.path_match == "exact"
            else parsed.path.startswith(prefix.path)
        )
        if (
            parsed.scheme != "https"
            or hostname != prefix.hostname
            or port is not None
            or parsed.username is not None
            or parsed.password is not None
            or not path_allowed
        ):
            raise SnapshotError(
                "SOURCE_URI_NOT_ALLOWED",
                f"URI is outside the registered {source_id} endpoint",
            )
        request = SourceCaptureRequest(
            source_id=source_id,
            uri=uri,
            terms_reference=spec.terms_reference,
            available_at=available_at,
            publication_at=publication_at,
            captured_at=captured_at,
        )
        for timestamp in (available_at, publication_at, captured_at):
            if timestamp is not None and (
                timestamp.tzinfo is None or timestamp.utcoffset() is None
            ):
                raise SnapshotError(
                    "SOURCE_TIMESTAMP_TIMEZONE_REQUIRED",
                    "source timestamps require a timezone",
                )
        profile.validate_request(request)
        payload, status, media_type, retrieved_at = self._request(uri)
        timing = profile.resolve_capture(
            request, SourceCaptureResponse(payload, media_type, retrieved_at)
        )
        for timestamp in (
            timing.available_at,
            timing.publication_at,
            timing.captured_at,
        ):
            if timestamp is not None and (
                timestamp.tzinfo is None or timestamp.utcoffset() is None
            ):
                raise SnapshotError(
                    "SOURCE_TIMESTAMP_TIMEZONE_REQUIRED",
                    "source timestamps require a timezone",
                )
        if timing.captured_at is not None and timing.captured_at > retrieved_at:
            raise SnapshotError(
                "SOURCE_CAPTURE_TIME_MISMATCH",
                "capture time exceeds service retrieval time",
            )
        if timing.available_at > (timing.captured_at or retrieved_at) or (
            timing.publication_at is not None
            and timing.publication_at > timing.available_at
        ):
            raise SnapshotError(
                "SOURCE_TIMESTAMP_ORDER_INVALID", "source timestamps are inconsistent"
            )
        return CapturedSource(
            source_id=source_id,
            uri=uri,
            role=spec.role,
            content=payload,
            media_type=media_type or "application/octet-stream",
            http_status=status,
            available_at=timing.available_at,
            captured_at=timing.captured_at,
            publication_at=timing.publication_at,
        )

    def _request(self, uri: str) -> tuple[bytes, int, str, datetime]:
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            if self._last_request_at is not None:
                elapsed = time.monotonic() - self._last_request_at
                if elapsed < self.min_interval_seconds:
                    self._sleep(self.min_interval_seconds - elapsed)
            request = Request(
                uri,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": (
                        "text/csv, application/json, application/xml, text/plain, */*"
                    ),
                },
            )
            self._last_request_at = time.monotonic()
            try:
                with self._opener(request, timeout=self.timeout_seconds) as response:
                    payload = response.read()
                    media_type = response.headers.get_content_type()
                    return (
                        payload,
                        int(getattr(response, "status", 200)),
                        media_type,
                        datetime.now(timezone.utc),
                    )
            except HTTPError as error:
                last_error = error
                retryable = error.code == 429 or 500 <= error.code < 600
                if not retryable or attempt + 1 >= self.max_attempts:
                    code = (
                        "SOURCE_RATE_LIMITED"
                        if error.code == 429
                        else "SOURCE_UNAVAILABLE"
                    )
                    raise SnapshotError(
                        code,
                        f"public source returned HTTP {error.code}",
                        retryable=retryable,
                    ) from error
                self._sleep(
                    _retry_after(error.headers.get("Retry-After")) or 2**attempt
                )
            except (URLError, TimeoutError, OSError) as error:
                last_error = error
                if attempt + 1 >= self.max_attempts:
                    raise SnapshotError(
                        "SOURCE_UNAVAILABLE",
                        "public source failed after retries",
                        retryable=True,
                    ) from error
                self._sleep(2**attempt)
        raise SnapshotError(
            "SOURCE_UNAVAILABLE", "public source failed", retryable=True
        ) from last_error
