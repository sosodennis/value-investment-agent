"""Reproduce an unadjusted U.S. common-stock daily close from Twelve Data bytes."""

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

TWELVE_CLOSE_SOURCE = "twelve-data-daily-close"
TWELVE_CLOSE_PROFILE = "twelve-data-us-common-daily-unadjusted-capture-v1"
TWELVE_TERMS = "https://twelvedata.com/terms"
_NEW_YORK = ZoneInfo("America/New_York")
_EXCHANGES = {"XNAS": "NASDAQ", "XNYS": "NYSE"}


class _ProviderModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class _Meta(_ProviderModel):
    symbol: str
    interval: Literal["1day"]
    currency: Literal["USD"]
    exchange_timezone: Literal["America/New_York"]
    exchange: Literal["NASDAQ", "NYSE"]
    mic_code: Literal["XNAS", "XNYS"]
    type: Literal["Common Stock"]


class _DailyBar(_ProviderModel):
    datetime: str
    close: str = Field(max_length=64)


class _Response(_ProviderModel):
    meta: _Meta
    values: tuple[_DailyBar, ...] = Field(min_length=1, max_length=1)
    status: Literal["ok"]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _request_mic(source_uri: str, security_id: str, day: date) -> str:
    uri = urlsplit(source_uri)
    query = parse_qs(
        uri.query, keep_blank_values=True, strict_parsing=True, max_num_fields=9
    )
    expected = {
        "symbol": [security_id],
        "interval": ["1day"],
        "country": ["US"],
        "type": ["Common Stock"],
        "format": ["JSON"],
        "date": [day.isoformat()],
        "adjust": ["none"],
        "dp": ["11"],
    }
    mic = query.get("mic_code", [""])
    if (
        len(source_uri) > 4096
        or uri.scheme != "https"
        or uri.netloc != "api.twelvedata.com"
        or uri.path != "/time_series"
        or uri.fragment
        or not re.fullmatch(r"[A-Z0-9.-]{1,32}", security_id)
        or len(mic) != 1
        or mic[0] not in _EXCHANGES
        or query != {**expected, "mic_code": mic}
    ):
        raise ValueError("quote request differs from the unadjusted U.S. daily profile")
    return mic[0]


def select_twelve_data_daily_close(
    raw: bytes,
    *,
    issuer_id: str,
    security_id: str,
    source_uri: str,
    observation_date: date,
    captured_at: datetime,
) -> CommonShareQuoteV1:
    """Use capture availability and conservative exchange-local calendar age.

    Daily history defaults to split-adjusted prices upstream. This profile requires
    an explicit unadjusted request; the response alone cannot establish that mode.
    """
    try:
        if (
            len(raw) > 1024 * 1024
            or captured_at.tzinfo is None
            or captured_at.utcoffset() is None
        ):
            raise ValueError("quote source exceeds bounds or lacks capture timezone")
        mic = _request_mic(source_uri, security_id, observation_date)
        value = json.loads(raw, object_pairs_hook=_unique_object)
        response = _Response.model_validate_json(json.dumps(value))
        bar = response.values[0]
        if (
            response.meta.symbol != security_id
            or response.meta.mic_code != mic
            or response.meta.exchange != _EXCHANGES[mic]
            or bar.datetime != observation_date.isoformat()
            or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", bar.close)
        ):
            raise ValueError("provider observation differs from its request")
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
            price=Decimal(bar.close),
            source_id=TWELVE_CLOSE_SOURCE,
            source_uri=source_uri,
            source_version=TWELVE_CLOSE_PROFILE,
            terms_reference=TWELVE_TERMS,
            content_hash=sha256(raw).hexdigest(),
            as_of=as_of.astimezone(UTC),
            available_at=captured_at,
            captured_at=captured_at,
        )
    except (ValueError, KeyError, TypeError, UnicodeError, RecursionError) as error:
        if isinstance(error, DilutionError):
            raise
        raise DilutionError(
            "DILUTION_QUOTE_SOURCE_INVALID",
            "retained quote does not reproduce the supported provider profile",
        ) from error


class TwelveDataDailyCloseProvider:
    """Retained-byte adapter; neither requests data nor grants source-use rights."""

    def supports(self, source_id: str, source_version: str) -> bool:
        return (
            source_id == TWELVE_CLOSE_SOURCE and source_version == TWELVE_CLOSE_PROFILE
        )

    def reproduce_quote(
        self, raw: bytes, *, request: QuoteSourceRequestV1
    ) -> CommonShareQuoteV1:
        if (
            not self.supports(request.source_id, request.source_version)
            or request.terms_reference != TWELVE_TERMS
        ):
            raise DilutionError(
                "DILUTION_QUOTE_SOURCE_PROFILE_UNSUPPORTED",
                "quote metadata does not match the Twelve Data source profile",
            )
        if request.as_of.tzinfo is None or request.as_of.utcoffset() is None:
            raise DilutionError(
                "DILUTION_QUOTE_SOURCE_INVALID", "quote as_of requires a timezone"
            )
        return select_twelve_data_daily_close(
            raw,
            issuer_id=request.issuer_id,
            security_id=request.security_id,
            source_uri=request.source_uri,
            observation_date=request.as_of.astimezone(_NEW_YORK).date(),
            captured_at=request.captured_at,
        )
