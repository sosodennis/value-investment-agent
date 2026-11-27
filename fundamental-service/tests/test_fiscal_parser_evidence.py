from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from fundamental_service.arelle_parser import ArelleParseReportV1
from fundamental_service.contracts import SecIntegrityEvidenceV1
from fundamental_service.data_releases import ArtifactRefV1
from fundamental_service.fiscal_parser_evidence import (
    RetainedFiscalAction,
    RetainedFiscalActions,
    bind_fiscal_retained_inputs,
)
from fundamental_service.fiscal_source_contracts import FiscalFilingV1
from fundamental_service.fiscal_validation_contracts import (
    FiscalArchiveInputV1,
    FiscalCapturedInputV1,
    FiscalNormalizedInputV1,
    FiscalOriginalValidationEvidenceV1,
    FiscalValidationMatchedV1,
    ResolvedFiscalValidationRequestV1,
)
from fundamental_service.parser_action_contracts import (
    ParserActionDeliveryV2,
    ParserActionInputV3,
    ParserActionResultV2,
    ParserBuildIdentityV1,
)
from fundamental_service.sec_capture import SecResponseReceiptV1
from fundamental_service.serialization import sha256_digest
from fundamental_service.snapshots import FilesystemContentStore, SnapshotError

SyntheticRetainedInputs = tuple[
    FiscalOriginalValidationEvidenceV1,
    ArtifactRefV1,
    RetainedFiscalActions,
    FilesystemContentStore,
]


@pytest.fixture
def synthetic_retained_inputs(tmp_path: Path) -> SyntheticRetainedInputs:
    content = FilesystemContentStore(tmp_path / "content")
    primary, manifest, captured = b"synthetic primary", b"{}", b"synthetic capture"
    members = {"extension.xsd": b"synthetic schema", "extension_cal.xml": b"cal"}
    archive_buffer = BytesIO()
    with ZipFile(archive_buffer, "w") as archive:
        for name, raw in members.items():
            archive.writestr(name, raw)
    archive_bytes = archive_buffer.getvalue()
    filing = FiscalFilingV1.model_construct(
        cik="0000320193", accession_number="0000320193-24-000001"
    )
    request = ResolvedFiscalValidationRequestV1.model_construct(
        filing=filing, valuation_timestamp=datetime(2024, 2, 1, tzinfo=UTC)
    )
    folder = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000001"
    receipts = tuple(
        SecResponseReceiptV1(
            scope=request.scope,
            uri=f"{folder}/{name}",
            content_hash=content.put(raw, media_type=media),
            http_status=200,
            media_type=media,
            captured_at=datetime(2024, 1, 1, tzinfo=UTC),
            response_headers=(),
            declared_size=len(raw),
            received_size=len(raw),
        )
        for name, raw, media in (
            ("primary.htm", primary, "text/html"),
            ("source.zip", archive_bytes, "application/zip"),
            ("captured.xml", captured, "application/xml"),
        )
    )
    primary_hash = receipts[0].content_hash
    manifest_hash = content.put(manifest, media_type="application/json")
    files = tuple(
        sorted(
            (
                ("primary.htm", primary_hash),
                ("input.ixds.json", manifest_hash),
                ("captured.xml", receipts[2].content_hash),
                *(
                    (name, hashlib.sha256(raw).hexdigest())
                    for name, raw in members.items()
                ),
            )
        )
    )
    parser_request = ParserActionInputV3(
        representation="normalized",
        entrypoint="input.ixds.json",
        files=files,
        normalization_inputs=tuple(sorted(digest for _, digest in files)),
        resources=(),
        profile_digest="1" * 64,
        taxonomy_version="us-gaap-2024",
        source_content_hash=manifest_hash,
        build=ParserBuildIdentityV1(
            implementation_digest="2" * 64,
            runtime_digest="3" * 64,
            output_schema_digest="4" * 64,
        ),
    )
    result = ParserActionResultV2(request=parser_request, report_content_hash="5" * 64)
    action = RetainedFiscalAction(
        report=ArelleParseReportV1.model_construct(),
        request=parser_request,
        delivery=ParserActionDeliveryV2(
            action_key=parser_request.digest,
            result_artifact_id=result.artifact_id,
            report_content_hash=result.report_content_hash,
            delivery_revision="6" * 40,
            build=parser_request.build,
        ),
        refs=(
            ArtifactRefV1(
                artifact_id=result.artifact_id,
                role="sec-parser-action-result-v2",
                content_hash=sha256_digest(result),
                media_type="application/json",
            ),
        ),
    )
    evidence = FiscalOriginalValidationEvidenceV1.model_construct(
        request=request,
        outcome=FiscalValidationMatchedV1.model_construct(
            responses=receipts,
            integrity=SecIntegrityEvidenceV1.model_construct(
                primary_document_uri=receipts[0].uri,
                archive_uri=receipts[1].uri,
                archive_size=len(archive_bytes),
                archive_member_name="primary.htm",
                normalized_content_hash=primary_hash,
                parser_input_hash=manifest_hash,
                archive_member_hash=primary_hash,
                inline_documents=(),
            ),
        ),
    )
    source_ref = ArtifactRefV1(
        artifact_id="synthetic-source-validation",
        role="fiscal-original-validation",
        content_hash="7" * 64,
        media_type="application/json",
    )
    return evidence, source_ref, RetainedFiscalActions(action, None), content


def test_binds_zip_dts_without_individual_http_receipts(
    synthetic_retained_inputs: SyntheticRetainedInputs,
) -> None:
    evidence, source_ref, actions, content = synthetic_retained_inputs
    binding = bind_fiscal_retained_inputs(
        evidence,
        source_ref,
        actions,
        content,
        actual_requests=(actions.normalized.request,),
    )
    files = {item.relative_name: item.origin for item in binding.inputs[0].files}
    for name in ("extension.xsd", "extension_cal.xml"):
        origin = files[name]
        assert isinstance(origin, FiscalArchiveInputV1)
        assert origin.member_name == name
        assert (
            origin.member_content.digest == dict(actions.normalized.request.files)[name]
        )
    assert isinstance(files["primary.htm"], FiscalNormalizedInputV1)
    assert isinstance(files["input.ixds.json"], FiscalNormalizedInputV1)
    assert isinstance(files["captured.xml"], FiscalCapturedInputV1)


@pytest.mark.parametrize(
    "failure", ("unknown_normalization_input", "member_hash_mismatch")
)
def test_refuses_inputs_without_exact_retained_origin(
    synthetic_retained_inputs: SyntheticRetainedInputs, failure: str
) -> None:
    evidence, source_ref, actions, content = synthetic_retained_inputs
    request = actions.normalized.request
    if failure == "unknown_normalization_input":
        update = {
            "normalization_inputs": tuple(
                sorted((*request.normalization_inputs, "8" * 64))
            )
        }
        message = "normalization input has no retained origin"
    else:
        update = {
            "files": tuple(
                (name, "8" * 64 if name == "extension.xsd" else digest)
                for name, digest in request.files
            )
        }
        message = "parser file cannot map to an exact retained origin"
    request = ParserActionInputV3.model_validate(request.model_dump() | update)
    action = RetainedFiscalAction(
        report=actions.normalized.report,
        request=request,
        delivery=actions.normalized.delivery,
        refs=actions.normalized.refs,
    )
    with pytest.raises(SnapshotError, match=message) as refusal:
        bind_fiscal_retained_inputs(
            evidence,
            source_ref,
            RetainedFiscalActions(action, None),
            content,
            actual_requests=(request,),
        )
    assert refusal.value.code == "FISCAL_PARSER_ACTION_INVALID"
