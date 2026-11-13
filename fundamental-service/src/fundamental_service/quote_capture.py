"""Compose entitled quote HTTP capture on the existing acquisition boundary."""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from typing import Protocol
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from .contracts import SourceRole
from .public_source import PublicResponsePort, PublicSourceAdapter
from .public_source_catalog import default_public_source_registrations
from .quote_admission import QUOTE_METRIC, QUOTE_POPULATION
from .snapshots import SnapshotError
from .source_admission import SourceUsePolicyV1
from .source_capture import (
    PublicSourceRegistration,
    PublicSourceSpec,
    RetainedAvailabilityCaptureProfile,
    SourceCaptureRequest,
    SourceCaptureResponse,
    SourceCaptureTimes,
)
from .twelve_quote_source import (
    TWELVE_CLOSE_PROFILE,
    TWELVE_CLOSE_SOURCE,
    TWELVE_TERMS,
    validate_twelve_data_daily_uri,
)

TWELVE_TERMS_SOURCE = "twelve-data-terms"
_MAX_QUOTE_BYTES = 1024 * 1024


class _NoQuoteRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> None:
        raise SnapshotError(
            "QUOTE_SOURCE_REDIRECT_REFUSED", "quote redirects are not permitted"
        )


class QuoteHttpResponsePort(Protocol):
    headers: Message
    status: int

    def read(self, size: int) -> bytes: ...


@dataclass
class _BufferedResponse:
    headers: Message
    status: int
    content: bytes

    def read(self) -> bytes:
        return self.content


def _validate_terms_uri(uri: str) -> None:
    if uri != TWELVE_TERMS:
        raise SnapshotError(
            "SOURCE_URI_NOT_ALLOWED", "quote terms require the exact registered URI"
        )


class _QuoteCaptureProfile:
    def validate_request(self, request: SourceCaptureRequest) -> None:
        if any(
            value is not None
            for value in (
                request.available_at,
                request.publication_at,
                request.captured_at,
            )
        ):
            raise SnapshotError(
                "SOURCE_AVAILABILITY_UNVERIFIED",
                "quote availability requires actual capture",
            )
        try:
            validate_twelve_data_daily_uri(request.uri)
        except ValueError as error:
            raise SnapshotError(
                "SOURCE_URI_NOT_ALLOWED", "unsupported quote capture URI"
            ) from error

    def resolve_capture(
        self, request: SourceCaptureRequest, response: SourceCaptureResponse
    ) -> SourceCaptureTimes:
        # Malformed/provider-error bytes remain available to admission diagnostics.
        return SourceCaptureTimes(response.retrieved_at, None, response.retrieved_at)


def quote_preparation_source_adapter(
    *,
    user_agent: str,
    policy: SourceUsePolicyV1 | None,
    api_key_file: Path | None,
    quote_opener: Callable[..., AbstractContextManager[QuoteHttpResponsePort]]
    | None = None,
    public_opener: Callable[..., AbstractContextManager[PublicResponsePort]] = urlopen,
) -> PublicSourceAdapter:
    """Keep credentials outside durable identities; cache hits need no key read."""
    open_quote = quote_opener or build_opener(_NoQuoteRedirect()).open

    @contextmanager
    def open_source(
        request: Request, *, timeout: float
    ) -> Iterator[PublicResponsePort]:
        if request.host != "api.twelvedata.com":
            with public_opener(request, timeout=timeout) as response:
                yield response
            return
        validate_twelve_data_daily_uri(request.full_url)
        rules = (
            tuple(
                rule
                for rule in policy.rules
                if (
                    rule.provider_id == TWELVE_CLOSE_SOURCE
                    and rule.metric_id == QUOTE_METRIC
                    and rule.population == QUOTE_POPULATION
                    and rule.source_id == TWELVE_CLOSE_SOURCE
                    and rule.source_version == TWELVE_CLOSE_PROFILE
                    and rule.terms_reference == TWELVE_TERMS
                )
            )
            if policy is not None
            else ()
        )
        if len(rules) != 1:
            raise SnapshotError(
                "SOURCE_USE_POLICY_MISSING"
                if not rules
                else "SOURCE_USE_POLICY_AMBIGUOUS",
                "quote capture requires an unambiguous deployment-owned source-use rule",
                retryable=True,
            )
        if "valuation_preparation" not in rules[0].permitted_uses:
            raise SnapshotError(
                "SOURCE_USE_PURPOSE_UNSUPPORTED",
                "quote capture requires valuation preparation permission",
                retryable=True,
            )
        try:
            key = api_key_file.read_text().strip() if api_key_file else ""
        except (OSError, UnicodeError):
            raise SnapshotError(
                "QUOTE_SOURCE_CREDENTIAL_UNAVAILABLE",
                "quote credential file is unavailable",
                retryable=True,
            ) from None
        if (
            not key
            or len(key) > 1024
            or any(not 33 <= ord(char) <= 126 for char in key)
        ):
            raise SnapshotError(
                "QUOTE_SOURCE_CREDENTIAL_UNAVAILABLE",
                "quote requires a valid deployment credential file",
                retryable=True,
            )
        request.add_header("Authorization", f"apikey {key}")
        with open_quote(request, timeout=timeout) as response:
            payload = response.read(_MAX_QUOTE_BYTES + 1)
            if len(payload) > _MAX_QUOTE_BYTES:
                raise SnapshotError(
                    "QUOTE_SOURCE_TOO_LARGE", "quote response exceeds the capture limit"
                )
            if key.encode() in payload:
                raise SnapshotError(
                    "QUOTE_SOURCE_CREDENTIAL_ECHO_REFUSED",
                    "quote response contains credential material",
                )
            yield _BufferedResponse(response.headers, response.status, payload)

    registrations = (
        *default_public_source_registrations(),
        PublicSourceRegistration(
            PublicSourceSpec(
                TWELVE_CLOSE_SOURCE,
                SourceRole.REFERENCE,
                "https://api.twelvedata.com/time_series",
                TWELVE_TERMS,
                "exact",
            ),
            _QuoteCaptureProfile(),
        ),
        PublicSourceRegistration(
            PublicSourceSpec(
                TWELVE_TERMS_SOURCE,
                SourceRole.REFERENCE,
                TWELVE_TERMS,
                TWELVE_TERMS,
                "exact",
            ),
            RetainedAvailabilityCaptureProfile(
                _validate_terms_uri, require_nonempty=True
            ),
        ),
    )
    return PublicSourceAdapter(
        user_agent=user_agent, registrations=registrations, opener=open_source
    )
