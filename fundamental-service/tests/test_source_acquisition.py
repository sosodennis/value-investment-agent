import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fundamental_service.contracts import (
    IdentityV1,
    SecFilingSelectorV1,
    SecIngestionRequestV1,
    SecMappingReferenceV1,
)
from fundamental_service.operations import ServiceError
from fundamental_service.serialization import sha256_digest
from fundamental_service.source_acquisition import SecAcquisitionUseCase


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
    use_case.settings = SimpleNamespace(
        taxonomy_manifest_id="sec-us-gaap-2023-2024-public-bundle",
        taxonomy_version="us-gaap-2023-2024",
    )

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
