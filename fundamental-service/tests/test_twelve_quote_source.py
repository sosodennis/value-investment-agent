"""Official-format fixture transcription; these tests grant no real source rights."""

from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from urllib.parse import urlencode

import pytest

from fundamental_service.equity_dilution import DilutionError
from fundamental_service.contracts import ValuationEvidenceReadRequestV1
from fundamental_service.free_source_policy import free_market_source_policy
from fundamental_service.quote_admission import admit_quote_source
from fundamental_service.quote_providers import reproduce_quote_source
from fundamental_service.quote_sources import default_quote_providers
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes
from fundamental_service.twelve_quote_source import (
    TWELVE_CLOSE_PROFILE,
    TWELVE_CLOSE_SOURCE,
    TWELVE_TERMS,
    select_twelve_data_daily_close,
)
from quote_provider_fixtures import publish_synthetic_quote_admission
from test_equity_award_evidence import _with_alternative_quote
from test_preparation_runner import _fixture, _reviewed_candidate

DAY = date(2026, 11, 12)
CAPTURE = datetime(2026, 11, 14, tzinfo=UTC)


def _query():
    return dict(
        symbol="NVEC",
        interval="1day",
        country="US",
        type="Common Stock",
        format="JSON",
        date=DAY.isoformat(),
        adjust="none",
        dp="11",
        mic_code="XNAS",
    )


def _uri(query=None):
    return "https://api.twelvedata.com/time_series?" + urlencode(
        query if query is not None else _query()
    )


def _response():
    return {
        "meta": {
            "symbol": "NVEC",
            "interval": "1day",
            "currency": "USD",
            "exchange_timezone": "America/New_York",
            "exchange": "NASDAQ",
            "mic_code": "XNAS",
            "type": "Common Stock",
        },
        "values": [
            {
                "datetime": DAY.isoformat(),
                "open": "82.00000",
                "high": "83.00000",
                "low": "81.00000",
                "close": "82.12345678901",
                "volume": "12345",
            }
        ],
        "status": "ok",
    }


def _select(raw=None, *, source_uri=None, captured_at=CAPTURE, day=DAY):
    return select_twelve_data_daily_close(
        canonical_bytes(_response()) if raw is None else raw,
        issuer_id="0000724910",
        security_id="NVEC",
        source_uri=source_uri or _uri(),
        observation_date=day,
        captured_at=captured_at,
    )


def test_unadjusted_daily_quote_repeats_exactly_through_registered_provider():
    raw = canonical_bytes(_response())
    first = _select(raw)
    assert first == _select(raw)
    assert first.price == Decimal("82.12345678901")
    assert first.currency == "USD"
    assert first.source_id == TWELVE_CLOSE_SOURCE
    assert first.source_version == TWELVE_CLOSE_PROFILE
    assert first.terms_reference == TWELVE_TERMS
    assert first.content_hash == sha256(raw).hexdigest()
    assert first.as_of == datetime(2026, 11, 12, 5, tzinfo=UTC)
    assert first.available_at == first.captured_at == CAPTURE
    reproduce_quote_source(first, raw, providers=default_quote_providers())


@pytest.mark.parametrize(
    "field,value",
    [
        ("symbol", "AAPL"),
        ("interval", "1min"),
        ("currency", "CAD"),
        ("exchange_timezone", "UTC"),
        ("exchange", "NYSE"),
        ("mic_code", "XNYS"),
        ("type", "Preferred Stock"),
    ],
)
def test_different_instrument_or_bar_metadata_refuses(field, value):
    response = _response()
    response["meta"][field] = value
    with pytest.raises(DilutionError) as error:
        _select(canonical_bytes(response))
    assert error.value.code == "DILUTION_QUOTE_SOURCE_INVALID"


@pytest.mark.parametrize(
    "change",
    (
        {"adjust": None},
        {"adjust": "splits"},
        {"adjust": "all"},
        {"interval": "1min"},
        {"date": "today"},
        {"date": "2026-11-11"},
        {"symbol": "AAPL"},
        {"mic_code": "XLON"},
        {"country": "CA"},
        {"type": "ETF"},
        {"dp": "5"},
        {"apikey": "synthetic-secret"},
    ),
)
def test_unsupported_or_credential_bearing_requests_refuse(change):
    query = {key: value for key, value in {**_query(), **change}.items() if value}
    with pytest.raises(DilutionError) as error:
        _select(source_uri=_uri(query))
    assert error.value.code == "DILUTION_QUOTE_SOURCE_INVALID"
    assert "synthetic-secret" not in str(error.value)


@pytest.mark.parametrize(
    "uri",
    [
        _uri().replace("https://", "http://"),
        _uri().replace("api.twelvedata.com", "other.test"),
        _uri().replace("/time_series?", "/time_series/cross?"),
        _uri() + "&adjust=none",
        _uri() + "#fragment",
        _uri().replace("api.twelvedata.com", "user:secret@api.twelvedata.com"),
    ],
)
def test_wrong_endpoint_duplicate_parameters_or_uri_credentials_refuse(uri):
    with pytest.raises(DilutionError) as error:
        _select(source_uri=uri)
    assert error.value.code == "DILUTION_QUOTE_SOURCE_INVALID"


@pytest.mark.parametrize("close", ("0", "-1", "NaN", "Infinity", "8e1", 82.5))
def test_invalid_or_inexact_price_representation_refuses(close):
    response = _response()
    response["values"][0]["close"] = close
    with pytest.raises(DilutionError) as error:
        _select(canonical_bytes(response))
    assert error.value.code == "DILUTION_QUOTE_SOURCE_INVALID"


def test_missing_wrong_or_ambiguous_daily_observation_refuses():
    wrong_day = _response()
    wrong_day["values"][0]["datetime"] = "2026-11-11"
    duplicate = _response()
    duplicate["values"] *= 2
    missing_currency = _response()
    del missing_currency["meta"]["currency"]
    for raw in (
        canonical_bytes(wrong_day),
        canonical_bytes(duplicate),
        canonical_bytes(missing_currency),
        b'{"status":"ok","status":"error"}',
        b'{"code":429,"message":"Rate limit","status":"error"}',
        b"not-json",
        b"[" * 2000 + b"]" * 2000,
        b"x" * (1024 * 1024 + 1),
    ):
        with pytest.raises(DilutionError) as error:
            _select(raw)
        assert error.value.code == "DILUTION_QUOTE_SOURCE_INVALID"


def test_daily_calendar_boundary_and_dst_do_not_imply_historical_availability():
    with pytest.raises(DilutionError) as error:
        _select(captured_at=datetime(2026, 11, 13, 4, 59, tzinfo=UTC))
    assert error.value.code == "DILUTION_QUOTE_DAY_INCOMPLETE"
    with pytest.raises(DilutionError):
        _select(captured_at=CAPTURE.replace(tzinfo=None))
    day = date(2026, 3, 8)
    response = _response()
    response["values"][0]["datetime"] = day.isoformat()
    query = {**_query(), "date": day.isoformat()}
    quote = _select(
        canonical_bytes(response),
        day=day,
        source_uri=_uri(query),
        captured_at=datetime(2026, 3, 9, 4, tzinfo=UTC),
    )
    assert quote.as_of == datetime(2026, 3, 8, 5, tzinfo=UTC)
    assert quote.available_at == datetime(2026, 3, 9, 4, tzinfo=UTC)


def test_nyse_metadata_and_mic_must_agree():
    response = _response()
    response["meta"].update(exchange="NYSE", mic_code="XNYS")
    quote = _select(
        canonical_bytes(response), source_uri=_uri({**_query(), "mic_code": "XNYS"})
    )
    reproduce_quote_source(
        quote, canonical_bytes(response), providers=default_quote_providers()
    )


def test_changed_quote_profile_terms_or_original_refuses():
    raw = canonical_bytes(_response())
    quote = _select(raw)
    for change in (
        {"price": Decimal("83")},
        {"source_version": "unsupported-v0"},
        {"terms_reference": "https://example.test/unrelated-terms"},
        {"as_of": quote.as_of.replace(hour=6)},
        {"content_hash": "0" * 64},
    ):
        with pytest.raises(DilutionError):
            reproduce_quote_source(
                quote.model_copy(update=change),
                raw,
                providers=default_quote_providers(),
            )


def test_default_policy_refuses_and_explicit_synthetic_admission_reuses(tmp_path):
    raw = canonical_bytes(_response())
    quote = _select(raw)
    refused = admit_quote_source(
        quote,
        raw,
        providers=default_quote_providers(),
        terms=(),
        policy=free_market_source_policy(),
        valuation_at=CAPTURE,
    )
    assert refused.status == "refused"
    assert refused.issue_codes == ("SOURCE_USE_POLICY_MISSING",)
    store = ArtifactStore(tmp_path)
    first = publish_synthetic_quote_admission(
        quote, raw, valuation_at=CAPTURE, artifacts=store
    )
    before = {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.iterdir()
        if p.is_file()
    }
    repeated = publish_synthetic_quote_admission(
        quote, raw, valuation_at=CAPTURE, artifacts=ArtifactStore(tmp_path)
    )
    assert first == repeated
    assert before == {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.iterdir()
        if p.is_file()
    }
    changed = _response()
    changed["values"][0]["close"] = "83"
    with pytest.raises(DilutionError):
        reproduce_quote_source(
            quote, canonical_bytes(changed), providers=default_quote_providers()
        )


@pytest.mark.parametrize("consumer", ("serving", "canary"))
def test_released_twelve_data_fixture_reaches_the_official_composer(tmp_path, consumer):
    fixture = _fixture(tmp_path)
    day = date(2026, 2, 27)
    symbol = fixture.snapshot.identity.security_id
    response = _response()
    response["meta"]["symbol"] = symbol
    response["values"][0].update(datetime=day.isoformat(), close="10")
    raw = canonical_bytes(response)
    quote = select_twelve_data_daily_close(
        raw,
        issuer_id=fixture.snapshot.identity.issuer_id,
        security_id=symbol,
        source_uri=_uri({**_query(), "symbol": symbol, "date": day.isoformat()}),
        observation_date=day,
        captured_at=datetime(2026, 2, 28, 5, tzinfo=UTC),
    )
    _with_alternative_quote(fixture, quote=quote, raw=raw)
    if consumer == "canary":
        candidate, canary = _reviewed_candidate(fixture)
        first = canary.validate(candidate.manifest, candidate.verification)
        assert first == canary.validate(candidate.manifest, candidate.verification)
        assert first.candidate_manifest_digest == candidate.manifest.manifest_digest
    else:
        request = ValuationEvidenceReadRequestV1(
            contract_version="fundamental.v1",
            snapshot_id=fixture.snapshot.snapshot_id,
            data_release_manifest_digest=fixture.manifest.manifest_digest,
            model_id="fcff_dcf",
        )
        first = fixture.application.prepare_valuation(request)
        assert first == fixture.application.prepare_valuation(request)
        assert first.status == "prepared"
        assert first.quality_status.value == "provisional"
        assert first.equity_dilution.incremental_shares == Decimal(10)
        assert first.input.assumptions.capital_bridge.diluted_shares == Decimal(120)
