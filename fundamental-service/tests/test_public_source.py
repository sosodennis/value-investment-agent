import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from email.message import Message
from pathlib import Path

import pytest
from fundamental_service.public_source import (
    PublicSourceAdapter,
    fundamental_source_register,
)
from fundamental_service.public_source_catalog import PUBLIC_SOURCE_SPECS
from fundamental_service.source_capture import (
    ProvidedAvailabilityCaptureProfile,
    PublicSourceRegistration,
    PublicSourceSpec,
    ReproducedMacroCaptureProfile,
    SourceCaptureTimes,
)
from fundamental_service.contracts import SourceRole
from fundamental_service.macro_series import (
    MacroObservationV1,
    MacroSeriesProviderPort,
    MacroSeriesVintageV1,
    reproduce_macro_vintage,
)
from fundamental_service.snapshots import LegalSource, SnapshotError, SourceRegister
from fundamental_service.source_evidence import RetainedSourceV1, SourceArtifactV1
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


class AlternativeRateProvider:
    provider_id = "alternative-rate-provider"

    def supports(self, series_id):
        return series_id == "test.policy_rate"

    def reproduce_vintage(self, *, series_id, sources):
        source = sources[0]
        period, raw_value = source.content.decode("ascii").strip().split(",")
        observed_on = date.fromisoformat(period)
        digest = hashlib.sha256(source.content).hexdigest()
        artifact = SourceArtifactV1(
            source_id=source.source_id,
            uri=source.uri,
            source_version=source.source_version,
            terms_reference=source.terms_reference,
            captured_at=source.captured_at,
            content_sha256=digest,
        )
        return MacroSeriesVintageV1.build(
            provider_id=self.provider_id,
            series_id=series_id,
            frequency="daily",
            unit="percent",
            source_version="alternative-rate-v1",
            available_at=source.captured_at,
            captured_at=source.captured_at,
            artifacts=(artifact,),
            observations=(
                MacroObservationV1(
                    series_id=series_id,
                    period_start=observed_on,
                    period_end=observed_on,
                    value=Decimal(raw_value),
                    unit="percent",
                    source_sha256=digest,
                ),
            ),
        )


@pytest.mark.parametrize("raw_value", ("3.5", "4.125"))
def test_alternative_provider_registers_without_transport_changes(raw_value):
    provider: MacroSeriesProviderPort = AlternativeRateProvider()
    spec = PublicSourceSpec(
        source_id="alternative-rate",
        role=SourceRole.MACRO,
        uri_prefix="https://rates.example.test/v1/",
        terms_reference="https://rates.example.test/terms",
    )
    registration = PublicSourceRegistration(
        spec,
        ReproducedMacroCaptureProfile(
            provider=provider,
            series_id="test.policy_rate",
            source_version="alternative-rate-v1",
            validate_uri=lambda uri: None,
        ),
    )
    source = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        registrations=(registration,),
        opener=lambda *_args, **_kwargs: FakeResponse(
            f"2025-01-01,{raw_value}\n".encode("ascii"), "text/plain"
        ),
        min_interval_seconds=0,
    ).capture("alternative-rate", "https://rates.example.test/v1/today")
    vintage = reproduce_macro_vintage(
        provider,
        series_id="test.policy_rate",
        sources=(
            RetainedSourceV1(
                source_id=source.source_id,
                uri=source.uri,
                source_version="alternative-rate-v1",
                terms_reference=spec.terms_reference,
                content=source.content,
                captured_at=source.captured_at,
            ),
        ),
    )
    assert vintage.provider_id == provider.provider_id
    assert vintage.observations[0].value == Decimal(raw_value)
    assert (
        vintage.observations[0].source_sha256
        == hashlib.sha256(source.content).hexdigest()
    )
    assert source.available_at == source.captured_at


def test_registered_source_requires_one_matching_injected_profile_before_io():
    calls = []
    registration = PublicSourceRegistration(
        PublicSourceSpec(
            source_id="alternative-rate",
            role=SourceRole.MACRO,
            uri_prefix="https://rates.example.test/v1/",
            terms_reference="https://rates.example.test/terms",
        ),
        ReproducedMacroCaptureProfile(
            provider=AlternativeRateProvider(),
            series_id="test.policy_rate",
            source_version="alternative-rate-v1",
            validate_uri=lambda _uri: None,
        ),
    )
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        registrations=(registration,),
        opener=lambda *_args, **_kwargs: calls.append(True),
    )
    with pytest.raises(SnapshotError) as error:
        adapter.capture(
            "alternative-rate",
            "https://other.example.test/v1/today",
        )
    assert error.value.code == "SOURCE_URI_NOT_ALLOWED"
    assert calls == []


def test_malformed_endpoint_port_is_a_typed_source_refusal():
    calls = []
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        opener=lambda *_args, **_kwargs: calls.append(True),
    )
    with pytest.raises(SnapshotError) as error:
        adapter.capture(
            "treasury-yields",
            TREASURY_URI.replace("home.treasury.gov", "home.treasury.gov:invalid"),
        )
    assert error.value.code == "SOURCE_URI_NOT_ALLOWED"
    assert calls == []


def test_malformed_source_registration_uri_fails_configuration():
    with pytest.raises(ValueError, match="registration boundary"):
        PublicSourceSpec(
            source_id="malformed-provider",
            role=SourceRole.MACRO,
            uri_prefix="https://rates.example.test:invalid/v1/",
            terms_reference="https://rates.example.test/terms",
        )


def test_sofr_capture_missing_query_member_is_a_typed_refusal_before_io():
    calls = []
    uri = "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json?startDate=2025-03-28"
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        opener=lambda *_args, **_kwargs: calls.append(True),
    )
    with pytest.raises(SnapshotError) as error:
        adapter.capture("new-york-fed-sofr", uri)
    assert error.value.code == "SOURCE_QUERY_INVALID"
    assert calls == []


def test_empty_registrations_do_not_load_default_sources():
    calls = []
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        registrations=(),
        opener=lambda *_args, **_kwargs: calls.append(True),
    )
    with pytest.raises(SnapshotError) as error:
        adapter.capture("treasury-yields", TREASURY_URI)
    assert error.value.code == "SOURCE_NOT_REGISTERED"
    assert calls == []


def test_duplicate_source_registration_fails_configuration():
    registration = PublicSourceRegistration(
        PUBLIC_SOURCE_SPECS[0], ProvidedAvailabilityCaptureProfile()
    )
    with pytest.raises(ValueError, match="repeat a source identity"):
        PublicSourceAdapter(
            user_agent="value-agent test@example.com",
            registrations=(registration, registration),
        )


@pytest.mark.parametrize("mismatch", ("role", "terms_reference"))
def test_capture_registration_must_match_legal_register_before_io(mismatch):
    spec = PUBLIC_SOURCE_SPECS[0]
    calls = []
    legal = LegalSource(
        spec.source_id,
        SourceRole.REFERENCE if mismatch == "role" else spec.role,
        "https://terms.example.test/"
        if mismatch == "terms_reference"
        else spec.terms_reference,
        "indefinite",
    )
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        source_register=SourceRegister((legal,)),
        registrations=(
            PublicSourceRegistration(spec, ProvidedAvailabilityCaptureProfile()),
        ),
        opener=lambda *_args, **_kwargs: calls.append(True),
    )
    with pytest.raises(SnapshotError) as error:
        adapter.capture(spec.source_id, TREASURY_URI)
    assert error.value.code == "SOURCE_REGISTRATION_MISMATCH"
    assert calls == []


def test_unsupported_injected_macro_series_fails_before_io():
    calls = []
    spec = PUBLIC_SOURCE_SPECS[0]
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        registrations=(
            PublicSourceRegistration(
                spec,
                ReproducedMacroCaptureProfile(
                    AlternativeRateProvider(),
                    "test.unsupported_rate",
                    "alternative-rate-v1",
                    lambda _uri: None,
                ),
            ),
        ),
        opener=lambda *_args, **_kwargs: calls.append(True),
    )
    with pytest.raises(SnapshotError) as error:
        adapter.capture(spec.source_id, TREASURY_URI)
    assert error.value.code == "SOURCE_PROFILE_UNSUPPORTED"
    assert calls == []


@pytest.mark.parametrize("timestamp", ("available_at", "publication_at", "captured_at"))
def test_naive_caller_timestamps_fail_before_io(timestamp):
    calls = []
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        opener=lambda *_args, **_kwargs: calls.append(True),
    )
    with pytest.raises(SnapshotError) as error:
        adapter.capture(
            "fred-observations",
            "https://fred.stlouisfed.org/graph/fredgraph.csv",
            **{timestamp: datetime(2025, 1, 1)},
        )
    assert error.value.code == "SOURCE_TIMESTAMP_TIMEZONE_REQUIRED"
    assert calls == []


@pytest.mark.parametrize(
    ("invalid_time", "expected_code"),
    (
        ("naive", "SOURCE_TIMESTAMP_TIMEZONE_REQUIRED"),
        ("capture_future", "SOURCE_CAPTURE_TIME_MISMATCH"),
        ("available_future", "SOURCE_TIMESTAMP_ORDER_INVALID"),
        ("publication_future", "SOURCE_TIMESTAMP_ORDER_INVALID"),
    ),
)
def test_transport_rejects_inconsistent_injected_profile_times(
    invalid_time, expected_code
):
    class InvalidTimeProfile:
        def validate_request(self, request):
            pass

        def resolve_capture(self, request, response):
            now = response.retrieved_at
            later = now + timedelta(days=1)
            return SourceCaptureTimes(
                now.replace(tzinfo=None)
                if invalid_time == "naive"
                else later
                if invalid_time == "available_future"
                else now,
                later if invalid_time == "publication_future" else None,
                later if invalid_time == "capture_future" else now,
            )

    spec = PUBLIC_SOURCE_SPECS[0]
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        registrations=(PublicSourceRegistration(spec, InvalidTimeProfile()),),
        opener=lambda *_args, **_kwargs: FakeResponse(b"retained source bytes"),
    )
    with pytest.raises(SnapshotError) as error:
        adapter.capture(spec.source_id, TREASURY_URI)
    assert error.value.code == expected_code


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
        if spec.source_id == "damodaran-reference":
            uri += "archives/betas24.xls"
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
                    "damodaran-reference",
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


@pytest.mark.parametrize("timestamp", ["available_at", "publication_at", "captured_at"])
def test_reference_capture_rejects_caller_timestamp_overrides_before_network(timestamp):
    calls = []
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        opener=lambda *_args, **_kwargs: calls.append(True),
    )
    with pytest.raises(SnapshotError) as error:
        adapter.capture(
            "damodaran-reference",
            "https://pages.stern.nyu.edu/~adamodar/pc/archives/betas24.xls",
            **{timestamp: datetime(2025, 1, 1, tzinfo=timezone.utc)},
        )
    assert error.value.code == "SOURCE_AVAILABILITY_UNVERIFIED"
    assert calls == []


def test_reference_capture_uses_actual_capture_without_claiming_publication():
    adapter = PublicSourceAdapter(
        user_agent="value-agent test@example.com",
        opener=lambda *_args, **_kwargs: FakeResponse(b"retained binary original"),
    )
    source = adapter.capture(
        "damodaran-reference",
        "https://pages.stern.nyu.edu/~adamodar/pc/archives/betas24.xls",
    )
    assert source.available_at == source.captured_at
    assert source.publication_at is None
