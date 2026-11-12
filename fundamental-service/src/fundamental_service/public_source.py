"""Free public macro/reference source capture with an explicit URI allowlist."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

from .contracts import SourceRole
from .snapshots import CapturedSource, LegalSource, SnapshotError, SourceRegister


class PublicResponsePort(Protocol):
    headers: Message

    def read(self) -> bytes: ...


@dataclass(frozen=True)
class PublicSourceSpec:
    source_id: str
    role: SourceRole
    uri_prefix: str
    terms_reference: str


PUBLIC_SOURCE_SPECS: tuple[PublicSourceSpec, ...] = (
    PublicSourceSpec(
        "treasury-yields",
        SourceRole.MACRO,
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/",
        "https://fiscaldata.treasury.gov/terms-of-use/",
    ),
    PublicSourceSpec(
        "fred-observations",
        SourceRole.MACRO,
        "https://fred.stlouisfed.org/graph/fredgraph.csv",
        "https://fred.stlouisfed.org/terms-of-use/",
    ),
    PublicSourceSpec(
        "alfred-vintage",
        SourceRole.MACRO,
        "https://alfred.stlouisfed.org/graph/alfredgraph.csv",
        "https://fred.stlouisfed.org/terms-of-use/",
    ),
    PublicSourceSpec(
        "bea-public-dataset",
        SourceRole.MACRO,
        "https://apps.bea.gov/",
        "https://apps.bea.gov/API/signup/",
    ),
    PublicSourceSpec(
        "bls-public-api",
        SourceRole.MACRO,
        "https://api.bls.gov/publicAPI/",
        "https://www.bls.gov/developers/",
    ),
    PublicSourceSpec(
        "federal-reserve-h15",
        SourceRole.MACRO,
        "https://www.federalreserve.gov/datadownload/",
        "https://www.federalreserve.gov/data.htm",
    ),
    PublicSourceSpec(
        "new-york-fed-sofr",
        SourceRole.MACRO,
        "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json",
        "https://www.newyorkfed.org/privacy/termsofuse",
    ),
    PublicSourceSpec(
        "federal-reserve-policy",
        SourceRole.REFERENCE,
        "https://www.federalreserve.gov/newsevents/pressreleases/",
        "https://www.federalreserve.gov/disclaimer.htm",
    ),
    PublicSourceSpec(
        "damodaran-archive-index",
        SourceRole.REFERENCE,
        "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/dataarchived.html",
        "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/",
    ),
    PublicSourceSpec(
        "fdic-bankfind",
        SourceRole.REFERENCE,
        "https://banks.data.fdic.gov/api/",
        "https://banks.data.fdic.gov/docs/",
    ),
    PublicSourceSpec(
        "ffiec-cdr",
        SourceRole.REFERENCE,
        "https://cdr.ffiec.gov/public/",
        "https://www.ffiec.gov/",
    ),
    PublicSourceSpec(
        "damodaran-reference",
        SourceRole.REFERENCE,
        "https://pages.stern.nyu.edu/~adamodar/pc/",
        "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/",
    ),
    # Post-cutover family sources.  Registration records the lawful public
    # boundary even while a family remains exploratory and cannot calculate.
    PublicSourceSpec(
        "naic-statutory-filings",
        SourceRole.REFERENCE,
        "https://content.naic.org/",
        "https://content.naic.org/insurance-topics/financial-data-repository",
    ),
    PublicSourceSpec(
        "nareit-definitions",
        SourceRole.REFERENCE,
        "https://www.reit.com/",
        "https://www.reit.com/terms-of-use",
    ),
    PublicSourceSpec(
        "ferc-public-data",
        SourceRole.REFERENCE,
        "https://www.ferc.gov/",
        "https://www.ferc.gov/terms-use",
    ),
    PublicSourceSpec(
        "state-utility-orders",
        SourceRole.REFERENCE,
        "https://www.naruc.org/",
        "https://www.naruc.org/about-naruc/",
    ),
    PublicSourceSpec(
        "eia-open-data",
        SourceRole.REFERENCE,
        "https://api.eia.gov/",
        "https://www.eia.gov/about/copyrights_reuse.php",
    ),
    PublicSourceSpec(
        "usgs-commodity-statistics",
        SourceRole.REFERENCE,
        "https://www.usgs.gov/centers/national-minerals-information-center/",
        "https://www.usgs.gov/information-policies",
    ),
    PublicSourceSpec(
        "usda-nass-quickstats",
        SourceRole.REFERENCE,
        "https://quickstats.nass.usda.gov/api/",
        "https://www.nass.usda.gov/About_NASS/",
    ),
    PublicSourceSpec(
        "fda-drugs",
        SourceRole.REFERENCE,
        "https://www.accessdata.fda.gov/",
        "https://www.fda.gov/about-fda/website-policies",
    ),
    PublicSourceSpec(
        "clinicaltrials-api",
        SourceRole.REFERENCE,
        "https://clinicaltrials.gov/data-api/api/",
        "https://clinicaltrials.gov/about-site/terms-conditions",
    ),
    PublicSourceSpec(
        "ifrs-taxonomy",
        SourceRole.TAXONOMY,
        "https://www.ifrs.org/issued-standards/ifrs-taxonomy/",
        "https://www.ifrs.org/legal/terms-and-conditions/",
    ),
)


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
            for spec in PUBLIC_SOURCE_SPECS
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
        for spec in PUBLIC_SOURCE_SPECS
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
        self.source_register = source_register or public_source_register()
        self.max_attempts = max_attempts
        self.min_interval_seconds = min_interval_seconds
        self.timeout_seconds = timeout_seconds
        self._opener = opener
        self._sleep = sleep
        self._last_request_at: float | None = None
        self._specs = {spec.source_id: spec for spec in PUBLIC_SOURCE_SPECS}

    def capture(
        self,
        source_id: str,
        uri: str,
        *,
        available_at: datetime | None = None,
        publication_at: datetime | None = None,
        captured_at: datetime | None = None,
    ) -> CapturedSource:
        spec = self._specs.get(source_id)
        if spec is None:
            raise SnapshotError(
                "SOURCE_NOT_REGISTERED", f"source {source_id} is not registered"
            )
        self.source_register.require(source_id)
        parsed = urlsplit(uri)
        prefix = urlsplit(spec.uri_prefix)
        path_allowed = (
            parsed.path == prefix.path
            if source_id in {"fred-observations", "alfred-vintage", "new-york-fed-sofr"}
            else parsed.path.startswith(prefix.path)
        )
        if (
            parsed.scheme != "https"
            or parsed.hostname != prefix.hostname
            or parsed.port is not None
            or parsed.username is not None
            or parsed.password is not None
            or not path_allowed
        ):
            raise SnapshotError(
                "SOURCE_URI_NOT_ALLOWED",
                f"URI is outside the registered {source_id} endpoint",
            )
        if source_id == "new-york-fed-sofr":
            try:
                query = parse_qs(
                    parsed.query, keep_blank_values=True, strict_parsing=True
                )
                start_value = query["startDate"][0]
                end_value = query["endDate"][0]
                start_date = date.fromisoformat(start_value)
                end_date = date.fromisoformat(end_value)
            except (KeyError, ValueError, IndexError) as error:
                raise SnapshotError(
                    "SOURCE_QUERY_INVALID",
                    "New York Fed SOFR requests require one ordered ISO date range",
                ) from error
            if (
                set(query) != {"startDate", "endDate"}
                or any(len(values) != 1 for values in query.values())
                or start_value != start_date.isoformat()
                or end_value != end_date.isoformat()
                or start_date != end_date
            ):
                raise SnapshotError(
                    "SOURCE_QUERY_INVALID",
                    "New York Fed SOFR capture requires one canonical ISO date",
                )
            if available_at is not None or publication_at is not None:
                raise SnapshotError(
                    "SOURCE_AVAILABILITY_UNVERIFIED",
                    "SOFR historical availability must use service capture time",
                )
        payload, status, media_type, retrieved_at = self._request(uri)
        if source_id == "new-york-fed-sofr":
            from .sofr_source import parse_new_york_fed_sofr

            parse_new_york_fed_sofr(
                payload,
                source_uri=uri,
                effective_date=start_date,
                captured_at=retrieved_at,
            )
            # Historical API responses do not establish when a value was first
            # published. Treat it as available only from this retained capture.
            available_at = retrieved_at
        if source_id == "alfred-vintage":
            vintage = parse_qs(parsed.query).get("vintage_date", ())
            if len(vintage) != 1:
                raise SnapshotError(
                    "SOURCE_VINTAGE_REQUIRED",
                    "ALFRED capture requires exactly one vintage_date query parameter",
                )
            if available_at is None:
                try:
                    available_at = datetime.fromisoformat(vintage[0]).replace(
                        tzinfo=timezone.utc
                    )
                except ValueError as error:
                    raise SnapshotError(
                        "SOURCE_VINTAGE_INVALID", "ALFRED vintage_date is invalid"
                    ) from error
        if available_at is None:
            raise SnapshotError(
                "SOURCE_AVAILABILITY_REQUIRED",
                f"{source_id} capture requires publisher availability metadata",
            )
        if available_at.tzinfo is None or (
            publication_at is not None and publication_at.tzinfo is None
        ):
            raise SnapshotError(
                "SOURCE_TIMESTAMP_TIMEZONE_REQUIRED",
                "source timestamps require a timezone",
            )
        if publication_at is None and source_id != "new-york-fed-sofr":
            publication_at = available_at
        if source_id in {"fred-observations", "alfred-vintage", "damodaran-reference"}:
            if not payload.strip():
                raise SnapshotError(
                    "SOURCE_PAYLOAD_INVALID", "public source returned empty bytes"
                )
        elif "json" in media_type:
            try:
                json.loads(payload)
            except json.JSONDecodeError as error:
                raise SnapshotError(
                    "SOURCE_PAYLOAD_INVALID", "public source JSON is invalid"
                ) from error
        return CapturedSource(
            source_id=source_id,
            uri=uri,
            role=spec.role,
            content=payload,
            media_type=media_type or "application/octet-stream",
            http_status=status,
            available_at=available_at,
            captured_at=(
                retrieved_at if source_id == "new-york-fed-sofr" else captured_at
            ),
            publication_at=publication_at,
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
