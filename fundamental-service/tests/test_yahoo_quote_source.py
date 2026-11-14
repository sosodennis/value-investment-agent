"""Synthetic Yahoo chart responses; these tests confer no source-use rights."""

from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json

import pytest

from fundamental_service.equity_dilution import CommonShareQuoteV1, DilutionError
from fundamental_service.quote_sources import verify_quote_source

DAY = date(2026, 11, 13)
CAPTURE = datetime(2026, 11, 14, 12, tzinfo=UTC)
SOURCE = "yahoo-chart-daily-close"
PROFILE = "yahoo-us-equity-latest-completed-daily-close-capture-v1"
TERMS = "https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html"
URI = (
    "https://query2.finance.yahoo.com/v8/finance/chart/NVEC"
    "?period1=1794546000&period2=1794632400&interval=1d&events=div,splits,capitalGains"
)


def response():
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "currency": "USD",
                        "symbol": "NVEC",
                        "exchangeName": "NCM",
                        "instrumentType": "EQUITY",
                        "exchangeTimezoneName": "America/New_York",
                        "regularMarketTime": 1794603600,
                        "dataGranularity": "1d",
                    },
                    "timestamp": [1794580200],
                    "indicators": {
                        "quote": [{"close": [81.05000305175781]}],
                        "adjclose": [{"adjclose": [70.0]}],
                    },
                }
            ],
            "error": None,
        }
    }


def raw_response(value=None):
    return json.dumps(response() if value is None else value).encode()


def expected_quote(raw):
    return CommonShareQuoteV1(
        issuer_id="0000724910",
        security_id="NVEC",
        currency="USD",
        price=Decimal("81.05000305175781"),
        source_id=SOURCE,
        source_version=PROFILE,
        source_uri=URI,
        terms_reference=TERMS,
        content_hash=sha256(raw).hexdigest(),
        as_of=datetime(2026, 11, 13, 5, tzinfo=UTC),
        available_at=CAPTURE,
        captured_at=CAPTURE,
    )


def test_retained_yahoo_latest_close_reproduces_through_the_formal_registry():
    raw = raw_response()
    quote = expected_quote(raw)
    verify_quote_source(quote, raw)
    verify_quote_source(quote, raw)


def select(raw=None, **changes):
    from fundamental_service.yahoo_quote_source import select_yahoo_daily_close

    return select_yahoo_daily_close(
        raw_response() if raw is None else raw,
        **{
            "issuer_id": "0000724910",
            "security_id": "NVEC",
            "source_uri": URI,
            "observation_date": DAY,
            "captured_at": CAPTURE,
            **changes,
        },
    )


def test_exact_decimal_token_is_retained_without_adjusted_close_or_rounding():
    raw = raw_response()
    assert select(raw) == expected_quote(raw)
    assert select(raw).price != Decimal("70")


@pytest.mark.parametrize(
    "field,value",
    [
        ("currency", "CAD"),
        ("symbol", "AAPL"),
        ("exchangeName", "LSE"),
        ("instrumentType", "ETF"),
        ("exchangeTimezoneName", "UTC"),
        ("dataGranularity", "1m"),
        ("regularMarketTime", 1794517200),
        ("regularMarketTime", 1794690000),
    ],
)
def test_identity_frequency_and_historical_split_basis_must_match(field, value):
    value_response = response()
    value_response["chart"]["result"][0]["meta"][field] = value
    with pytest.raises(DilutionError) as error:
        select(raw_response(value_response))
    assert error.value.code == "DILUTION_QUOTE_SOURCE_INVALID"


@pytest.mark.parametrize(
    "uri",
    [
        URI.replace("https://", "http://"),
        URI.replace("query2.finance.yahoo.com", "other.test"),
        URI.replace("NVEC", "AAPL"),
        URI + "#fragment",
        URI + "&interval=1d",
        URI + "&crumb=secret",
        URI.replace("query2.finance.yahoo.com", "user:secret@query2.finance.yahoo.com"),
        URI.replace("interval=1d", "interval=1h"),
        URI.replace("period1=1794546000", "period1=1794546001"),
        URI.replace("period2=1794632400", "period2=1794546000"),
        URI.replace("events=div,splits,capitalGains", "events=div"),
    ],
)
def test_only_the_bounded_credential_free_daily_request_profile_is_supported(uri):
    with pytest.raises(DilutionError) as error:
        select(source_uri=uri)
    assert error.value.code == "DILUTION_QUOTE_SOURCE_INVALID"
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate-day",
        "unordered",
        "outside-request",
        "null",
        "misaligned",
        "two-quotes",
        "future-split",
    ],
)
def test_malformed_or_ambiguous_bars_and_later_split_events_refuse(mutation):
    value = response()
    result = value["chart"]["result"][0]
    if mutation == "duplicate-day":
        result["timestamp"].append(1794580201)
        result["indicators"]["quote"][0]["close"].append(82)
    elif mutation == "unordered":
        result["timestamp"] = [1794580200, 1794493800]
        result["indicators"]["quote"][0]["close"] = [81, 82]
    elif mutation == "outside-request":
        result["timestamp"] = [1794493800]
    elif mutation == "null":
        result["indicators"]["quote"][0]["close"] = [None]
    elif mutation == "misaligned":
        result["indicators"]["quote"][0]["close"] = []
    elif mutation == "two-quotes":
        result["indicators"]["quote"].append({"close": [82]})
    else:
        result["events"] = {"splits": {"1794839400": {"date": 1794839400}}}
    with pytest.raises(DilutionError) as error:
        select(raw_response(value))
    assert error.value.code == "DILUTION_QUOTE_SOURCE_INVALID"


@pytest.mark.parametrize(
    "price", [0, -1, "81.05", True, None, float("nan"), float("inf")]
)
def test_missing_nonpositive_and_non_numeric_prices_never_become_zero(price):
    value = response()
    value["chart"]["result"][0]["indicators"]["quote"][0]["close"] = [price]
    with pytest.raises(DilutionError) as error:
        select(raw_response(value))
    assert error.value.code == "DILUTION_QUOTE_SOURCE_INVALID"


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        b'{"chart":{},"chart":{}}',
        b'{"chart":{"result":[],"error":null}}',
        b"x" * (1024 * 1024 + 1),
    ],
)
def test_bounded_json_requires_one_successful_unambiguous_result(raw):
    with pytest.raises(DilutionError) as error:
        select(raw)
    assert error.value.code == "DILUTION_QUOTE_SOURCE_INVALID"


def test_no_availability_backdating_or_incomplete_day_admission():
    with pytest.raises(DilutionError) as error:
        select(captured_at=datetime(2026, 11, 14, 4, 59, tzinfo=UTC))
    assert error.value.code == "DILUTION_QUOTE_DAY_INCOMPLETE"
    with pytest.raises(DilutionError):
        select(captured_at=datetime(2026, 11, 14))


def test_changed_price_or_declared_profile_cannot_replay():
    raw = raw_response()
    quote = expected_quote(raw)
    for change, code in (
        ({"price": Decimal("81.05")}, "DILUTION_QUOTE_SOURCE_VALUE_MISMATCH"),
        (
            {"source_version": "yahoo-history-v0"},
            "DILUTION_QUOTE_SOURCE_PROFILE_UNSUPPORTED",
        ),
        ({"content_hash": "0" * 64}, "DILUTION_QUOTE_SOURCE_MISMATCH"),
    ):
        with pytest.raises(DilutionError) as error:
            verify_quote_source(quote.model_copy(update=change), raw)
        assert error.value.code == code


def test_yahoo_reproduction_does_not_grant_a_source_use_permission():
    from fundamental_service.free_source_policy import free_market_source_policy
    from fundamental_service.quote_admission import admit_quote_source
    from fundamental_service.quote_sources import default_quote_providers

    raw = raw_response()
    admission = admit_quote_source(
        expected_quote(raw),
        raw,
        providers=default_quote_providers(),
        terms=(),
        policy=free_market_source_policy(),
        valuation_at=CAPTURE,
    )
    assert admission.status == "refused"
    assert admission.issue_codes == ("SOURCE_USE_POLICY_MISSING",)
    assert admission.source_check is not None


def test_decimal_integer_close_is_supported_without_binary_conversion():
    value = response()
    value["chart"]["result"][0]["indicators"]["quote"][0]["close"] = [81]
    assert select(raw_response(value)).price == Decimal("81")
