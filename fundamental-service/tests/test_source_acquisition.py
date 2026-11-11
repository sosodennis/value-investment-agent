import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from fundamental_service.arelle_parser import ArelleValidationProfileV1
from fundamental_service.contracts import (
    IdentityV1,
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
