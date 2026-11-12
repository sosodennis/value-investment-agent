from datetime import UTC, date, datetime
from hashlib import sha256

import pytest

from fundamental_service.equity_dilution import DilutionError
from fundamental_service.quote_sources import (
    NASDAQ_CLOSE_PROFILE,
    NASDAQ_CLOSE_SOURCE,
    NASDAQ_TERMS,
    select_nasdaq_historical_close,
    verify_quote_source,
)
from fundamental_service.serialization import canonical_bytes

ISSUER = "0000789019"
SECURITY = "MSFT"


def _payload(day: date, *, symbol: str = SECURITY, rows=None, close: str = "$521.125"):
    return {
        "data": {
            "symbol": symbol,
            "totalRecords": len(rows) if rows is not None else 1,
            "tradesTable": {
                "headers": {"date": "Date", "close": "Close/Last"},
                "rows": rows
                if rows is not None
                else [{"date": day.strftime("%m/%d/%Y"), "close": close}],
            },
        },
        "status": {"rCode": 200, "bCodeMessage": None, "developerMessage": None},
    }


def _uri(day: date, *, security: str = SECURITY) -> str:
    end = date.fromordinal(day.toordinal() + 1)
    return (
        f"https://api.nasdaq.com/api/quote/{security}/historical"
        f"?assetclass=stocks&fromdate={day.isoformat()}&todate={end.isoformat()}&limit=10"
    )


def _select(day: date, raw: bytes, *, captured_at=None, source_uri=None):
    return select_nasdaq_historical_close(
        raw,
        issuer_id=ISSUER,
        security_id=SECURITY,
        source_uri=source_uri or _uri(day),
        observation_date=day,
        captured_at=captured_at or datetime(2026, 11, 14, tzinfo=UTC),
    )


def test_replays_source_bytes_to_the_same_quote_and_retains_capture_provenance():
    day = date(2026, 11, 12)
    raw = canonical_bytes(_payload(day))

    first = _select(day, raw)
    second = _select(day, raw)

    assert first == second
    assert first.price == 521.125
    assert first.currency == "USD"
    assert first.as_of == datetime(2026, 11, 12, 5, tzinfo=UTC)
    assert first.available_at == first.captured_at == datetime(2026, 11, 14, tzinfo=UTC)
    assert first.content_hash == sha256(raw).hexdigest()
    assert first.source_id == NASDAQ_CLOSE_SOURCE
    assert first.source_version == NASDAQ_CLOSE_PROFILE
    assert first.terms_reference == NASDAQ_TERMS
    verify_quote_source(first, raw)


def test_daily_date_uses_its_timezone_boundary_across_dst():
    day = date(2026, 3, 8)
    raw = canonical_bytes(_payload(day))
    quote = _select(day, raw, captured_at=datetime(2026, 3, 9, 5, tzinfo=UTC))

    assert quote.as_of == datetime(2026, 3, 8, 5, tzinfo=UTC)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"data":{"symbol":"MSFT","symbol":"MSFT"}}',
        canonical_bytes(_payload(date(2026, 11, 12), symbol="AAPL")),
        canonical_bytes(
            {
                **_payload(date(2026, 11, 12)),
                "status": {
                    "rCode": 403,
                    "bCodeMessage": None,
                    "developerMessage": None,
                },
            }
        ),
        canonical_bytes(_payload(date(2026, 11, 12), rows=[])),
        canonical_bytes(
            _payload(
                date(2026, 11, 12),
                rows=[
                    {"date": "11/12/2026", "close": "$521.125"},
                    {"date": "11/12/2026", "close": "$522.00"},
                ],
            )
        ),
        canonical_bytes(_payload(date(2026, 11, 12), close="521.125")),
        canonical_bytes(_payload(date(2026, 11, 12), close="$1,00.00")),
        canonical_bytes(_payload(date(2026, 11, 12), close="$0")),
        b"not-json",
    ],
    ids=(
        "duplicate-json-member",
        "provider-symbol-mismatch",
        "provider-error",
        "empty-history",
        "duplicate-observation-date",
        "currency-not-explicit",
        "malformed-price",
        "non-positive-price",
        "malformed-json",
    ),
)
def test_invalid_provider_observations_are_rejected(raw):
    with pytest.raises(DilutionError) as error:
        _select(date(2026, 11, 12), raw)

    assert error.value.code == "DILUTION_QUOTE_SOURCE_INVALID"


@pytest.mark.parametrize(
    "source_uri",
    [
        "http://api.nasdaq.com/api/quote/MSFT/historical?assetclass=stocks&fromdate=2026-11-12&todate=2026-11-13",
        _uri(date(2026, 11, 12)).replace("MSFT", "AAPL"),
        _uri(date(2026, 11, 12)) + "&assetclass=stocks",
        _uri(date(2026, 11, 12)).replace("&limit=10", "&unknown=1"),
        _uri(date(2026, 11, 12)).replace("&todate=2026-11-13", "&todate=2026-11-12"),
    ],
    ids=(
        "non-tls",
        "different-security",
        "duplicate-parameter",
        "unknown-parameter",
        "empty-range",
    ),
)
def test_unsupported_request_profiles_are_rejected(source_uri):
    with pytest.raises(DilutionError) as error:
        _select(
            date(2026, 11, 12),
            canonical_bytes(_payload(date(2026, 11, 12))),
            source_uri=source_uri,
        )

    assert error.value.code == "DILUTION_QUOTE_SOURCE_INVALID"


def test_incomplete_local_calendar_day_has_a_stable_refusal_code():
    with pytest.raises(DilutionError) as error:
        _select(
            date(2026, 11, 12),
            canonical_bytes(_payload(date(2026, 11, 12))),
            captured_at=datetime(2026, 11, 13, 4, 59, tzinfo=UTC),
        )

    assert error.value.code == "DILUTION_QUOTE_DAY_INCOMPLETE"


def test_retrospective_capture_cannot_claim_earlier_availability():
    day = date(2026, 11, 12)
    capture = datetime(2026, 11, 14, tzinfo=UTC)
    quote = _select(day, canonical_bytes(_payload(day)), captured_at=capture)

    assert quote.as_of < quote.available_at == capture


def test_source_value_and_profile_mismatches_are_distinguished():
    day = date(2026, 11, 12)
    raw = canonical_bytes(_payload(day))
    quote = _select(day, raw)

    with pytest.raises(DilutionError) as changed_value:
        verify_quote_source(quote.model_copy(update={"price": 522}), raw)
    assert changed_value.value.code == "DILUTION_QUOTE_SOURCE_VALUE_MISMATCH"

    unsupported = quote.model_copy(update={"source_version": "nasdaq-profile-v0"})
    with pytest.raises(DilutionError) as changed_profile:
        verify_quote_source(unsupported, raw)
    assert changed_profile.value.code == "DILUTION_QUOTE_SOURCE_PROFILE_UNSUPPORTED"


def test_capture_timestamp_must_include_timezone():
    with pytest.raises(DilutionError) as error:
        _select(
            date(2026, 11, 12),
            canonical_bytes(_payload(date(2026, 11, 12))),
            captured_at=datetime(2026, 11, 13),
        )

    assert error.value.code == "DILUTION_QUOTE_SOURCE_INVALID"
