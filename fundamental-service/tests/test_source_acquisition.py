import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fundamental_service.arelle_parser import ArelleValidationProfileV1
from fundamental_service.contracts import (
    IdentityV1,
    SecFilingSelectorV1,
    SecIngestionRequestV1,
    SecMappingReferenceV1,
)
from fundamental_service.operations import ServiceError
from fundamental_service.serialization import sha256_digest
from fundamental_service.source_acquisition import (
    SecAcquisitionUseCase,
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
    }
    return SimpleNamespace(filings=SimpleNamespace(recent=SimpleNamespace(**recent)))


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
