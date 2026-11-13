import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from fundamental_service.arelle_parser import ArelleValidationProfileV1
from fundamental_service.contracts import (
    IdentityV1,
    QualityStatus,
    SecFilingSelectorV1,
    SecIngestionRequestV1,
    SecMappingReferenceV1,
)
from fundamental_service.operations import ServiceError
from fundamental_service.historical_dqc import (
    HISTORICAL_PROFILE_ID,
    OFFICIAL_SOURCE_SHA256,
)
from fundamental_service.serialization import sha256_digest
from fundamental_service.snapshots import FilesystemContentStore
from fundamental_service.source_acquisition import (
    SecAcquisitionUseCase,
    parse_supported_filing_forms,
    parse_supported_filing_years,
)


def test_sec_filing_index_selects_only_primary_schema_and_linkbases():
    payload = json.dumps(
        {
            "directory": {
                "item": [
                    {
                        "name": "aapl-20240928.htm",
                        "type": "text.gif",
                        "size": "1503780",
                    },
                    {
                        "name": "0000320193-24-000123-xbrl.zip",
                        "type": "compressed.gif",
                        "size": "458550",
                    },
                    {"name": "aapl-20240928.xsd", "type": "text.gif", "size": "58200"},
                    {
                        "name": "aapl-20240928_cal.xml",
                        "type": "text.gif",
                        "size": "150261",
                    },
                    {
                        "name": "aapl-20240928_def.xml",
                        "type": "text.gif",
                        "size": "232678",
                    },
                    {
                        "name": "aapl-20240928_lab.xml",
                        "type": "text.gif",
                        "size": "779708",
                    },
                    {
                        "name": "aapl-20240928_pre.xml",
                        "type": "text.gif",
                        "size": "509625",
                    },
                    {
                        "name": "a10-kexhibit10199282024.htm",
                        "type": "text.gif",
                        "size": "56948",
                    },
                    {"name": "other-issuer.xsd", "type": "EX-101.SCH", "size": "1000"},
                ]
            }
        }
    ).encode()
    use_case = object.__new__(SecAcquisitionUseCase)

    assert use_case._select_dts_filenames(payload, "aapl-20240928.htm") == (
        "aapl-20240928.xsd",
        "aapl-20240928_cal.xml",
        "aapl-20240928_def.xml",
        "aapl-20240928_lab.xml",
        "aapl-20240928_pre.xml",
    )
    assert (
        use_case._select_filing_archive_filename(payload, "0000320193-24-000123")
        == "0000320193-24-000123-xbrl.zip"
    )


def test_award_proxy_selection_is_point_in_time_and_retains_following_materials():
    valuation_at = datetime(2026, 11, 13, tzinfo=UTC)
    submissions = _submissions_with_filings(
        {
            "accession": "0000320193-26-000455",
            "filing_date": "2026-06-22",
            "accepted_at": "2026-06-22T14:22:00Z",
            "form": "DEF 14A",
            "primary_document": "proxy.htm",
        },
        {
            "accession": "0000320193-26-000499",
            "filing_date": "2026-07-01",
            "accepted_at": "2026-07-01T14:22:00Z",
            "form": "DEFA14A",
            "primary_document": "additional.htm",
        },
        {
            "accession": "0000320193-26-000510",
            "filing_date": "2026-07-03",
            "accepted_at": "2026-07-03T14:22:00Z",
            "form": "DEF 14A/A",
            "primary_document": "amended.htm",
        },
        {
            "accession": "0000320193-26-000600",
            "filing_date": "2026-11-14",
            "accepted_at": "2026-11-14T14:22:00Z",
            "form": "DEF 14A",
            "primary_document": "future.htm",
        },
        {
            "accession": "0000320193-25-000010",
            "filing_date": "2025-03-01",
            "accepted_at": "2025-03-01T14:22:00Z",
            "form": "DEF 14A",
            "primary_document": "stale.htm",
        },
    )

    selected, issues = SecAcquisitionUseCase._select_award_proxy_filings(
        submissions, valuation_at
    )

    assert issues == ()
    assert tuple(item.accession_number for item in selected) == (
        "0000320193-26-000455",
        "0000320193-26-000499",
        "0000320193-26-000510",
    )
    assert tuple(item.form for item in selected) == (
        "DEF 14A",
        "DEFA14A",
        "DEF 14A/A",
    )


def test_award_proxy_selection_retains_missing_original_diagnostic():
    submissions = _submissions_with_filings(
        {
            "accession": "0000320193-26-000001",
            "filing_date": "2026-05-01",
            "accepted_at": "2026-05-01T14:22:00Z",
            "form": "10-K",
            "primary_document": "annual.htm",
        }
    )

    selected, issues = SecAcquisitionUseCase._select_award_proxy_filings(
        submissions, datetime(2026, 11, 13, tzinfo=UTC)
    )

    assert selected == ()
    assert tuple(issue.code for issue in issues) == ("EQUITY_AWARD_PROXY_UNAVAILABLE",)


def _submissions_with_filings(*filings: dict[str, object]):
    recent = {
        "accessionNumber": [item["accession"] for item in filings],
        "filingDate": [item["filing_date"] for item in filings],
        "acceptanceDateTime": [item["accepted_at"] for item in filings],
        "form": [item["form"] for item in filings],
        "primaryDocument": [item["primary_document"] for item in filings],
        "isXBRL": [1 for _ in filings],
        "isInlineXBRL": None,
    }
    return SimpleNamespace(filings=SimpleNamespace(recent=SimpleNamespace(**recent)))


def _entrypoint_index(*names: str) -> bytes:
    return json.dumps(
        {"directory": {"item": [{"name": name, "size": 100} for name in names]}}
    ).encode()


@pytest.mark.parametrize(
    ("primary", "inline", "expected"),
    (
        ("acug_10k.htm", False, "acug-20150930.xml"),
        ("acug-20150930.xml", False, "acug-20150930.xml"),
        ("acug-20150930.htm", True, "acug-20150930.htm"),
        ("acug-20150930.htm", None, "acug-20150930.htm"),
    ),
)
def test_entrypoint_selection_distinguishes_original_xml_from_inline_html(
    primary, inline, expected
):
    use_case = object.__new__(SecAcquisitionUseCase)
    payload = _entrypoint_index(
        primary,
        *(() if primary.endswith(".xml") else ("acug-20150930.xml",)),
        "acug-20150930.xsd",
        "acug-20150930_cal.xml",
        "acug-20150930_lab.xml",
        "FilingSummary.xml",
    )
    selected = use_case._select_xbrl_entrypoint(payload, primary, is_inline_xbrl=inline)
    assert selected == expected
    assert use_case._select_dts_filenames(payload, selected) == (
        "acug-20150930.xsd",
        "acug-20150930_cal.xml",
        "acug-20150930_lab.xml",
    )


@pytest.mark.parametrize(
    ("names", "inline"),
    (
        (("acug_10k.htm",), False),
        (("acug_10k.htm", "acug.xml"), False),
        (("acug.xml", "acug.xsd", "other.xml", "other.xsd"), False),
        (("acug.xml", "acug.xml", "acug.xsd"), False),
        (("acug.xml", "acug.xsd", "acug.xsd"), False),
        (("../acug.xml", "acug.xsd"), False),
        (("acug.xml", "acug.xsd"), True),
        (("acug.xml", "acug.xsd"), None),
        (("acug_10k.htm", "acug_10k.htm", "acug.xsd"), True),
        (("../acug_10k.htm", "acug.xsd"), True),
    ),
)
def test_entrypoint_selection_retains_missing_ambiguous_and_unsafe_failures(
    names, inline
):
    use_case = object.__new__(SecAcquisitionUseCase)
    with pytest.raises(ServiceError) as error:
        use_case._select_xbrl_entrypoint(
            _entrypoint_index(*names), "acug_10k.htm", is_inline_xbrl=inline
        )
    assert error.value.code == "XBRL_ENTRYPOINT_UNRESOLVED"


def _inline_original(schema: str) -> bytes:
    return (
        '<html xmlns:link="http://www.xbrl.org/2003/linkbase" '
        'xmlns:xlink="http://www.w3.org/1999/xlink"><head>'
        f'<link:schemaRef xlink:type="simple" xlink:href="{schema}"/>'
        "</head><body>Retained original</body></html>"
    ).encode()


def test_inline_schema_selection_uses_original_reference_and_exact_index_name():
    use_case = object.__new__(SecAcquisitionUseCase)
    primary = "ef20039035_10k.htm"
    schema = "tlfa-20241231.xsd"
    payload = _entrypoint_index(
        primary, schema, "tlfa-20241231_cal.xml", "unrelated.xsd"
    )
    assert (
        use_case._select_xbrl_entrypoint(payload, primary, is_inline_xbrl=True)
        == primary
    )
    selected = use_case._inline_schema_filename(_inline_original(schema))
    assert selected == schema
    assert use_case._select_dts_filenames(
        payload, primary, schema_filename=selected
    ) == (schema, "tlfa-20241231_cal.xml")


@pytest.mark.parametrize(
    "schema",
    (
        "../tlfa.xsd",
        "./tlfa.xsd",
        "/tlfa.xsd",
        "sub/tlfa.xsd",
        "https://example.com/tlfa.xsd",
        "//example.com/tlfa.xsd",
        "tlfa.xsd?query",
        "tlfa.xsd#fragment",
        "tlfa%2exsd",
        "tlfa\\x.xsd",
        "tlfa.xml",
        "",
        " tlfa.xsd",
        "tlfa.xsd ",
    ),
)
def test_inline_schema_selection_refuses_nonlocal_or_unsafe_references(schema):
    with pytest.raises(ServiceError) as error:
        SecAcquisitionUseCase._inline_schema_filename(_inline_original(schema))
    assert error.value.code == "XBRL_SCHEMA_UNRESOLVED"


@pytest.mark.parametrize(
    "content",
    (
        b"",
        b"<html><body>No schema reference</body></html>",
        _inline_original("tlfa.xsd").replace(b"/2003/linkbase", b"/other"),
        _inline_original("tlfa.xsd").replace(b"/1999/xlink", b"/other"),
        _inline_original("tlfa.xsd").replace(b"xlink:href", b"href"),
        _inline_original("tlfa.xsd").replace(
            b"<link:schemaRef", b'<link:schemaRef xmlns:link="spoof"'
        ),
        _inline_original("tlfa.xsd").replace(
            b"<html ", b'<html xml:base="https://example.com/" '
        ),
        _inline_original("tlfa.xsd").replace(
            b"<link:schemaRef", b'<link:schemaRef xml:base="other/"'
        ),
        _inline_original("tlfa.xsd").replace(
            b"</head>", b'<link:schemaRef xlink:href="other.xsd"/></head>'
        ),
        _inline_original("tlfa.xsd").replace(
            b"</head>", b'<link:schemaRef xlink:href="tlfa.xsd"/></head>'
        ),
    ),
)
def test_inline_schema_selection_retains_missing_ambiguous_and_misbound_failures(
    content,
):
    with pytest.raises(ServiceError) as error:
        SecAcquisitionUseCase._inline_schema_filename(content)
    assert error.value.code == "XBRL_SCHEMA_UNRESOLVED"


@pytest.mark.parametrize(
    "names",
    (
        ("different_10k.htm",),
        ("different_10k.htm", "tlfa.xsd", "tlfa.xsd"),
        ("different_10k.htm", "TLFA.xsd"),
    ),
)
def test_inline_schema_must_occur_once_with_exact_case_in_accession_index(names):
    use_case = object.__new__(SecAcquisitionUseCase)
    with pytest.raises(ServiceError) as error:
        use_case._select_dts_filenames(
            _entrypoint_index(*names), "different_10k.htm", schema_filename="tlfa.xsd"
        )
    assert error.value.code == "SOURCE_PAYLOAD_INVALID"


def test_inline_schema_selection_accepts_bound_namespace_aliases():
    content = (
        b'<html xmlns:l="http://www.xbrl.org/2003/linkbase" '
        b'xmlns:x="http://www.w3.org/1999/xlink"><head>'
        b'<l:schemaRef x:href="tlfa.xsd"/></head><body/></html>'
    )
    assert SecAcquisitionUseCase._inline_schema_filename(content) == "tlfa.xsd"


@pytest.mark.parametrize(
    ("flag", "expected"), (("0", False), (1, True), ("true", True))
)
def test_filing_selection_retains_sec_inline_indicator(flag, expected):
    submissions = _submissions_with_filings(
        {
            "accession": "0001477932-16-007985",
            "filing_date": "2016-01-12",
            "accepted_at": "2016-01-12T12:00:00Z",
            "form": "10-K",
            "primary_document": "acug_10k.htm",
        }
    )
    submissions.filings.recent.isInlineXBRL = [flag]
    selected = SecAcquisitionUseCase._select_filing(
        submissions,
        SecFilingSelectorV1(),
        datetime(2016, 2, 1, tzinfo=UTC),
        supported_filing_years=(2016,),
        supported_filing_forms=("10-K",),
    )
    assert selected.is_inline_xbrl is expected


def test_submissions_reject_incomplete_inline_column():
    request = _sec_request()
    payload = json.dumps(
        {
            "cik": request.cik,
            "tickers": [request.ticker],
            "filings": {
                "recent": {
                    "accessionNumber": ["0001477932-16-007985"],
                    "filingDate": ["2016-01-12"],
                    "acceptanceDateTime": ["2016-01-12T12:00:00Z"],
                    "form": ["10-K"],
                    "primaryDocument": ["acug_10k.htm"],
                    "isXBRL": [1],
                    "isInlineXBRL": [],
                }
            },
        }
    ).encode()
    with pytest.raises(ServiceError) as error:
        SecAcquisitionUseCase._decode_submissions(payload, request)
    assert error.value.code == "SOURCE_PAYLOAD_INVALID"


def test_historical_header_uses_pinned_cik_without_current_ticker_survival_check():
    request = _sec_request()
    payload = {
        "cik": request.cik,
        "tickers": [],
        "filings": {
            "recent": {
                key: []
                for key in (
                    "accessionNumber",
                    "filingDate",
                    "acceptanceDateTime",
                    "form",
                    "primaryDocument",
                    "isXBRL",
                )
            }
        },
    }
    with pytest.raises(ServiceError) as current:
        SecAcquisitionUseCase._decode_submissions(json.dumps(payload).encode(), request)
    assert current.value.code == "IDENTITY_AMBIGUOUS"
    historical = SecIngestionRequestV1.model_validate(
        {
            **request.model_dump(),
            "identity_basis": "original-filing-dei-v1",
            "filing": {
                "accession_number": request.filing.accession_number,
                "forms": ("10-K",),
            },
        }
    )
    SecAcquisitionUseCase._decode_submissions(json.dumps(payload).encode(), historical)
    assert SecAcquisitionUseCase._canonical_key_payload(historical) != (
        SecAcquisitionUseCase._canonical_key_payload(request)
    )
    payload["cik"] = "0000000001"
    with pytest.raises(ServiceError) as mismatch:
        SecAcquisitionUseCase._decode_submissions(
            json.dumps(payload).encode(), historical
        )
    assert mismatch.value.code == "IDENTITY_AMBIGUOUS"


@pytest.mark.parametrize(
    "filing", [{}, {"forms": ("10-K/A",)}, {"forms": ("10-K", "10-Q")}]
)
def test_historical_identity_contract_rejects_unpinned_or_nonoriginal_selection(filing):
    request = _sec_request().model_dump()
    request.update(identity_basis="original-filing-dei-v1", filing=filing)
    with pytest.raises(ValidationError, match="pinned original 10-K"):
        SecIngestionRequestV1.model_validate(request)


def test_declared_inline_filing_cannot_select_standalone_xml():
    use_case = object.__new__(SecAcquisitionUseCase)
    with pytest.raises(ServiceError) as error:
        use_case._select_xbrl_entrypoint(
            _entrypoint_index("acug.xml", "acug.xsd"),
            "acug.xml",
            is_inline_xbrl=True,
        )
    assert error.value.code == "XBRL_ENTRYPOINT_UNRESOLVED"


def test_default_filing_selection_skips_years_outside_installed_runtime():
    submissions = _submissions_with_filings(
        {
            "accession": "0000789019-26-000001",
            "filing_date": "2026-11-03",
            "accepted_at": "2026-11-03T12:00:00Z",
            "form": "10-K",
            "primary_document": "msft-20260930.htm",
        },
        {
            "accession": "0000789019-24-000001",
            "filing_date": "2024-07-30",
            "accepted_at": "2024-07-30T12:00:00Z",
            "form": "10-K",
            "primary_document": "msft-20240630.htm",
        },
    )

    selected = SecAcquisitionUseCase._select_filing(
        submissions,
        SecFilingSelectorV1(),
        datetime(2026, 11, 7, tzinfo=UTC),
        supported_filing_years=(2024,),
        supported_filing_forms=("10-K",),
    )

    assert selected.accession_number == "0000789019-24-000001"


def test_explicit_filing_outside_installed_runtime_fails_closed():
    submissions = _submissions_with_filings(
        {
            "accession": "0000789019-26-000001",
            "filing_date": "2026-11-03",
            "accepted_at": "2026-11-03T12:00:00Z",
            "form": "10-K",
            "primary_document": "msft-20260930.htm",
        }
    )

    with pytest.raises(ServiceError) as error:
        SecAcquisitionUseCase._select_filing(
            submissions,
            SecFilingSelectorV1(accession_number="0000789019-26-000001"),
            datetime(2026, 11, 7, tzinfo=UTC),
            supported_filing_years=(2024,),
            supported_filing_forms=("10-K",),
        )

    assert error.value.code == "FILING_RUNTIME_INCOMPATIBLE"
    assert error.value.retryable is False


def _sec_request() -> SecIngestionRequestV1:
    return SecIngestionRequestV1(
        contract_version="fundamental.v1",
        identity=IdentityV1(
            issuer_id="0000789019",
            issuer_name="Microsoft Corporation",
            domicile="US",
            reporting_basis="us-gaap",
            security_id="MSFT",
            share_class="common",
            currency="USD",
        ),
        cik="0000789019",
        ticker="MSFT",
        valuation_timestamp=datetime(2025, 6, 30, tzinfo=UTC),
        required_fields=("revenue",),
        mappings=(
            SecMappingReferenceV1(
                decision_id="sec-revenue-v1",
                mapping_version="sec-us-gaap-v1",
                normalized_field="revenue",
            ),
        ),
        source_selection_policy="sec-pit-v1",
        coverage_profile="us-gaap-public-v1",
        legal_use_profile="sec-public-us-v1",
        filing=SecFilingSelectorV1(accession_number="0000950170-24-087843"),
        parser_version="2.47.4",
        validation_profile_id="sec-efm-us-dqc-v31.0.3",
        taxonomy_manifest_id="sec-us-gaap-2023-2024-public-bundle",
        taxonomy_version="us-gaap-2023-2024",
        policy_version="sec-public-pit-v1",
    )


def _runtime_settings() -> SimpleNamespace:
    return SimpleNamespace(
        taxonomy_manifest_id="sec-us-gaap-2023-2024-public-bundle",
        taxonomy_version="us-gaap-2023-2024",
        taxonomy_cache_sha256="c" * 64,
        supported_filing_years=(2024,),
        edgar_plugin_dir=Path("/runtime/arelle/EDGAR"),
        xule_plugin_dir=Path("/runtime/arelle/Xule"),
        dqc_ruleset_path=Path("/runtime/arelle/dqc-ruleset.xml"),
        edgar_plugin_sha256="a" * 64,
        xule_plugin_sha256="b" * 64,
        dqc_ruleset_sha256="d" * 64,
        supported_filing_forms=("10-K",),
        historical_dqc_dir=None,
        historical_dqc_sha256=None,
    )


def _validation_profile(dqc_ruleset_sha256: str = "d" * 64):
    return ArelleValidationProfileV1(
        profile_id="sec-efm-us-dqc-v31.0.3",
        validation_mode="sec-efm-dqc",
        edgar_plugin_dir=Path("/runtime/arelle/EDGAR"),
        xule_plugin_dir=Path("/runtime/arelle/Xule"),
        dqc_ruleset_path=Path("/runtime/arelle/dqc-ruleset.xml"),
        edgar_plugin_sha256="a" * 64,
        xule_plugin_sha256="b" * 64,
        dqc_ruleset_sha256=dqc_ruleset_sha256,
    )


def _partial_acquisition_fixture(tmp_path, *, empty=False, schema="msft-20240630.xsd"):
    from fundamental_service.facts import CanonicalMappingV1
    from fundamental_service.sec_source import (
        SecEdgarSourceAdapter,
        SecRequestPolicy,
        _SecResponse,
    )
    from test_postgres_metadata import _fact_for_snapshot, _snapshot

    fields = ("revenue", "preferred_claims", "contract_assets")
    mappings = tuple(
        CanonicalMappingV1(
            contract_version="fundamental.v1",
            decision_id=f"partial-{field}",
            source_concept=f"us-gaap:{field}",
            normalized_field=field,
            mapping_version="partial-v1",
            status="provisional",
            confidence="unresolved",
        )
        for field in fields
    )
    request = _sec_request().model_copy(
        update={
            "valuation_timestamp": datetime(2026, 2, 1, tzinfo=UTC),
            "required_fields": fields,
            "mappings": tuple(
                SecMappingReferenceV1(
                    decision_id=mapping.decision_id,
                    mapping_version=mapping.mapping_version,
                    normalized_field=mapping.normalized_field,
                )
                for mapping in mappings
            ),
        }
    )
    content = FilesystemContentStore(tmp_path / "content")
    raw = b"synthetic validated original; incomplete accounting roles"
    source_hash = content.put(raw, media_type="application/json")
    original = _snapshot(
        source_hash,
        identity=request.identity,
        valuation_timestamp=request.valuation_timestamp,
    )
    payload = original.model_dump(exclude={"manifest_digest"})
    payload["source_records"] = (
        original.source_records[0].model_copy(update={"content_hash": source_hash}),
    )
    payload["manifest_digest"] = sha256_digest(
        {key: value for key, value in payload.items() if key != "snapshot_id"}
    )
    snapshot = type(original)(**payload)
    facts = () if empty else (_fact_for_snapshot(snapshot, f"partial-{source_hash}"),)
    settings = _runtime_settings()
    settings.taxonomy_cache_dir = tmp_path / "taxonomy"
    profile = _validation_profile()
    prepared = SimpleNamespace(
        snapshot=snapshot,
        facts=facts,
        issues=(),
        identity_evidence_ref=None,
        mapping_evidence_ref=None,
        parser_report=SimpleNamespace(
            taxonomy_cache_hash=settings.taxonomy_cache_sha256,
            finding_codes=(),
            validation_profile=profile,
            validation_profile_digest=profile.digest(),
        ),
    )
    state = SimpleNamespace(provider_calls=0, parser_calls=0, parser_kwargs=None)
    primary = "msft-20240630.htm"
    accession = request.filing.accession_number
    submissions = {
        "cik": int(request.cik),
        "tickers": [request.ticker],
        "filings": {
            "recent": {
                "accessionNumber": [accession],
                "filingDate": ["2024-07-30"],
                "acceptanceDateTime": ["2024-07-30T20:06:22Z"],
                "form": ["10-K"],
                "primaryDocument": [primary],
                "isXBRL": [1],
                "isInlineXBRL": [1],
            }
        },
    }

    class Provider(SecEdgarSourceAdapter):
        def _request(self, uri, *, deadline_at=None):
            state.provider_calls += 1
            raw = (
                json.dumps(submissions).encode()
                if "/submissions/" in uri
                else _inline_original(schema)
                if uri.endswith("/" + primary)
                else _entrypoint_index(primary, schema, f"{accession}-xbrl.zip")
            )
            return _SecResponse(
                raw, 200, "application/json", snapshot.captured_at, (), len(raw)
            )

    def prepare_filing(**kwargs):
        state.parser_calls += 1
        state.parser_kwargs = kwargs
        return prepared

    provider = Provider(SecRequestPolicy(user_agent="test test@example.com"))
    return SimpleNamespace(
        request=request,
        snapshot=snapshot,
        facts=facts,
        mappings=mappings,
        state=state,
        content=content,
        settings=settings,
        provider=provider,
        ingestion=SimpleNamespace(prepare_filing=prepare_filing),
        prepared=prepared,
    )


@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("schema", ["msft-20240630.xsd", "different-schema-2024.xsd"])
def test_incomplete_parsed_acquisition_retains_partial_evidence(
    tmp_path, empty, schema
):
    fixture = _partial_acquisition_fixture(tmp_path, empty=empty, schema=schema)
    published = []

    def publish(**kwargs):
        published.append(kwargs)
        return kwargs["result"]

    metadata = SimpleNamespace(
        get_mapping={m.decision_id: m for m in fixture.mappings}.__getitem__,
        publish_sec_ingestion=publish,
        publish_source_audit=lambda **kwargs: None,
    )
    use_case = SecAcquisitionUseCase(
        adapter=fixture.provider,
        ingestion=fixture.ingestion,
        metadata=metadata,
        content_store=fixture.content,
        settings=fixture.settings,
        authorized_organizations=frozenset({"org"}),
    )
    result = use_case._acquire_and_publish(
        fixture.request,
        acquisition_key="a" * 64,
        key_payload={},
        caller_principal="caller",
        organization_id="org",
        correlation_id="first",
        deadline_at=datetime.now(UTC) + timedelta(minutes=1),
        validation_profile=_validation_profile(),
    )
    assert result.status == "abstain"
    assert result.quality_status is QualityStatus.ABSTAIN
    assert result.issue_codes == ("REQUIRED_FACTS_UNAVAILABLE",)
    assert result.missing_evidence == tuple(
        sorted(
            fixture.request.required_fields
            if empty
            else ("preferred_claims", "contract_assets")
        )
    )
    assert result.snapshot_id == fixture.snapshot.snapshot_id
    assert result.manifest_digest == fixture.snapshot.manifest_digest
    assert result.canonical_fact_ids == tuple(f.fact_id for f in fixture.facts)
    assert published[0]["snapshot"] == fixture.snapshot
    assert published[0]["facts"] == fixture.facts
    assert fixture.state.parser_calls == 1
    assert fixture.state.parser_kwargs["dts_filenames"] == (schema,)
    assert fixture.state.parser_kwargs["primary_document"] == "msft-20240630.htm"


def test_canonical_acquisition_key_distinguishes_identity_cutoff_and_coverage():
    request = _sec_request()
    use_case = object.__new__(SecAcquisitionUseCase)
    key = sha256_digest(use_case._canonical_key_payload(request))
    variants = (
        request.model_copy(
            update={
                "identity": request.identity.model_copy(
                    update={"share_class": "preferred"}
                )
            }
        ),
        request.model_copy(
            update={"identity": request.identity.model_copy(update={"currency": "EUR"})}
        ),
        request.model_copy(
            update={"valuation_timestamp": datetime(2025, 7, 1, tzinfo=UTC)}
        ),
        request.model_copy(update={"coverage_profile": "us-gaap-full-history-v2"}),
        request.model_copy(update={"taxonomy_version": "us-gaap-2023"}),
        request.model_copy(update={"policy_version": "sec-public-pit-v2"}),
    )

    assert all(
        sha256_digest(use_case._canonical_key_payload(variant)) != key
        for variant in variants
    )


def test_verified_supporting_facts_do_not_degrade_complete_required_coverage(tmp_path):
    fixture = _partial_acquisition_fixture(tmp_path)
    request = fixture.request.model_copy(
        update={
            "required_fields": ("revenue",),
            "mappings": (fixture.request.mappings[0],),
        }
    )
    required = fixture.facts[0].model_copy(update={"quality": QualityStatus.VERIFIED})
    assert fixture.snapshot.coverage_status is QualityStatus.VERIFIED
    fixture.prepared.facts = (
        required,
        required.model_copy(
            update={"fact_id": "supporting-fact", "normalized_field": "cash"}
        ),
    )
    metadata = SimpleNamespace(
        get_mapping={m.decision_id: m for m in fixture.mappings}.__getitem__,
        publish_sec_ingestion=lambda **kwargs: kwargs["result"],
        publish_source_audit=lambda **kwargs: None,
    )
    use_case = SecAcquisitionUseCase(
        adapter=fixture.provider,
        ingestion=fixture.ingestion,
        metadata=metadata,
        content_store=fixture.content,
        settings=fixture.settings,
        authorized_organizations=frozenset({"org"}),
    )
    result = use_case._acquire_and_publish(
        request,
        acquisition_key="a" * 64,
        key_payload={},
        caller_principal="caller",
        organization_id="org",
        correlation_id="supporting-facts",
        deadline_at=datetime.now(UTC) + timedelta(minutes=1),
        validation_profile=_validation_profile(),
    )
    assert result.status == "created"
    assert result.quality_status is QualityStatus.VERIFIED
    assert not result.missing_evidence and not result.issue_codes
    assert set(result.canonical_fact_ids) == {required.fact_id, "supporting-fact"}


def test_runtime_acquisition_key_binds_validation_and_taxonomy_digests():
    request = _sec_request()
    use_case = object.__new__(SecAcquisitionUseCase)
    use_case.settings = _runtime_settings()

    baseline = use_case._runtime_key_payload(request, _validation_profile())
    changed_profile = use_case._runtime_key_payload(
        request, _validation_profile(dqc_ruleset_sha256="e" * 64)
    )
    use_case.settings = SimpleNamespace(
        **{**vars(_runtime_settings()), "taxonomy_cache_sha256": "f" * 64}
    )
    changed_taxonomy = use_case._runtime_key_payload(request, _validation_profile())
    use_case.settings = SimpleNamespace(
        **{**vars(_runtime_settings()), "supported_filing_years": (2023, 2024)}
    )
    changed_compatible_years = use_case._runtime_key_payload(
        request, _validation_profile()
    )

    assert baseline["runtime_releases"] == {
        "taxonomy_cache_sha256": "c" * 64,
        "validation_profile_digest": _validation_profile().digest(),
        "supported_filing_years": (2024,),
        "supported_filing_forms": ("10-K",),
    }
    assert sha256_digest(baseline) != sha256_digest(changed_profile)
    assert sha256_digest(baseline) != sha256_digest(changed_taxonomy)
    assert sha256_digest(baseline) != sha256_digest(changed_compatible_years)


@pytest.mark.parametrize(
    ("value", "expected"),
    (("2024", (2024,)), ("2024,2023,2024", (2023, 2024)), (None, None)),
)
def test_supported_filing_years_parse_deterministically(value, expected):
    assert parse_supported_filing_years(value) == expected


def test_supported_filing_years_reject_invalid_configuration():
    with pytest.raises(ValueError, match="comma-separated years"):
        parse_supported_filing_years("2024,current")
    with pytest.raises(ValueError, match="invalid year"):
        parse_supported_filing_years("1800")


@pytest.mark.parametrize(
    ("value", "expected"),
    (("10-K", ("10-K",)), ("10-Q,10-K,10-K", ("10-K", "10-Q")), (None, None)),
)
def test_supported_filing_forms_parse_deterministically(value, expected):
    assert parse_supported_filing_forms(value) == expected


def test_supported_filing_forms_reject_invalid_configuration():
    with pytest.raises(ValueError, match="invalid form"):
        parse_supported_filing_forms("10-K,8-K")


def test_default_filing_selection_skips_unsupported_forms():
    submissions = _submissions_with_filings(
        {
            "accession": "0000789019-24-000002",
            "filing_date": "2024-10-30",
            "accepted_at": "2024-10-30T12:00:00Z",
            "form": "10-Q",
            "primary_document": "msft-20240930.htm",
        },
        {
            "accession": "0000789019-24-000001",
            "filing_date": "2024-07-30",
            "accepted_at": "2024-07-30T12:00:00Z",
            "form": "10-K",
            "primary_document": "msft-20240630.htm",
        },
    )

    selected = SecAcquisitionUseCase._select_filing(
        submissions,
        SecFilingSelectorV1(),
        datetime(2026, 11, 7, tzinfo=UTC),
        supported_filing_years=(2024,),
        supported_filing_forms=("10-K",),
    )

    assert selected.accession_number == "0000789019-24-000001"


class _AuditMetadata:
    def __init__(self, lease=None):
        self.lease = lease
        self.audits = []

    def publish_source_audit(self, **audit):
        self.audits.append(audit)

    def try_acquire_ingestion_lock(self, _acquisition_key):
        return self.lease

    def get_sec_ingestion(self, _acquisition_key, *, expected_acquisition_payload):
        return None


class _RetainedAcquisitionMetadata(_AuditMetadata):
    def __init__(self, result, *, published_during_lock=False):
        super().__init__(lease=object() if published_during_lock else None)
        self.result = result
        self.published_during_lock = published_during_lock
        self.reads = []
        self.lock_attempts = 0
        self.released = []

    def get_sec_ingestion(self, acquisition_key, *, expected_acquisition_payload):
        self.reads.append((acquisition_key, expected_acquisition_payload))
        if self.published_during_lock and self.lock_attempts == 0:
            return None
        return self.result

    def try_acquire_ingestion_lock(self, acquisition_key):
        self.lock_attempts += 1
        return super().try_acquire_ingestion_lock(acquisition_key)

    def release_ingestion_lock(self, lease):
        self.released.append(lease)


def _retained_acquisition_use_case(tmp_path, *, published_during_lock=False):
    from test_postgres_metadata import _sec_ingestion_result

    fixture = _partial_acquisition_fixture(tmp_path)
    result = _sec_ingestion_result(fixture.snapshot, correlation_id="original")
    metadata = _RetainedAcquisitionMetadata(
        result, published_during_lock=published_during_lock
    )
    use_case = SecAcquisitionUseCase(
        adapter=fixture.provider,
        ingestion=fixture.ingestion,
        metadata=metadata,
        content_store=fixture.content,
        settings=fixture.settings,
        authorized_organizations=frozenset({"org"}),
    )
    return use_case, metadata, fixture


@pytest.mark.parametrize("audit_reuse", [False, True])
def test_completed_acquisition_reuses_without_writer_lease(tmp_path, audit_reuse):
    use_case, metadata, fixture = _retained_acquisition_use_case(tmp_path)
    result = use_case.execute(
        fixture.request,
        caller_principal="caller",
        organization_id="org",
        correlation_id="new-caller",
        deadline_at=datetime(2025, 1, 1, tzinfo=UTC),
        audit_reuse=audit_reuse,
    )

    assert result == metadata.result.model_copy(
        update={"status": "reused", "reused": True, "correlation_id": "new-caller"}
    )
    assert metadata.lock_attempts == 0 and not metadata.released
    key, payload = metadata.reads[0]
    assert key == sha256_digest(payload)
    assert payload == use_case._runtime_key_payload(
        fixture.request, use_case._validation_profile(fixture.request)
    )
    assert fixture.state.provider_calls == fixture.state.parser_calls == 0
    assert len(metadata.audits) == int(audit_reuse)
    if audit_reuse:
        assert metadata.audits[0] == {
            "acquisition_key": key,
            "caller_principal": "caller",
            "organization_id": "org",
            "correlation_id": "new-caller",
            "source_hashes": (),
            "outcome": "reused",
        }


def test_concurrent_completed_acquisitions_are_read_only(tmp_path):
    use_case, metadata, fixture = _retained_acquisition_use_case(tmp_path)

    def execute(_):
        return use_case.execute(
            fixture.request,
            caller_principal="caller",
            organization_id="org",
            correlation_id="unchanged",
            deadline_at=datetime(2025, 1, 1, tzinfo=UTC),
            audit_reuse=False,
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = tuple(pool.map(execute, range(3)))
    assert results[0] == results[1] == results[2]
    assert all(result.reused for result in results)
    assert metadata.lock_attempts == 0 and not metadata.audits
    assert len(metadata.reads) == 3
    assert fixture.state.provider_calls == fixture.state.parser_calls == 0


def test_acquisition_published_during_writer_lock_is_rechecked(tmp_path):
    use_case, metadata, fixture = _retained_acquisition_use_case(
        tmp_path, published_during_lock=True
    )
    result = use_case.execute(
        fixture.request,
        caller_principal="caller",
        organization_id="org",
        correlation_id="raced-publication",
        deadline_at=datetime(2025, 1, 1, tzinfo=UTC),
        audit_reuse=False,
    )
    assert result.reused and result.snapshot_id == metadata.result.snapshot_id
    assert len(metadata.reads) == 2
    assert metadata.lock_attempts == 1 and metadata.released == [metadata.lease]
    assert not metadata.audits
    assert fixture.state.provider_calls == fixture.state.parser_calls == 0


@pytest.mark.parametrize(
    ("organization_id", "taxonomy_manifest_id", "code"),
    [
        ("unauthorized", None, "INGESTION_NOT_AUTHORIZED"),
        ("org", "uninstalled-taxonomy", "TAXONOMY_PACKAGE_INVALID"),
    ],
)
def test_completed_acquisition_cannot_bypass_authorization_or_taxonomy(
    tmp_path, organization_id, taxonomy_manifest_id, code
):
    use_case, metadata, fixture = _retained_acquisition_use_case(tmp_path)
    request = fixture.request
    if taxonomy_manifest_id is not None:
        request = request.model_copy(
            update={"taxonomy_manifest_id": taxonomy_manifest_id}
        )
    with pytest.raises(ServiceError) as error:
        use_case.execute(
            request,
            caller_principal="caller",
            organization_id=organization_id,
            correlation_id="rejected",
            deadline_at=datetime(2025, 1, 1, tzinfo=UTC),
            audit_reuse=False,
        )
    assert error.value.code == code
    assert not metadata.reads and metadata.lock_attempts == 0
    assert metadata.audits[0]["outcome"] == code
    assert fixture.state.provider_calls == fixture.state.parser_calls == 0


def test_invalid_retained_acquisition_does_not_fall_back_to_provider(
    tmp_path, monkeypatch
):
    from fundamental_service.snapshots import SnapshotError

    use_case, metadata, fixture = _retained_acquisition_use_case(tmp_path)

    def reject(*args, **kwargs):
        raise SnapshotError("INGESTION_KEY_COLLISION", "another retained request")

    monkeypatch.setattr(metadata, "get_sec_ingestion", reject)
    with pytest.raises(SnapshotError, match="another retained request"):
        use_case.execute(
            fixture.request,
            caller_principal="caller",
            organization_id="org",
            correlation_id="invalid-retained",
            deadline_at=datetime(2025, 1, 1, tzinfo=UTC),
            audit_reuse=False,
        )
    assert metadata.lock_attempts == 0 and not metadata.audits
    assert fixture.state.provider_calls == fixture.state.parser_calls == 0


@pytest.mark.parametrize(
    ("organization_id", "taxonomy_manifest_id", "error_code", "audit_outcome"),
    (
        (
            "org-unapproved",
            "sec-us-gaap-2023-2024-public-bundle",
            "INGESTION_NOT_AUTHORIZED",
            "INGESTION_NOT_AUTHORIZED",
        ),
        (
            "org-approved",
            "uninstalled-taxonomy",
            "TAXONOMY_PACKAGE_INVALID",
            "TAXONOMY_PACKAGE_INVALID",
        ),
        (
            "org-approved",
            "sec-us-gaap-2023-2024-public-bundle",
            "INGESTION_IN_PROGRESS",
            "INGESTION_IN_PROGRESS",
        ),
    ),
)
def test_authenticated_early_rejections_are_audited(
    organization_id: str,
    taxonomy_manifest_id: str,
    error_code: str,
    audit_outcome: str,
):
    request = _sec_request().model_copy(
        update={"taxonomy_manifest_id": taxonomy_manifest_id}
    )
    use_case = object.__new__(SecAcquisitionUseCase)
    metadata = _AuditMetadata()
    use_case.metadata = metadata
    use_case.authorized_organizations = frozenset({"org-approved"})
    use_case.settings = _runtime_settings()

    with pytest.raises(ServiceError) as error:
        use_case.execute(
            request,
            caller_principal="caller-1",
            organization_id=organization_id,
            correlation_id="correlation-1",
            deadline_at=datetime(2025, 6, 30, tzinfo=UTC),
        )

    assert error.value.code == error_code
    assert len(metadata.audits) == 1
    assert metadata.audits[0]["outcome"] == audit_outcome
    assert metadata.audits[0]["caller_principal"] == "caller-1"
    assert metadata.audits[0]["organization_id"] == organization_id
    assert metadata.audits[0]["correlation_id"] == "correlation-1"
    assert metadata.audits[0]["source_hashes"] == ()


def test_historical_acquisition_uses_separate_pinned_profile_and_identity():
    use_case = object.__new__(SecAcquisitionUseCase)
    use_case.settings = _runtime_settings()
    request = _sec_request().model_copy(
        update={"validation_profile_id": HISTORICAL_PROFILE_ID}
    )
    with pytest.raises(ServiceError) as missing:
        use_case._validation_profile(request)
    assert missing.value.code == "VALIDATION_RESOURCES_UNAVAILABLE"
    use_case.settings.historical_dqc_dir = Path("/runtime/official-dqc-v1")
    use_case.settings.historical_dqc_sha256 = OFFICIAL_SOURCE_SHA256
    profile = use_case._validation_profile(request)
    assert profile.dqc_version == "v1.0.0"
    assert profile.historical_dqc_sha256 == OFFICIAL_SOURCE_SHA256
    historical_key = sha256_digest(use_case._runtime_key_payload(request, profile))
    assert historical_key == sha256_digest(
        use_case._runtime_key_payload(request, use_case._validation_profile(request))
    )
    modern_request = _sec_request()
    modern_profile = use_case._validation_profile(modern_request)
    assert modern_profile.historical_dqc_dir is None
    assert historical_key != sha256_digest(
        use_case._runtime_key_payload(modern_request, modern_profile)
    )


def test_v3_acquisition_binds_its_own_official_package_and_runtime_key():
    from fundamental_service.historical_dqc import V3_PROFILE

    use_case = object.__new__(SecAcquisitionUseCase)
    use_case.settings = _runtime_settings()
    use_case.settings.historical_dqc_dir = Path("/runtime/official-dqc-v3.6.2")
    use_case.settings.historical_dqc_sha256 = V3_PROFILE.source_sha256
    request = _sec_request().model_copy(
        update={"validation_profile_id": V3_PROFILE.profile_id}
    )
    profile = use_case._validation_profile(request)
    assert profile.dqc_version == V3_PROFILE.dqc_version
    key = sha256_digest(use_case._runtime_key_payload(request, profile))
    assert key == sha256_digest(
        use_case._runtime_key_payload(request, use_case._validation_profile(request))
    )
    use_case.settings.historical_dqc_sha256 = OFFICIAL_SOURCE_SHA256
    with pytest.raises(ValueError, match="pinned official package"):
        use_case._validation_profile(request)
