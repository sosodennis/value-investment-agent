"""Reproduce a quote from retained provider bytes, without provider I/O."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .equity_dilution import CommonShareQuoteV1, DilutionError
from .quote_providers import (
    QuoteSourceProviderPort,
    QuoteSourceRequestV1,
    reproduce_quote_source,
)

NASDAQ_CLOSE_PROFILE = "nasdaq-historical-close-capture-v1"
NASDAQ_CLOSE_SOURCE = "nasdaq-historical-close"
NASDAQ_TERMS = "https://www.nasdaq.com/terms-of-use"
_NEW_YORK = ZoneInfo("America/New_York")


class _ProviderModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class _Row(_ProviderModel):
    date: str
    close: str


class _Headers(_ProviderModel):
    date: str
    close: str


class _Table(_ProviderModel):
    headers: _Headers
    rows: tuple[_Row, ...] = Field(min_length=1, max_length=100)


class _Data(_ProviderModel):
    symbol: str
    totalRecords: int = Field(gt=0, le=100)
    tradesTable: _Table


class _Status(_ProviderModel):
    rCode: int
    bCodeMessage: None
    developerMessage: None


class _Response(_ProviderModel):
    data: _Data
    status: _Status


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _query_dates(source_uri: str, security_id: str) -> tuple[date, date]:
    uri = urlsplit(source_uri)
    query = parse_qs(uri.query, keep_blank_values=True, strict_parsing=True)
    if (
        uri.scheme != "https"
        or uri.netloc != "api.nasdaq.com"
        or uri.path != f"/api/quote/{security_id}/historical"
        or uri.fragment
        or not re.fullmatch(r"[A-Z0-9.-]{1,32}", security_id)
        or set(query) - {"assetclass", "fromdate", "todate", "limit"}
        or any(len(values) != 1 for values in query.values())
        or query.get("assetclass") != ["stocks"]
    ):
        raise ValueError("quote request does not match the U.S. stocks profile")
    start, end = (
        date.fromisoformat(query["fromdate"][0]),
        date.fromisoformat(query["todate"][0]),
    )
    if start >= end:
        raise ValueError("historical quote request requires an ordered date range")
    return start, end


def select_nasdaq_historical_close(
    raw: bytes,
    *,
    issuer_id: str,
    security_id: str,
    source_uri: str,
    observation_date: date,
    captured_at: datetime,
) -> CommonShareQuoteV1:
    """Use the daily date's start for conservative age and capture for availability.

    The response has no historical publication timestamp. It cannot establish
    availability before capture or the exchange's exact session close time.
    """
    try:
        if (
            len(raw) > 1024 * 1024
            or captured_at.tzinfo is None
            or captured_at.utcoffset() is None
        ):
            raise ValueError("quote source exceeds bounds or lacks capture timezone")
        start, end = _query_dates(source_uri, security_id)
        if not start <= observation_date <= end:
            raise ValueError("quote observation is outside the captured request")
        value = json.loads(raw, object_pairs_hook=_unique_object)
        # JSON input allows provider arrays while retaining strict scalar types.
        response = _Response.model_validate_json(json.dumps(value))
        if (
            response.status.rCode != 200
            or response.data.symbol != security_id
            or response.data.totalRecords != len(response.data.tradesTable.rows)
            or response.data.tradesTable.headers
            != _Headers(date="Date", close="Close/Last")
        ):
            raise ValueError("provider response does not match the requested quote")
        rows = response.data.tradesTable.rows
        dates = tuple(datetime.strptime(row.date, "%m/%d/%Y").date() for row in rows)
        if len(set(dates)) != len(dates) or any(
            not start <= day <= end for day in dates
        ):
            raise ValueError("provider dates are duplicated or outside the request")
        selected = tuple(
            row for row, day in zip(rows, dates, strict=True) if day == observation_date
        )
        if len(selected) != 1 or not re.fullmatch(
            r"\$(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)(?:\.[0-9]+)?",
            selected[0].close,
        ):
            raise ValueError("one positive dollar-denominated close is required")
        as_of = datetime.combine(observation_date, time.min, _NEW_YORK)
        day_end = datetime.combine(
            observation_date + timedelta(days=1), time.min, _NEW_YORK
        )
        if captured_at < day_end:
            raise DilutionError(
                "DILUTION_QUOTE_DAY_INCOMPLETE",
                "daily source must be captured after its New York calendar date ends",
            )
        return CommonShareQuoteV1(
            issuer_id=issuer_id,
            security_id=security_id,
            currency="USD",
            price=Decimal(selected[0].close[1:].replace(",", "")),
            source_id=NASDAQ_CLOSE_SOURCE,
            source_uri=source_uri,
            source_version=NASDAQ_CLOSE_PROFILE,
            terms_reference=NASDAQ_TERMS,
            content_hash=sha256(raw).hexdigest(),
            as_of=as_of.astimezone(UTC),
            available_at=captured_at,
            captured_at=captured_at,
        )
    except (ValueError, KeyError, TypeError, UnicodeError, ValidationError) as error:
        if isinstance(error, DilutionError):
            raise
        raise DilutionError(
            "DILUTION_QUOTE_SOURCE_INVALID",
            "retained quote does not reproduce the supported provider profile",
        ) from error


class NasdaqHistoricalCloseProvider:
    """Nasdaq adapter implementing the provider-neutral quote boundary."""

    def supports(self, source_id: str, source_version: str) -> bool:
        return (
            source_id == NASDAQ_CLOSE_SOURCE and source_version == NASDAQ_CLOSE_PROFILE
        )

    def reproduce_quote(
        self, raw: bytes, *, request: QuoteSourceRequestV1
    ) -> CommonShareQuoteV1:
        if (
            not self.supports(request.source_id, request.source_version)
            or request.terms_reference != NASDAQ_TERMS
        ):
            raise DilutionError(
                "DILUTION_QUOTE_SOURCE_PROFILE_UNSUPPORTED",
                "quote metadata does not match the Nasdaq source profile",
            )
        return select_nasdaq_historical_close(
            raw,
            issuer_id=request.issuer_id,
            security_id=request.security_id,
            source_uri=request.source_uri,
            observation_date=request.as_of.astimezone(_NEW_YORK).date(),
            captured_at=request.captured_at,
        )


def default_quote_providers() -> tuple[QuoteSourceProviderPort, ...]:
    """Composition for supported source formats; this does not admit source use."""
    return (NasdaqHistoricalCloseProvider(),)


def verify_quote_source(quote: CommonShareQuoteV1, raw: bytes) -> None:
    reproduce_quote_source(quote, raw, providers=default_quote_providers())
