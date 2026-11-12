"""Interchangeable Treasury and ALFRED adapters for retained ten-year par yields."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from .macro_series import (
    MacroObservationV1,
    MacroSeriesVintageV1,
    MacroSourceArtifactV1,
    RetainedMacroSourceV1,
)
from .snapshots import SnapshotError

TREASURY_SERIES = "us.treasury_par_yield_10y"
TREASURY_SOURCE = "treasury-yields"
TREASURY_PROFILE = "treasury-par-yield-xml-10y-v1"
TREASURY_TERMS = "https://fiscaldata.treasury.gov/terms-of-use/"
ALFRED_SOURCE = "alfred-vintage"
ALFRED_TREASURY_PROFILE = "alfred-dgs10-csv-vintage-v1"
ALFRED_TERMS = "https://fred.stlouisfed.org/terms-of-use/"
_TREASURY_PATH = "/resource-center/data-chart-center/interest-rates/pages/xml"
_ALFRED_PATH = "/graph/alfredgraph.csv"
_ATOM = "{http://www.w3.org/2005/Atom}"
_DATA = "{http://schemas.microsoft.com/ado/2007/08/dataservices}"
_META = "{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}"
_NEW_YORK = ZoneInfo("America/New_York")


def _query(uri: str, *, host: str, path: str) -> dict[str, list[str]]:
    parsed = urlsplit(uri)
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    if (
        parsed.scheme != "https"
        or parsed.netloc != host
        or parsed.path != path
        or parsed.fragment
        or any(len(values) != 1 for values in query.values())
    ):
        raise ValueError("source request does not match its canonical endpoint")
    return query


def treasury_request_year(uri: str) -> int:
    """Validate the annual XML request before transport performs any I/O."""
    try:
        query = _query(uri, host="home.treasury.gov", path=_TREASURY_PATH)
        year = query["field_tdr_date_value"][0]
        if (
            set(query) != {"data", "field_tdr_date_value"}
            or query["data"] != ["daily_treasury_yield_curve"]
            or re.fullmatch(r"[0-9]{4}", year) is None
            or not 1990 <= int(year) <= 9998
        ):
            raise ValueError("Treasury request must select one annual par-yield table")
        return int(year)
    except (KeyError, ValueError, IndexError) as error:
        raise SnapshotError(
            "SOURCE_QUERY_INVALID", "invalid Treasury XML request"
        ) from error


def alfred_treasury_request(uri: str) -> tuple[date, date, date]:
    """Bind DGS10, observation range and vintage without supplying expected values."""
    try:
        query = _query(uri, host="alfred.stlouisfed.org", path=_ALFRED_PATH)
        if "vintage_date" not in query:
            raise SnapshotError(
                "SOURCE_VINTAGE_REQUIRED", "ALFRED requires one vintage_date"
            )
        start, end, vintage = (
            date.fromisoformat(query[key][0])
            for key in ("cosd", "coed", "vintage_date")
        )
        if (
            set(query) != {"id", "cosd", "coed", "vintage_date"}
            or query["id"] != ["DGS10"]
            or any(
                query[key] != [value.isoformat()]
                for key, value in (
                    ("cosd", start),
                    ("coed", end),
                    ("vintage_date", vintage),
                )
            )
            or not start <= end <= vintage
            or (end - start).days > 366
        ):
            raise ValueError("ALFRED requires a bounded DGS10 range within the vintage")
        return start, end, vintage
    except (KeyError, ValueError, IndexError) as error:
        raise SnapshotError(
            "SOURCE_QUERY_INVALID", "invalid ALFRED DGS10 request"
        ) from error


def _capture_time(source: RetainedMacroSourceV1) -> datetime:
    captured = source.captured_at
    if captured.tzinfo is None or captured.utcoffset() is None:
        raise ValueError("source capture time requires a timezone")
    return captured.astimezone(UTC)


def _rate(value: str) -> Decimal:
    if re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", value) is None:
        raise ValueError("yield is missing or not a decimal observation")
    rate = Decimal(value)
    if not rate.is_finite() or not Decimal("-100") < rate < Decimal("100"):
        raise ValueError("yield is outside the supported percent range")
    return rate


def _vintage(
    source: RetainedMacroSourceV1,
    *,
    provider_id: str,
    available_at: datetime,
    rows: list[tuple[date, Decimal]],
) -> MacroSeriesVintageV1:
    digest = hashlib.sha256(source.content).hexdigest()
    return MacroSeriesVintageV1.build(
        series_id=TREASURY_SERIES,
        provider_id=provider_id,
        frequency="daily",
        unit="percent",
        source_version=source.source_version,
        available_at=available_at,
        captured_at=source.captured_at,
        artifacts=(
            MacroSourceArtifactV1(
                source_id=source.source_id,
                uri=source.uri,
                source_version=source.source_version,
                terms_reference=source.terms_reference,
                content_sha256=digest,
                captured_at=source.captured_at,
            ),
        ),
        observations=tuple(
            MacroObservationV1(
                series_id=TREASURY_SERIES,
                period_start=day,
                period_end=day,
                value=value,
                unit="percent",
                source_sha256=digest,
            )
            for day, value in rows
        ),
    )


class TreasuryParYieldVintageProvider:
    """Reproduce mutable Treasury XML, available only from retained capture time."""

    provider_id = "us-treasury"

    def supports(self, series_id: str) -> bool:
        return series_id == TREASURY_SERIES

    def reproduce_vintage(
        self, *, series_id: str, sources: tuple[RetainedMacroSourceV1, ...]
    ) -> MacroSeriesVintageV1:
        try:
            if not self.supports(series_id) or len(sources) != 1:
                raise ValueError("Treasury requires one retained annual source")
            source = sources[0]
            if (source.source_id, source.source_version, source.terms_reference) != (
                TREASURY_SOURCE,
                TREASURY_PROFILE,
                TREASURY_TERMS,
            ):
                raise ValueError("Treasury source profile does not match")
            year = treasury_request_year(source.uri)
            captured = _capture_time(source)
            if not 0 < len(source.content) <= 2 * 1024 * 1024:
                raise ValueError("Treasury XML exceeds the bounded source profile")
            xml = source.content.decode("utf-8")
            if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", xml, flags=re.IGNORECASE):
                raise ValueError("XML entity declarations are not permitted")
            root = ElementTree.fromstring(xml)
            if root.tag != _ATOM + "feed" or root.findtext(_ATOM + "title") != (
                "DailyTreasuryYieldCurveRateData"
            ):
                raise ValueError("Treasury feed does not identify the par-yield table")
            rows: list[tuple[date, Decimal]] = []
            entries = root.findall(_ATOM + "entry")
            if not 0 < len(entries) <= 366:
                raise ValueError("Treasury annual feed must contain observations")
            for entry in entries:
                properties = entry.findall(f"{_ATOM}content/{_META}properties")
                if len(properties) != 1:
                    raise ValueError("Treasury entry has ambiguous properties")
                dates = properties[0].findall(_DATA + "NEW_DATE")
                rates = properties[0].findall(_DATA + "BC_10YEAR")
                if len(dates) != 1 or len(rates) != 1:
                    raise ValueError(
                        "Treasury entry lacks a unique date or ten-year yield"
                    )
                day_text = dates[0].text or ""
                day = date.fromisoformat(day_text[:10])
                if (
                    day_text != day.isoformat() + "T00:00:00"
                    or dates[0].get(_META + "type") != "Edm.DateTime"
                    or rates[0].get(_META + "type") != "Edm.Double"
                    or rates[0].get(_META + "null") is not None
                    or day.year != year
                    or day > captured.astimezone(_NEW_YORK).date()
                ):
                    raise ValueError("Treasury observation date or type is invalid")
                rows.append((day, _rate(rates[0].text or "")))
            return _vintage(
                source, provider_id=self.provider_id, available_at=captured, rows=rows
            )
        except (ValueError, TypeError, UnicodeError, ElementTree.ParseError) as error:
            raise SnapshotError(
                "TREASURY_SOURCE_INVALID",
                "retained Treasury XML does not reproduce its profile",
            ) from error


class AlfredTreasuryVintageProvider:
    """Reproduce a header-bound ALFRED vintage after its local calendar day ends."""

    provider_id = "alfred"

    def supports(self, series_id: str) -> bool:
        return series_id == TREASURY_SERIES

    def reproduce_vintage(
        self, *, series_id: str, sources: tuple[RetainedMacroSourceV1, ...]
    ) -> MacroSeriesVintageV1:
        try:
            if not self.supports(series_id) or len(sources) != 1:
                raise ValueError("ALFRED requires one retained vintage CSV")
            source = sources[0]
            if (source.source_id, source.source_version, source.terms_reference) != (
                ALFRED_SOURCE,
                ALFRED_TREASURY_PROFILE,
                ALFRED_TERMS,
            ):
                raise ValueError("ALFRED source profile does not match")
            start, end, vintage = alfred_treasury_request(source.uri)
            available = datetime.combine(
                vintage + timedelta(days=1), time(), _NEW_YORK
            ).astimezone(UTC)
            if (
                available > _capture_time(source)
                or not 0 < len(source.content) <= 1024 * 1024
            ):
                raise ValueError(
                    "ALFRED vintage day has not ended or CSV exceeds its bound"
                )
            reader = csv.reader(
                io.StringIO(source.content.decode("utf-8")), strict=True
            )
            if next(reader, None) != ["observation_date", f"DGS10_{vintage:%Y%m%d}"]:
                raise ValueError(
                    "ALFRED header does not match the requested series and vintage"
                )
            rows: list[tuple[date, Decimal]] = []
            for row in reader:
                if len(row) != 2 or len(rows) >= 367:
                    raise ValueError("ALFRED row has an invalid shape or count")
                day = date.fromisoformat(row[0])
                if row[0] != day.isoformat() or not start <= day <= end:
                    raise ValueError(
                        "ALFRED observation is outside the requested date range"
                    )
                rows.append((day, _rate(row[1])))
            return _vintage(
                source, provider_id=self.provider_id, available_at=available, rows=rows
            )
        except (ValueError, TypeError, UnicodeError, csv.Error, OverflowError) as error:
            raise SnapshotError(
                "ALFRED_SOURCE_INVALID",
                "retained ALFRED CSV does not reproduce its DGS10 vintage",
            ) from error
