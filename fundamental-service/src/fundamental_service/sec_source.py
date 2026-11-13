"""Free SEC EDGAR source acquisition with explicit offline/retry boundaries."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from email.message import Message
from email.utils import parsedate_to_datetime
from http.client import IncompleteRead
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .contracts import SourceRole
from .snapshots import CapturedSource, LegalSource, SnapshotError, SourceRegister

SEC_TERMS = "https://www.sec.gov/submit-filings/about-edgar-filer-access"
_RETAINED_RESPONSE_HEADERS = frozenset(
    {
        "cache-control",
        "content-encoding",
        "content-length",
        "content-type",
        "date",
        "etag",
        "last-modified",
        "x-akamai-transformed",
    }
)


class SecSourceError(SnapshotError):
    """Stable failures from the free SEC source boundary."""


@dataclass(frozen=True)
class SecRequestPolicy:
    user_agent: str
    min_interval_seconds: float = 0.11
    max_attempts: int = 3
    timeout_seconds: float = 30.0
    max_response_bytes: int = 24_000_000
    base_url: str = "https://data.sec.gov"

    def __post_init__(self) -> None:
        if not self.user_agent.strip() or "@" not in self.user_agent:
            raise ValueError(
                "SEC requests require an identifiable User-Agent with contact"
            )
        if (
            self.min_interval_seconds < 0
            or self.max_attempts < 1
            or self.timeout_seconds <= 0
            or self.max_response_bytes < 1
        ):
            raise ValueError("invalid SEC request policy")
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "data.sec.gov"
            or parsed.path.rstrip("/")
        ):
            raise ValueError("SEC base_url must be https://data.sec.gov")


@dataclass(frozen=True)
class _SecResponse:
    content: bytes
    http_status: int
    media_type: str
    available_at: datetime
    response_headers: tuple[tuple[str, str], ...]
    declared_size: int | None


class SecRequestTransportPort(Protocol):
    """HTTP implementation injected beneath SEC URL and response policies."""

    policy: SecRequestPolicy

    def _request(
        self, uri: str, *, deadline_at: datetime | None = None
    ) -> _SecResponse: ...


class SecSourceCapturePort(SecRequestTransportPort, Protocol):
    """SEC evidence capture surface consumed by acquisition and ingestion."""

    policy: SecRequestPolicy

    def capture_company_facts(
        self,
        cik: str,
        *,
        captured_at: datetime | None = None,
        deadline_at: datetime | None = None,
    ) -> CapturedSource: ...

    def capture_company_tickers(
        self, *, deadline_at: datetime | None = None
    ) -> CapturedSource: ...

    def capture_submissions(
        self,
        cik: str,
        *,
        captured_at: datetime | None = None,
        deadline_at: datetime | None = None,
    ) -> CapturedSource: ...

    def capture_filing_index(
        self,
        *,
        cik: str,
        accession_number: str,
        deadline_at: datetime | None = None,
        filed_at: datetime | None = None,
        captured_at: datetime | None = None,
    ) -> CapturedSource: ...

    def capture_filing_submission(
        self,
        *,
        cik: str,
        accession_number: str,
        filed_at: datetime,
        captured_at: datetime | None = None,
        form: str = "10-K",
        is_amendment: bool = False,
        amends_accession: str | None = None,
        amendment_scope: str | None = None,
        accepted_at: datetime | None = None,
        filing_date: date | None = None,
        deadline_at: datetime | None = None,
    ) -> CapturedSource: ...

    def capture_filing(
        self,
        *,
        cik: str,
        accession_number: str,
        primary_document: str,
        filed_at: datetime,
        captured_at: datetime | None = None,
        form: str = "10-K",
        is_amendment: bool = False,
        amends_accession: str | None = None,
        amendment_scope: str | None = None,
        accepted_at: datetime | None = None,
        filing_date: date | None = None,
        deadline_at: datetime | None = None,
    ) -> CapturedSource: ...

    def capture_filing_archive(
        self,
        *,
        cik: str,
        accession_number: str,
        filed_at: datetime,
        filename: str | None = None,
        captured_at: datetime | None = None,
        form: str = "10-K",
        is_amendment: bool = False,
        amends_accession: str | None = None,
        amendment_scope: str | None = None,
        accepted_at: datetime | None = None,
        deadline_at: datetime | None = None,
    ) -> CapturedSource: ...

    def capture_filing_resource(
        self,
        *,
        cik: str,
        accession_number: str,
        filename: str,
        role: SourceRole = SourceRole.TAXONOMY,
        filed_at: datetime | None = None,
        filing_date: date | None = None,
        taxonomy_manifest_id: str | None = None,
        form: str = "XBRL-DTS",
        is_amendment: bool = False,
        amends_accession: str | None = None,
        amendment_scope: str | None = None,
        captured_at: datetime | None = None,
        deadline_at: datetime | None = None,
    ) -> CapturedSource: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    """Keep provider redirects visible to the SEC allowlist boundary."""

    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


_SEC_OPENER = build_opener(_NoRedirectHandler())


class _SecHttpResponse(Protocol):
    headers: Message
    status: int

    def read(self, amt: int | None = None) -> bytes: ...


def _open_sec(
    request: Request, *, timeout: float
) -> AbstractContextManager[_SecHttpResponse]:
    return _SEC_OPENER.open(request, timeout=timeout)


def sec_source_register() -> SourceRegister:
    """Return the allowlist for the public SEC JSON and filing resources."""
    return SourceRegister(
        (
            LegalSource("sec-companyfacts", SourceRole.FACTS, SEC_TERMS, "indefinite"),
            LegalSource(
                "sec-company-tickers", SourceRole.ACQUISITION, SEC_TERMS, "indefinite"
            ),
            LegalSource(
                "sec-submissions", SourceRole.ACQUISITION, SEC_TERMS, "indefinite"
            ),
            LegalSource(
                "sec-filing-index", SourceRole.REFERENCE, SEC_TERMS, "indefinite"
            ),
            LegalSource("sec-filing", SourceRole.FILING, SEC_TERMS, "indefinite"),
            LegalSource(
                "sec-supplemental-filing", SourceRole.FILING, SEC_TERMS, "indefinite"
            ),
            LegalSource(
                "sec-supplemental-filing-index",
                SourceRole.REFERENCE,
                SEC_TERMS,
                "indefinite",
            ),
            LegalSource(
                "sec-filing-submission", SourceRole.FILING, SEC_TERMS, "indefinite"
            ),
            LegalSource(
                "sec-filing-archive", SourceRole.FILING, SEC_TERMS, "indefinite"
            ),
            LegalSource("sec-taxonomy", SourceRole.TAXONOMY, SEC_TERMS, "indefinite"),
        )
    )


def _parse_retry_after(value: str | None) -> float | None:
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


class SecEdgarSourceAdapter:
    """Capture SEC responses as immutable source records.

    The adapter is the only component allowed to perform provider I/O. The
    calculation and replay planes receive captured bytes and never call it.
    """

    def __init__(
        self,
        policy: SecRequestPolicy,
        *,
        opener: Callable[..., AbstractContextManager[_SecHttpResponse]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        request_slot: Callable[[float], float] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.policy = policy
        self._opener = opener or _open_sec
        self._sleep = sleep
        self._request_slot = request_slot
        self._clock = clock
        self._last_request_at: float | None = None

    def _request(
        self, uri: str, *, deadline_at: datetime | None = None
    ) -> _SecResponse:
        last_error: Exception | None = None
        for attempt in range(self.policy.max_attempts):
            remaining = (
                None
                if deadline_at is None
                else (deadline_at - datetime.now(timezone.utc)).total_seconds()
            )
            if remaining is not None and remaining <= 0:
                raise SecSourceError(
                    "REQUEST_DEADLINE_EXCEEDED",
                    "SEC acquisition deadline expired",
                    retryable=True,
                )
            if self._request_slot is not None:
                delay = self._request_slot(self.policy.min_interval_seconds)
            elif self._last_request_at is not None:
                elapsed = time.monotonic() - self._last_request_at
                delay = max(0.0, self.policy.min_interval_seconds - elapsed)
            else:
                delay = 0.0
            if remaining is not None and delay >= remaining:
                raise SecSourceError(
                    "REQUEST_DEADLINE_EXCEEDED",
                    "SEC request pacing exceeds the remaining deadline",
                    retryable=True,
                )
            if delay > 0:
                self._sleep(delay)
                if deadline_at is not None:
                    remaining = (
                        deadline_at - datetime.now(timezone.utc)
                    ).total_seconds()
                    if remaining <= 0:
                        raise SecSourceError(
                            "REQUEST_DEADLINE_EXCEEDED",
                            "SEC acquisition deadline expired",
                            retryable=True,
                        )
            request = Request(
                uri,
                headers={
                    "User-Agent": self.policy.user_agent,
                    "Accept": ", ".join(
                        (
                            "application/json",
                            "text/html",
                            "application/xml",
                            "application/zip",
                            "application/octet-stream",
                        )
                    ),
                },
            )
            self._last_request_at = time.monotonic()
            try:
                with self._opener(
                    request,
                    timeout=min(
                        self.policy.timeout_seconds,
                        remaining
                        if remaining is not None
                        else self.policy.timeout_seconds,
                    ),
                ) as response:
                    status = int(getattr(response, "status", 200))
                    if status in {301, 302, 303, 307, 308}:
                        raise SecSourceError(
                            "SOURCE_REDIRECT_NOT_ALLOWED",
                            "SEC source redirects are not permitted",
                            retryable=False,
                        )
                    payload = self._read_bounded(response, deadline_at)
                    media_type = response.headers.get_content_type()
                    available_at = self._clock()
                    response_headers = tuple(
                        sorted(
                            (str(name).lower(), str(value).strip())
                            for name, value in response.headers.items()
                            if str(name).lower() in _RETAINED_RESPONSE_HEADERS
                        )
                    )
                    declared_header = response.headers.get("Content-Length")
                    declared_size = (
                        int(declared_header)
                        if declared_header is not None and declared_header.isdecimal()
                        else None
                    )
                    if declared_size is not None and declared_size != len(payload):
                        raise SecSourceError(
                            "SOURCE_RESPONSE_SIZE_MISMATCH",
                            "SEC response length does not match Content-Length",
                        )
                    return _SecResponse(
                        content=payload,
                        http_status=status,
                        media_type=media_type,
                        available_at=available_at,
                        response_headers=response_headers,
                        declared_size=declared_size,
                    )
            except HTTPError as error:
                if error.code in {301, 302, 303, 307, 308}:
                    raise SecSourceError(
                        "SOURCE_REDIRECT_NOT_ALLOWED",
                        "SEC source redirects are not permitted",
                        retryable=False,
                    ) from error
                last_error = error
                retryable = error.code == 429 or 500 <= error.code < 600
                if not retryable or attempt + 1 >= self.policy.max_attempts:
                    code = (
                        "SOURCE_RATE_LIMITED"
                        if error.code == 429
                        else "SOURCE_UNAVAILABLE"
                    )
                    raise SecSourceError(
                        code,
                        f"SEC request returned HTTP {error.code}",
                        retryable=retryable,
                    ) from error
                retry_after = _parse_retry_after(error.headers.get("Retry-After"))
                self._sleep_with_deadline(
                    retry_after if retry_after is not None else 2**attempt, deadline_at
                )
            except (URLError, TimeoutError, OSError, IncompleteRead) as error:
                last_error = error
                if attempt + 1 >= self.policy.max_attempts:
                    raise SecSourceError(
                        "SOURCE_UNAVAILABLE",
                        "SEC request failed after retries",
                        retryable=True,
                    ) from error
                self._sleep_with_deadline(2**attempt, deadline_at)
        raise SecSourceError(
            "SOURCE_UNAVAILABLE", "SEC request failed", retryable=True
        ) from last_error

    def _read_bounded(self, response: object, deadline_at: datetime | None) -> bytes:
        read = getattr(response, "read")
        chunks: list[bytes] = []
        total = 0
        while True:
            if deadline_at is not None and datetime.now(timezone.utc) >= deadline_at:
                raise SecSourceError(
                    "REQUEST_DEADLINE_EXCEEDED",
                    "SEC response exceeded the request deadline",
                    retryable=True,
                )
            try:
                chunk = read(
                    min(1024 * 1024, self.policy.max_response_bytes + 1 - total)
                )
            except TypeError:
                chunk = read()
                if len(chunk) > self.policy.max_response_bytes:
                    raise SecSourceError(
                        "SOURCE_RESPONSE_TOO_LARGE",
                        "SEC response exceeds the configured evidence limit",
                        retryable=False,
                    )
                return chunk
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
            total += len(chunk)
            if total > self.policy.max_response_bytes:
                raise SecSourceError(
                    "SOURCE_RESPONSE_TOO_LARGE",
                    "SEC response exceeds the configured evidence limit",
                    retryable=False,
                )

    def _sleep_with_deadline(
        self, delay_seconds: float, deadline_at: datetime | None
    ) -> None:
        if deadline_at is not None:
            remaining = (deadline_at - datetime.now(timezone.utc)).total_seconds()
            if remaining <= delay_seconds:
                raise SecSourceError(
                    "REQUEST_DEADLINE_EXCEEDED",
                    "SEC retry delay exceeds the request deadline",
                    retryable=True,
                )
        self._sleep(delay_seconds)

    def capture_json(
        self,
        *,
        source_id: str,
        uri: str,
        captured_at: datetime | None = None,
        deadline_at: datetime | None = None,
    ) -> CapturedSource:
        if source_id not in {
            "sec-companyfacts",
            "sec-company-tickers",
            "sec-submissions",
            "sec-filing-index",
        }:
            raise SecSourceError(
                "SOURCE_NOT_REGISTERED", f"unsupported SEC source {source_id}"
            )
        if source_id == "sec-companyfacts":
            expected_prefixes = (f"{self.policy.base_url}/api/xbrl/companyfacts/",)
        elif source_id == "sec-submissions":
            expected_prefixes = (f"{self.policy.base_url}/submissions/",)
        elif source_id == "sec-company-tickers":
            expected_prefixes = ("https://www.sec.gov/files/company_tickers.json",)
        else:
            expected_prefixes = ("https://www.sec.gov/Archives/edgar/data/",)
        parsed = urlsplit(uri)
        allowed_hosts = (
            {"data.sec.gov"}
            if source_id in {"sec-companyfacts", "sec-submissions"}
            else {"www.sec.gov"}
        )
        if (
            parsed.scheme != "https"
            or parsed.hostname not in allowed_hosts
            or parsed.port is not None
            or parsed.username is not None
            or parsed.password is not None
            or (
                uri != expected_prefixes[0]
                if source_id == "sec-company-tickers"
                else not uri.startswith(expected_prefixes)
            )
        ):
            raise SecSourceError(
                "SOURCE_URI_NOT_ALLOWED",
                f"URI is outside the registered {source_id} endpoint",
            )
        response = self._request(uri, deadline_at=deadline_at)
        payload = response.content
        try:
            json.loads(payload)
        except json.JSONDecodeError as error:
            raise SecSourceError(
                "SOURCE_PAYLOAD_INVALID", "SEC JSON payload is invalid"
            ) from error
        return CapturedSource(
            source_id=source_id,
            uri=uri,
            role=(
                SourceRole.FACTS
                if source_id == "sec-companyfacts"
                else SourceRole.ACQUISITION
                if source_id in {"sec-company-tickers", "sec-submissions"}
                else SourceRole.REFERENCE
            ),
            content=payload,
            media_type=response.media_type or "application/json",
            http_status=response.http_status,
            available_at=response.available_at,
            captured_at=captured_at or response.available_at,
            publication_at=response.available_at,
            response_headers=response.response_headers,
            declared_size=response.declared_size,
            received_size=len(payload),
        )

    def capture_company_facts(
        self,
        cik: str,
        *,
        captured_at: datetime | None = None,
        deadline_at: datetime | None = None,
    ) -> CapturedSource:
        normalized = cik.strip().lstrip("0") or "0"
        if not normalized.isdigit() or len(normalized) > 10:
            raise ValueError("CIK must be numeric and at most ten digits")
        return self.capture_json(
            source_id="sec-companyfacts",
            uri=f"{self.policy.base_url}/api/xbrl/companyfacts/CIK{int(normalized):010d}.json",
            captured_at=captured_at,
            deadline_at=deadline_at,
        )

    def capture_company_tickers(
        self, *, deadline_at: datetime | None = None
    ) -> CapturedSource:
        """Capture SEC's public ticker-to-CIK reference as immutable evidence."""
        return self.capture_json(
            source_id="sec-company-tickers",
            uri="https://www.sec.gov/files/company_tickers.json",
            deadline_at=deadline_at,
        )

    def capture_submissions(
        self,
        cik: str,
        *,
        captured_at: datetime | None = None,
        deadline_at: datetime | None = None,
    ) -> CapturedSource:
        normalized = cik.strip().lstrip("0") or "0"
        if not normalized.isdigit() or len(normalized) > 10:
            raise ValueError("CIK must be numeric and at most ten digits")
        return self.capture_json(
            source_id="sec-submissions",
            uri=f"{self.policy.base_url}/submissions/CIK{int(normalized):010d}.json",
            captured_at=captured_at,
            deadline_at=deadline_at,
        )

    def capture_filing(
        self,
        *,
        cik: str,
        accession_number: str,
        primary_document: str,
        filed_at: datetime,
        captured_at: datetime | None = None,
        form: str = "10-K",
        is_amendment: bool = False,
        amends_accession: str | None = None,
        amendment_scope: str | None = None,
        accepted_at: datetime | None = None,
        filing_date: date | None = None,
        deadline_at: datetime | None = None,
    ) -> CapturedSource:
        normalized = cik.strip().lstrip("0") or "0"
        accession_path = accession_number.replace("-", "")
        if not normalized.isdigit() or len(normalized) > 10:
            raise ValueError("CIK must be numeric and at most ten digits")
        if not accession_path.isdigit() or len(accession_path) != 18:
            raise ValueError("accession number must be in SEC accession format")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", primary_document):
            raise ValueError("primary document must be a simple SEC archive filename")
        uri = f"https://www.sec.gov/Archives/edgar/data/{int(normalized)}/{accession_path}/{primary_document}"
        response = self._request(uri, deadline_at=deadline_at)
        payload = response.content
        return CapturedSource(
            source_id="sec-filing",
            uri=uri,
            role=SourceRole.FILING,
            content=payload,
            media_type=response.media_type or "text/html",
            http_status=response.http_status,
            available_at=accepted_at or filed_at,
            captured_at=captured_at or response.available_at,
            publication_at=filed_at,
            filed_at=filed_at,
            filing_date=filing_date,
            accession_number=accession_number,
            form=form,
            filing_version=accession_number,
            is_amendment=is_amendment,
            amends_accession=amends_accession,
            amendment_scope=amendment_scope,
            response_headers=response.response_headers,
            declared_size=response.declared_size,
            received_size=len(response.content),
        )

    def capture_filing_submission(
        self,
        *,
        cik: str,
        accession_number: str,
        filed_at: datetime,
        captured_at: datetime | None = None,
        form: str = "10-K",
        is_amendment: bool = False,
        amends_accession: str | None = None,
        amendment_scope: str | None = None,
        accepted_at: datetime | None = None,
        filing_date: date | None = None,
        deadline_at: datetime | None = None,
    ) -> CapturedSource:
        """Capture the accession-bound EDGAR full-submission text response."""
        normalized = cik.strip().lstrip("0") or "0"
        accession_path = accession_number.replace("-", "")
        if not normalized.isdigit() or len(normalized) > 10:
            raise ValueError("CIK must be numeric and at most ten digits")
        if not accession_path.isdigit() or len(accession_path) != 18:
            raise ValueError("accession number must be in SEC accession format")
        if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession_number):
            raise ValueError("accession number must be in SEC accession format")
        filename = f"{accession_number}.txt"
        uri = (
            f"https://www.sec.gov/Archives/edgar/data/{int(normalized)}/"
            f"{accession_path}/{filename}"
        )
        response = self._request(uri, deadline_at=deadline_at)
        available_at = accepted_at or filed_at
        return CapturedSource(
            source_id="sec-filing-submission",
            uri=uri,
            role=SourceRole.FILING,
            content=response.content,
            media_type=response.media_type or "text/plain",
            http_status=response.http_status,
            available_at=available_at,
            captured_at=captured_at or response.available_at,
            publication_at=filed_at,
            filed_at=filed_at,
            filing_date=filing_date,
            accession_number=accession_number,
            form=form,
            filing_version=accession_number,
            is_amendment=is_amendment,
            amends_accession=amends_accession,
            amendment_scope=amendment_scope,
            response_headers=response.response_headers,
            declared_size=response.declared_size,
            received_size=len(response.content),
        )

    def capture_filing_archive(
        self,
        *,
        cik: str,
        accession_number: str,
        filed_at: datetime,
        filename: str | None = None,
        captured_at: datetime | None = None,
        form: str = "10-K",
        is_amendment: bool = False,
        amends_accession: str | None = None,
        amendment_scope: str | None = None,
        accepted_at: datetime | None = None,
        deadline_at: datetime | None = None,
    ) -> CapturedSource:
        """Capture the accession-matched SEC XBRL archive as immutable evidence."""
        normalized = cik.strip().lstrip("0") or "0"
        accession_path = accession_number.replace("-", "")
        if not normalized.isdigit() or len(normalized) > 10:
            raise ValueError("CIK must be numeric and at most ten digits")
        if not accession_path.isdigit() or len(accession_path) != 18:
            raise ValueError("accession number must be in SEC accession format")
        expected_filename = f"{accession_number}-xbrl.zip"
        if filename is None:
            filename = expected_filename
        if filename != expected_filename:
            raise ValueError("filing archive must match the SEC accession number")
        uri = (
            f"https://www.sec.gov/Archives/edgar/data/{int(normalized)}/"
            f"{accession_path}/{filename}"
        )
        response = self._request(uri, deadline_at=deadline_at)
        return CapturedSource(
            source_id="sec-filing-archive",
            uri=uri,
            role=SourceRole.FILING,
            content=response.content,
            media_type=response.media_type or "application/zip",
            http_status=response.http_status,
            available_at=accepted_at or filed_at,
            captured_at=captured_at or response.available_at,
            publication_at=filed_at,
            filed_at=filed_at,
            accession_number=accession_number,
            form=form,
            filing_version=accession_number,
            is_amendment=is_amendment,
            amends_accession=amends_accession,
            amendment_scope=amendment_scope,
            response_headers=response.response_headers,
            declared_size=response.declared_size,
            received_size=len(response.content),
        )

    def capture_filing_resource(
        self,
        *,
        cik: str,
        accession_number: str,
        filename: str,
        role: SourceRole = SourceRole.TAXONOMY,
        filed_at: datetime | None = None,
        filing_date: date | None = None,
        taxonomy_manifest_id: str | None = None,
        form: str = "XBRL-DTS",
        is_amendment: bool = False,
        amends_accession: str | None = None,
        amendment_scope: str | None = None,
        captured_at: datetime | None = None,
        deadline_at: datetime | None = None,
    ) -> CapturedSource:
        """Capture a DTS/XBRL resource declared in the SEC filing index."""
        normalized = cik.strip().lstrip("0") or "0"
        accession_path = accession_number.replace("-", "")
        if not normalized.isdigit() or len(normalized) > 10:
            raise ValueError("CIK must be numeric and at most ten digits")
        if not accession_path.isdigit() or len(accession_path) != 18:
            raise ValueError("accession number must be in SEC accession format")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", filename):
            raise ValueError("filing resource must be a simple SEC archive filename")
        uri = (
            f"https://www.sec.gov/Archives/edgar/data/{int(normalized)}/"
            f"{accession_path}/{filename}"
        )
        if role not in {SourceRole.FILING, SourceRole.TAXONOMY}:
            raise ValueError("SEC filing resources must be filing or taxonomy records")
        response = self._request(uri, deadline_at=deadline_at)
        payload = response.content
        available_at = filed_at or response.available_at
        return CapturedSource(
            source_id="sec-taxonomy" if role is SourceRole.TAXONOMY else "sec-filing",
            uri=uri,
            role=role,
            content=payload,
            media_type=response.media_type or "application/octet-stream",
            http_status=response.http_status,
            available_at=available_at,
            captured_at=captured_at or response.available_at,
            publication_at=available_at,
            filing_date=filing_date,
            accession_number=accession_number,
            form=form,
            filed_at=filed_at,
            filing_version=accession_number,
            is_amendment=is_amendment,
            amends_accession=amends_accession,
            amendment_scope=amendment_scope,
            taxonomy_manifest_id=taxonomy_manifest_id,
            response_headers=response.response_headers,
            declared_size=response.declared_size,
            received_size=len(payload),
        )

    def capture_filing_index(
        self,
        *,
        cik: str,
        accession_number: str,
        deadline_at: datetime | None = None,
        filed_at: datetime | None = None,
        captured_at: datetime | None = None,
    ) -> CapturedSource:
        """Capture the accession's filing index, including DTS resource paths."""
        normalized = cik.strip().lstrip("0") or "0"
        accession_path = accession_number.replace("-", "")
        if not normalized.isdigit() or len(normalized) > 10:
            raise ValueError("CIK must be numeric and at most ten digits")
        if not accession_path.isdigit() or len(accession_path) != 18:
            raise ValueError("accession number must be in SEC accession format")
        source = self.capture_json(
            source_id="sec-filing-index",
            uri=f"https://www.sec.gov/Archives/edgar/data/{int(normalized)}/{accession_path}/index.json",
            captured_at=captured_at,
            deadline_at=deadline_at,
        )
        if filed_at is None:
            return source
        return replace(
            source,
            available_at=filed_at,
            publication_at=filed_at,
            accession_number=accession_number,
            form="SEC-FILING-INDEX",
            filed_at=filed_at,
            filing_version=accession_number,
        )
