import hashlib
import json
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path

import pytest
from fundamental_service.public_source import (
    PUBLIC_SOURCE_SPECS,
    PublicSourceAdapter,
    fundamental_source_register,
)
from fundamental_service.snapshots import SnapshotError
from treasury_source_fixtures import ALFRED_CSV, ALFRED_URI, TREASURY_URI, TREASURY_XML


class FakeResponse:
    status = 200

    def __init__(self, payload: bytes, media_type: str = "text/csv"):
        self._payload = payload
        self.headers = Message()
        self.headers["Content-Type"] = media_type

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_all_declared_free_sources_have_allowlisted_capture_contract():
    requests: list[str] = []

    def opener(request, timeout):
        requests.append(request.full_url)
        if "markets.newyorkfed.org" in request.full_url:
            return FakeResponse(
                b'{"refRates":[{"effectiveDate":"2025-01-03","type":"SOFR",'
                b'"percentRate":4.33,"revisionIndicator":""}]}',
                "application/json",
            )
        if "home.treasury.gov" in request.full_url:
            return FakeResponse(TREASURY_XML, "application/xml")
        if "alfred.stlouisfed.org" in request.full_url:
            return FakeResponse(ALFRED_CSV)
        if "api.bls.gov" in request.full_url:
            return FakeResponse(json.dumps({"data": []}).encode(), "application/json")
        return FakeResponse(b"observation,value\n2025-01-01,1\n")

    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        opener=opener,
        sleep=lambda _seconds: None,
        min_interval_seconds=0,
    )
    for spec in PUBLIC_SOURCE_SPECS:
        uri = spec.uri_prefix
        if spec.source_id == "alfred-vintage":
            uri = ALFRED_URI
        if spec.source_id == "treasury-yields":
            uri = TREASURY_URI
        if spec.source_id == "new-york-fed-sofr":
            uri += "?startDate=2025-01-03&endDate=2025-01-03"
        source = adapter.capture(
            spec.source_id,
            uri,
            available_at=(
                None
                if spec.source_id
                in {
                    "new-york-fed-sofr",
                    "bea-gdp-release",
                    "bea-nipa-archive",
                    "treasury-yields",
                    "alfred-vintage",
                }
                else datetime(2025, 1, 3, tzinfo=timezone.utc)
            ),
        )
        assert source.source_id == spec.source_id
        assert source.role == spec.role
        if spec.source_id == "new-york-fed-sofr":
            assert source.available_at == source.captured_at
            assert source.publication_at is None
    assert len(requests) == len(PUBLIC_SOURCE_SPECS)
    assert (
        fundamental_source_register().require("sec-companyfacts").source_id
        == "sec-companyfacts"
    )


def test_expansion_source_register_covers_each_governed_family_boundary():
    register = fundamental_source_register()
    for source_id in (
        "fdic-bankfind",
        "ffiec-cdr",
        "naic-statutory-filings",
        "nareit-definitions",
        "ferc-public-data",
        "state-utility-orders",
        "eia-open-data",
        "usgs-commodity-statistics",
        "usda-nass-quickstats",
        "fda-drugs",
        "clinicaltrials-api",
        "ifrs-taxonomy",
    ):
        assert register.require(source_id).permitted


def test_public_source_rejects_unregistered_uri_before_network():
    calls = []
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        opener=lambda *_args, **_kwargs: calls.append(True),
    )
    with pytest.raises(SnapshotError) as error:
        adapter.capture(
            "fred-observations",
            "https://example.test/fred.csv",
            available_at=datetime(2025, 1, 3, tzinfo=timezone.utc),
        )
    assert error.value.code == "SOURCE_URI_NOT_ALLOWED"
    assert calls == []


def test_public_source_rejects_custom_port_before_network():
    calls = []
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        opener=lambda *_args, **_kwargs: calls.append(True),
    )
    with pytest.raises(SnapshotError) as error:
        adapter.capture(
            "fred-observations",
            "https://fred.stlouisfed.org:443/graph/fredgraph.csv?id=DGS10",
            available_at=datetime(2025, 1, 3, tzinfo=timezone.utc),
        )
    assert error.value.code == "SOURCE_URI_NOT_ALLOWED"
    assert calls == []


@pytest.mark.parametrize(
    "uri",
    (
        "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json.evil?startDate=2025-01-03&endDate=2025-01-03",
        "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json?startDate=2025-02-01&endDate=2025-01-03",
        "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json?startDate=2025-01-01&endDate=2025-01-03",
        "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json?startDate=2025-99-03&endDate=2025-99-03",
        "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json?startDate=2025-01-03&endDate=2025-01-03&foo=bar",
    ),
)
def test_sofr_source_rejects_unbound_or_invalid_query_before_network(uri: str):
    calls = []
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        opener=lambda *_args, **_kwargs: calls.append(True),
    )
    with pytest.raises(SnapshotError):
        adapter.capture("new-york-fed-sofr", uri)
    assert calls == []


def test_sofr_source_refuses_caller_backdated_availability():
    calls = []
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        opener=lambda *_args, **_kwargs: calls.append(True),
        min_interval_seconds=0,
    )
    with pytest.raises(SnapshotError) as error:
        adapter.capture(
            "new-york-fed-sofr",
            "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json?startDate=2025-01-03&endDate=2025-01-03",
            available_at=datetime(2025, 1, 3, tzinfo=timezone.utc),
        )
    assert error.value.code == "SOURCE_AVAILABILITY_UNVERIFIED"
    assert calls == []


def test_sofr_source_refuses_unverified_publication_timestamp():
    calls = []
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        opener=lambda *_args, **_kwargs: calls.append(True),
        min_interval_seconds=0,
    )
    with pytest.raises(SnapshotError) as error:
        adapter.capture(
            "new-york-fed-sofr",
            "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json?startDate=2025-01-03&endDate=2025-01-03",
            publication_at=datetime(2025, 1, 3, tzinfo=timezone.utc),
        )
    assert error.value.code == "SOURCE_AVAILABILITY_UNVERIFIED"
    assert calls == []


@pytest.mark.parametrize(
    ("source_id", "uri"),
    (
        (
            "bea-gdp-release",
            "https://www.bea.gov/news/2025/gross-domestic-product-test",
        ),
        (
            "bea-nipa-archive",
            "https://apps.bea.gov/HistData/Files/Releases/GDP_and_PI/2024/Q4/Third_March-28-2025/Section1all_xls.xlsx",
        ),
    ),
)
def test_bea_capture_cannot_claim_historical_availability_before_paired_reproduction(
    source_id: str, uri: str
):
    calls = []
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        opener=lambda *_args, **_kwargs: calls.append(True),
    )
    with pytest.raises(SnapshotError) as error:
        adapter.capture(
            source_id, uri, available_at=datetime(2025, 1, 3, tzinfo=timezone.utc)
        )
    assert error.value.code == "SOURCE_AVAILABILITY_UNVERIFIED"
    assert calls == []


def test_sofr_capture_records_retrieval_time_without_claiming_publication_time():
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        opener=lambda *_args, **_kwargs: FakeResponse(
            b'{"refRates":[{"effectiveDate":"2025-01-03","type":"SOFR",'
            b'"percentRate":4.33,"revisionIndicator":""}]}',
            "application/json",
        ),
        min_interval_seconds=0,
    )
    source = adapter.capture(
        "new-york-fed-sofr",
        "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json?startDate=2025-01-03&endDate=2025-01-03",
    )
    assert source.available_at == source.captured_at
    assert source.publication_at is None


def test_sofr_capture_refuses_invalid_observation_before_returning_a_source():
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        opener=lambda *_args, **_kwargs: FakeResponse(
            b'{"refRates":[]}', "application/json"
        ),
        min_interval_seconds=0,
    )
    with pytest.raises(SnapshotError) as error:
        adapter.capture(
            "new-york-fed-sofr",
            "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json?startDate=2025-01-03&endDate=2025-01-03",
        )
    assert error.value.code == "SOFR_SOURCE_INVALID"


@pytest.mark.parametrize(
    "uri",
    (
        "https://fred.stlouisfed.org/graph/fredgraph.csv.evil?id=DGS10",
        "https://fred.stlouisfed.org/graph/fredgraph.csv/evil?id=DGS10",
    ),
)
def test_public_source_rejects_fred_path_siblings_before_network(uri: str):
    calls = []
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        opener=lambda *_args, **_kwargs: calls.append(True),
    )
    with pytest.raises(SnapshotError) as error:
        adapter.capture(
            "fred-observations",
            uri,
            available_at=datetime(2025, 1, 3, tzinfo=timezone.utc),
        )
    assert error.value.code == "SOURCE_URI_NOT_ALLOWED"
    assert calls == []


def test_public_source_rate_limit_is_explicit_after_bounded_retries():
    attempts = 0

    def opener(_request, timeout):
        nonlocal attempts
        attempts += 1
        raise OSError("offline")

    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        opener=opener,
        max_attempts=2,
        min_interval_seconds=0,
        sleep=lambda _seconds: None,
    )
    with pytest.raises(SnapshotError) as error:
        adapter.capture(
            "fred-observations",
            "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10",
            available_at=datetime(2025, 1, 3, tzinfo=timezone.utc),
        )
    assert error.value.code == "SOURCE_UNAVAILABLE"
    assert attempts == 2


def test_alfred_requires_vintage_date():
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        opener=lambda *_args, **_kwargs: FakeResponse(b"value\n"),
    )
    with pytest.raises(SnapshotError) as error:
        adapter.capture(
            "alfred-vintage",
            "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=DGS10",
            available_at=datetime(2025, 1, 3, tzinfo=timezone.utc),
        )
    assert error.value.code == "SOURCE_VINTAGE_REQUIRED"


@pytest.mark.parametrize("source_id", ("treasury-yields", "alfred-vintage"))
@pytest.mark.parametrize("timestamp", ("available_at", "publication_at", "captured_at"))
def test_treasury_capture_refuses_caller_timestamp_before_network(source_id, timestamp):
    calls = []
    uri = (
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
        "pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value=2025"
        if source_id == "treasury-yields"
        else "https://alfred.stlouisfed.org/graph/alfredgraph.csv"
        "?id=DGS10&cosd=2025-03-28&coed=2025-03-31&vintage_date=2025-03-31"
    )
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        opener=lambda *_args, **_kwargs: calls.append(True),
    )
    with pytest.raises(SnapshotError) as error:
        adapter.capture(
            source_id, uri, **{timestamp: datetime(2025, 3, 31, tzinfo=timezone.utc)}
        )
    assert error.value.code == "SOURCE_AVAILABILITY_UNVERIFIED"
    assert calls == []


@pytest.mark.parametrize(
    "source_id,uri",
    (
        ("treasury-yields", TREASURY_URI.replace("=2025", "=25")),
        (
            "treasury-yields",
            TREASURY_URI.replace(
                "daily_treasury_yield_curve", "daily_treasury_real_yield_curve"
            ),
        ),
        ("treasury-yields", TREASURY_URI + "&field_tdr_date_value=2024"),
        ("treasury-yields", TREASURY_URI + "#ignored"),
        ("alfred-vintage", ALFRED_URI.replace("DGS10", "DGS2")),
        ("alfred-vintage", ALFRED_URI.replace("cosd=2025-03-28", "cosd=2025-04-01")),
        (
            "alfred-vintage",
            ALFRED_URI.replace("vintage_date=2025-03-31", "vintage_date=2025-03-27"),
        ),
        ("alfred-vintage", ALFRED_URI + "&vintage_date=2025-03-31"),
        ("alfred-vintage", ALFRED_URI.replace("coed=2025-03-31&", "")),
        ("alfred-vintage", ALFRED_URI + "&unbound=1"),
    ),
)
def test_treasury_source_queries_are_validated_before_network(source_id, uri):
    calls = []
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        opener=lambda *_args, **_kwargs: calls.append(True),
    )
    with pytest.raises(SnapshotError) as error:
        adapter.capture(source_id, uri)
    assert error.value.code == "SOURCE_QUERY_INVALID"
    assert calls == []


@pytest.mark.parametrize("alfred", (False, True))
def test_treasury_capture_uses_proven_availability_without_inventing_publication(
    alfred,
):
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        opener=lambda *_args, **_kwargs: FakeResponse(
            ALFRED_CSV if alfred else TREASURY_XML,
            "text/csv" if alfred else "application/xml",
        ),
    )
    source = adapter.capture(
        "alfred-vintage" if alfred else "treasury-yields",
        ALFRED_URI if alfred else TREASURY_URI,
    )
    assert source.captured_at is not None
    assert source.publication_at is None
    assert source.available_at == (
        datetime(2025, 4, 1, 4, tzinfo=timezone.utc) if alfred else source.captured_at
    )


def test_alfred_capture_rejects_payload_from_a_different_vintage():
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        opener=lambda *_args, **_kwargs: FakeResponse(
            ALFRED_CSV.replace(b"20250331", b"20250401")
        ),
    )
    with pytest.raises(SnapshotError) as error:
        adapter.capture("alfred-vintage", ALFRED_URI)
    assert error.value.code == "ALFRED_SOURCE_INVALID"


def test_captured_macro_and_vintage_fixtures_have_stable_hashes():
    fixture_root = Path(__file__).parent / "fixtures"
    manifest = json.loads(
        (fixture_root / "public-sources" / "manifest.json").read_text()
    )
    records = {record["path"]: record for record in manifest["sources"]}
    assert {record["source_id"] for record in records.values()} >= {
        "treasury-yields",
        "fred-observations",
        "alfred-vintage",
        "bls-public-api",
        "fdic-bankfind",
    }
    vintage = next(
        record for record in records.values() if record["source_id"] == "alfred-vintage"
    )
    assert "vintage_date=2025-01-03" in vintage["uri"]
    for path, record in records.items():
        payload = (fixture_root / path).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == record["sha256"]
        assert record["http_status"] == 200
