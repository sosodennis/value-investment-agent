"""Reproduce Yahoo's latest completed daily close from retained chart bytes."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
import json
import re
from typing import Literal
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from .equity_dilution import CommonShareQuoteV1, DilutionError
from .quote_providers import QuoteSourceRequestV1

YAHOO_CLOSE_SOURCE = "yahoo-chart-daily-close"
YAHOO_CLOSE_PROFILE = "yahoo-us-equity-latest-completed-daily-close-capture-v1"
YAHOO_TERMS = "https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html"
_NEW_YORK = ZoneInfo("America/New_York")


class _ProviderModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class _Meta(_ProviderModel):
    currency: Literal["USD"]
    symbol: str
    exchangeName: Literal["NCM", "NGM", "NMS", "NYQ"]
    instrumentType: Literal["EQUITY"]
    exchangeTimezoneName: Literal["America/New_York"]
    regularMarketTime: int
    dataGranularity: Literal["1d"]


class _Bar(_ProviderModel):
    close: list[Decimal | int] = Field(min_length=1, max_length=14)


class _Indicators(_ProviderModel):
    quote: list[_Bar] = Field(min_length=1, max_length=1)


class _Split(_ProviderModel):
    date: int


class _Events(_ProviderModel):
    splits: dict[str, _Split] = Field(default_factory=dict, max_length=14)


class _Result(_ProviderModel):
    meta: _Meta
    timestamp: list[int] = Field(min_length=1, max_length=14)
    indicators: _Indicators
    events: _Events = Field(default_factory=_Events)


class _Chart(_ProviderModel):
    result: list[_Result] = Field(min_length=1, max_length=1)
    error: None


class _Response(_ProviderModel):
    chart: _Chart


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def _request_window(source_uri: str, security_id: str) -> tuple[datetime, datetime]:
    uri = urlsplit(source_uri)
    query = parse_qs(
        uri.query, keep_blank_values=True, strict_parsing=True, max_num_fields=4
    )
    if (
        len(source_uri) > 4096
        or uri.scheme != "https"
        or uri.netloc != "query2.finance.yahoo.com"
        or uri.path != f"/v8/finance/chart/{security_id}"
        or uri.fragment
        or not re.fullmatch(r"[A-Z0-9.-]{1,32}", security_id)
        or set(query) != {"period1", "period2", "interval", "events"}
        or any(len(items) != 1 for items in query.values())
        or query["interval"] != ["1d"]
        or query["events"] != ["div,splits,capitalGains"]
        or any(
            not re.fullmatch(r"[0-9]{1,12}", query[key][0])
            for key in ("period1", "period2")
        )
    ):
        raise ValueError("unsupported credential-free Yahoo daily request")
    start, end = (
        datetime.fromtimestamp(int(query[key][0]), _NEW_YORK)
        for key in ("period1", "period2")
    )
    if (
        start.time() != time.min
        or end.time() != time.min
        or not 0 < (end.date() - start.date()).days <= 14
    ):
        raise ValueError("Yahoo daily requests require a bounded local date range")
    return start, end


def validate_yahoo_daily_uri(source_uri: str) -> None:
    try:
        _request_window(source_uri, urlsplit(source_uri).path.rsplit("/", 1)[-1])
    except (ValueError, OverflowError, OSError) as error:
        raise ValueError("unsupported Yahoo daily capture URI") from error


def select_yahoo_daily_close(
    raw: bytes,
    *,
    issuer_id: str,
    security_id: str,
    source_uri: str,
    observation_date: date,
    captured_at: datetime,
) -> CommonShareQuoteV1:
    """Preserve the decimal Close token and capture-time availability.

    Yahoo history is split-adjusted even with yfinance auto_adjust=False. Only
    the latest traded session is supported, on the provider's current share
    basis. Earlier observations need a separate corporate-action profile.
    """
    try:
        if (
            len(raw) > 1024 * 1024
            or captured_at.tzinfo is None
            or captured_at.utcoffset() is None
            or observation_date.weekday() >= 5
        ):
            raise ValueError("quote source exceeds bounds or lacks a supported date")
        start, end = _request_window(source_uri, security_id)
        response = _Response.model_validate(
            json.loads(
                raw,
                parse_float=Decimal,
                parse_constant=_reject_constant,
                object_pairs_hook=_unique_object,
            )
        )
        result = response.chart.result[0]
        meta = result.meta
        timestamps = result.timestamp
        closes = result.indicators.quote[0].close
        dates = [datetime.fromtimestamp(item, _NEW_YORK).date() for item in timestamps]
        market_time = datetime.fromtimestamp(meta.regularMarketTime, UTC)
        if (
            meta.symbol != security_id
            or len(timestamps) != len(closes)
            or timestamps != sorted(set(timestamps))
            or len(set(dates)) != len(dates)
            or any(
                not start.timestamp() <= item < end.timestamp() for item in timestamps
            )
            or dates[-1] != observation_date
            or market_time.astimezone(_NEW_YORK).date() != observation_date
            or market_time > captured_at
            or meta.regularMarketTime < timestamps[-1]
            or any(
                datetime.fromtimestamp(item.date, _NEW_YORK).date() > observation_date
                for item in result.events.splits.values()
            )
        ):
            raise ValueError("quote does not establish the latest traded share basis")
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
            price=Decimal(closes[-1]),
            source_id=YAHOO_CLOSE_SOURCE,
            source_uri=source_uri,
            source_version=YAHOO_CLOSE_PROFILE,
            terms_reference=YAHOO_TERMS,
            content_hash=sha256(raw).hexdigest(),
            as_of=as_of.astimezone(UTC),
            available_at=captured_at,
            captured_at=captured_at,
        )
    except (
        ValueError,
        KeyError,
        TypeError,
        UnicodeError,
        RecursionError,
        OverflowError,
        OSError,
    ) as error:
        if isinstance(error, DilutionError):
            raise
        raise DilutionError(
            "DILUTION_QUOTE_SOURCE_INVALID",
            "retained quote does not reproduce the supported Yahoo latest-session profile",
        ) from error


class YahooDailyCloseProvider:
    def supports(self, source_id: str, source_version: str) -> bool:
        return source_id == YAHOO_CLOSE_SOURCE and source_version == YAHOO_CLOSE_PROFILE

    def reproduce_quote(
        self, raw: bytes, *, request: QuoteSourceRequestV1
    ) -> CommonShareQuoteV1:
        if (
            not self.supports(request.source_id, request.source_version)
            or request.terms_reference != YAHOO_TERMS
        ):
            raise DilutionError(
                "DILUTION_QUOTE_SOURCE_PROFILE_UNSUPPORTED",
                "quote metadata does not match the Yahoo source profile",
            )
        if request.as_of.tzinfo is None or request.as_of.utcoffset() is None:
            raise DilutionError(
                "DILUTION_QUOTE_SOURCE_INVALID", "quote as_of requires a timezone"
            )
        return select_yahoo_daily_close(
            raw,
            issuer_id=request.issuer_id,
            security_id=request.security_id,
            source_uri=request.source_uri,
            observation_date=request.as_of.astimezone(_NEW_YORK).date(),
            captured_at=request.captured_at,
        )
