from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
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
    RetainedFiscalValidation,
    bind_fiscal_retained_inputs,
)
from fundamental_service.fiscal_source_closure import FiscalSourceContentRead
from fundamental_service.fiscal_source_contracts import FiscalFilingV1
from fundamental_service.fiscal_source_validation import SecFiscalSourceValidation
from fundamental_service.fiscal_validation_contracts import (
    FiscalArchiveInputV1,
    FiscalCapturedInputV1,
    FiscalNormalizedInputV1,
    FiscalOriginalValidationEvidenceV1,
    FiscalValidationMatchedV1,
    FiscalValidationPinV1,
    ResolvedFiscalValidationRequestV1,
)
from fundamental_service.parser_action_contracts import (
    ParserActionDeliveryV2,
    ParserActionInputV3,
    ParserActionResultV2,
    ParserBuildIdentityV1,
)
from fundamental_service.replay import ArtifactRecordV1, ArtifactStore
from fundamental_service.sec_capture import (
    SecResponseReceiptV1,
    sec_response_artifact_id,
)
from fundamental_service.sec_source import SecEdgarSourceAdapter, SecRequestPolicy
from fundamental_service.serialization import sha256_digest
from fundamental_service.snapshots import FilesystemContentStore, SnapshotError
from fundamental_service.source_acquisition import SecAcquisitionUseCase

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


@dataclass(frozen=True)
class CurrentRetainedInputs:
    validation: SecFiscalSourceValidation
    evidence: FiscalOriginalValidationEvidenceV1
    source_ref: ArtifactRefV1
    actions: RetainedFiscalActions
    content: FilesystemContentStore
    artifacts: ArtifactStore
    members: dict[str, bytes]
    deadline: datetime


def _retained_files(inputs: CurrentRetainedInputs) -> dict[Path, tuple[bytes, int]]:
    return {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in inputs.content.root.parent.rglob("*")
        if path.is_file()
    }


@pytest.fixture
def current_retained_inputs(
    synthetic_retained_inputs: SyntheticRetainedInputs,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> CurrentRetainedInputs:
    evidence, source_ref, actions, content = synthetic_retained_inputs
    old_primary, old_archive, captured = evidence.outcome.responses
    with ZipFile(
        BytesIO(content.get(old_archive.content_hash, media_type="application/zip"))
    ) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    members["extension.xml"] = content.get(
        old_primary.content_hash, media_type="text/html"
    )
    members["unselected.xml"] = b"unselected XML member"
    members["unselected.xsd"] = b"unselected schema member"
    archive_buffer = BytesIO()
    with ZipFile(archive_buffer, "w") as archive:
        for name, raw in members.items():
            archive.writestr(name, raw)
    archive_bytes = archive_buffer.getvalue()
    filing = FiscalFilingV1(
        cik=evidence.request.filing.cik,
        accession_number=evidence.request.filing.accession_number,
        form="10-Q",
        filing_date=date(2024, 1, 1),
        accepted_at=datetime(2024, 1, 1, tzinfo=UTC),
        report_period_end=date(2023, 12, 31),
        primary_document="extension.xml",
        is_xbrl=True,
        is_inline_xbrl=False,
    )
    pin = FiscalValidationPinV1(
        declared_source_revision="6" * 40, taxonomy_manifest_id="synthetic"
    )
    request = evidence.request.model_copy(update={"filing": filing, "pin": pin})
    folder = old_primary.uri.rsplit("/", 1)[0]
    archive_name = f"{filing.accession_number}-xbrl.zip"
    index = json.dumps(
        {
            "directory": {
                "item": [
                    {"name": name, "size": len(raw)} for name, raw in members.items()
                ]
                + [{"name": archive_name, "size": len(archive_bytes)}]
            }
        }
    ).encode()
    receipts = tuple(
        sorted(
            (
                captured,
                *(
                    old_primary.model_copy(
                        update={
                            "uri": f"{folder}/{name}",
                            "content_hash": content.put(raw, media_type=media),
                            "media_type": media,
                            "declared_size": len(raw),
                            "received_size": len(raw),
                        }
                    )
                    for name, raw, media in (
                        (
                            filing.primary_document,
                            members[filing.primary_document],
                            "application/xml",
                        ),
                        (archive_name, archive_bytes, "application/zip"),
                        ("index.json", index, "application/json"),
                        (
                            f"{filing.accession_number}.txt",
                            b"synthetic submission",
                            "text/plain",
                        ),
                    )
                ),
            ),
            key=lambda item: item.uri,
        )
    )
    for name in ("extension.xsd", "extension_cal.xml"):
        content.put(members[name], media_type="application/xml")
    parser_request = actions.normalized.request.model_copy(
        update={
            "files": tuple(
                sorted(
                    ("extension.xml" if name == "primary.htm" else name, digest)
                    for name, digest in actions.normalized.request.files
                )
            )
        }
    )
    action = RetainedFiscalAction(
        report=actions.normalized.report,
        request=parser_request,
        delivery=actions.normalized.delivery,
        refs=actions.normalized.refs,
    )
    actions = RetainedFiscalActions(action, None)
    outcome = evidence.outcome.model_copy(
        update={
            "responses": receipts,
            "integrity": evidence.outcome.integrity.model_copy(
                update={
                    "primary_document_uri": f"{folder}/{filing.primary_document}",
                    "archive_uri": f"{folder}/{archive_name}",
                    "archive_size": len(archive_bytes),
                    "archive_member_name": filing.primary_document,
                }
            ),
        }
    )
    evidence = FiscalOriginalValidationEvidenceV1.model_construct(
        request=request, outcome=outcome
    )
    artifacts = ArtifactStore(tmp_path / "receipts")
    for receipt in receipts:
        artifacts.put(
            sec_response_artifact_id(request.scope, receipt.uri),
            receipt,
            (receipt.content_hash,),
        )
    provider = SecEdgarSourceAdapter(
        SecRequestPolicy(user_agent="synthetic-test test@example.com")
    )

    def refuse_provider_io(*args: object, **kwargs: object) -> None:
        raise AssertionError(
            "current content observation must not contact the provider"
        )

    monkeypatch.setattr(provider, "_request", refuse_provider_io)
    owner = SecAcquisitionUseCase(
        adapter=provider,
        ingestion=None,
        metadata=None,
        content_store=content,
        settings=None,
        authorized_organizations=frozenset(),
        capture_store=artifacts,
    )
    return CurrentRetainedInputs(
        SecFiscalSourceValidation(owner, pin=pin, store=artifacts),
        evidence,
        source_ref,
        actions,
        content,
        artifacts,
        members,
        datetime.now(UTC) + timedelta(minutes=5),
    )


def test_current_content_matches_normal_selected_dts_consumption_and_archive_origins(
    current_retained_inputs: CurrentRetainedInputs,
) -> None:
    inputs = current_retained_inputs
    normal = FiscalSourceContentRead(inputs.content, lambda: None)
    for receipt in inputs.evidence.outcome.responses:
        normal.get(receipt.content_hash, media_type=receipt.media_type)
    retained = RetainedFiscalValidation(inputs.artifacts, normal, inputs.actions)
    for name in ("extension.xsd", "extension_cal.xml"):
        retained.match_content(inputs.members[name], media_type="application/xml")
    normal_binding = bind_fiscal_retained_inputs(
        inputs.evidence,
        inputs.source_ref,
        inputs.actions,
        normal,
        actual_requests=(inputs.actions.normalized.request,),
    )
    current = FiscalSourceContentRead(inputs.content, lambda: None)
    before = _retained_files(inputs)
    inputs.validation._observe_current_content(
        inputs.evidence.request,
        inputs.evidence.outcome,
        inputs.actions,
        current,
        artifacts=inputs.artifacts,
        deadline_at=inputs.deadline,
    )
    current_binding = bind_fiscal_retained_inputs(
        inputs.evidence,
        inputs.source_ref,
        inputs.actions,
        current,
        actual_requests=(inputs.actions.normalized.request,),
    )
    assert current.input_footprint == normal.input_footprint
    assert current_binding == normal_binding
    for name in ("extension.xsd", "extension_cal.xml"):
        origin = next(
            item.origin
            for item in current_binding.inputs[0].files
            if item.relative_name == name
        )
        assert isinstance(origin, FiscalArchiveInputV1)
        assert origin.member_content.media_type == "application/octet-stream"
        assert (
            hashlib.sha256(inputs.members[name]).hexdigest(),
            "application/xml",
            len(inputs.members[name]),
        ) in current.input_footprint
    for name in ("unselected.xml", "unselected.xsd"):
        assert hashlib.sha256(inputs.members[name]).hexdigest() not in {
            digest for digest, _, _ in current.input_footprint
        }
    assert _retained_files(inputs) == before


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    (("missing", "SOURCE_BYTES_UNAVAILABLE"), ("corrupt", "SOURCE_HASH_MISMATCH")),
)
def test_current_and_normal_refuse_missing_or_corrupt_selected_dts_content(
    current_retained_inputs: CurrentRetainedInputs,
    failure: str,
    expected_code: str,
) -> None:
    inputs = current_retained_inputs
    selected = inputs.members["extension_cal.xml"]
    path = inputs.content._path(hashlib.sha256(selected).hexdigest(), "application/xml")
    if failure == "missing":
        path.unlink()
    else:
        path.write_bytes(b"corrupt")
    before = _retained_files(inputs)
    normal = FiscalSourceContentRead(inputs.content, lambda: None)
    with pytest.raises(SnapshotError) as normal_refusal:
        RetainedFiscalValidation(
            inputs.artifacts, normal, inputs.actions
        ).match_content(selected, media_type="application/xml")
    assert normal_refusal.value.code == expected_code
    current = FiscalSourceContentRead(inputs.content, lambda: None)
    with pytest.raises(SnapshotError) as current_refusal:
        inputs.validation._observe_current_content(
            inputs.evidence.request,
            inputs.evidence.outcome,
            inputs.actions,
            current,
            artifacts=inputs.artifacts,
            deadline_at=inputs.deadline,
        )
    assert current_refusal.value.code == expected_code
    assert _retained_files(inputs) == before


@pytest.mark.parametrize("resource", ("index.json", "submission", "archive"))
def test_current_content_refuses_missing_receipt_without_fetch_or_publication(
    current_retained_inputs: CurrentRetainedInputs,
    monkeypatch: pytest.MonkeyPatch,
    resource: str,
) -> None:
    inputs = current_retained_inputs
    filing = inputs.evidence.request.filing
    name = {
        "index.json": "index.json",
        "submission": f"{filing.accession_number}.txt",
        "archive": f"{filing.accession_number}-xbrl.zip",
    }[resource]
    receipt = next(
        item
        for item in inputs.evidence.outcome.responses
        if item.uri.endswith("/" + name)
    )
    missing = sec_response_artifact_id(inputs.evidence.request.scope, receipt.uri)
    original_get = inputs.artifacts.get

    def missing_receipt(identity: str) -> ArtifactRecordV1:
        if identity == missing:
            raise SnapshotError("ARTIFACT_NOT_FOUND", "synthetic receipt is absent")
        return original_get(identity)

    monkeypatch.setattr(inputs.artifacts, "get", missing_receipt)
    before = _retained_files(inputs)
    with pytest.raises(SnapshotError) as refusal:
        inputs.validation._observe_current_content(
            inputs.evidence.request,
            inputs.evidence.outcome,
            inputs.actions,
            FiscalSourceContentRead(inputs.content, lambda: None),
            artifacts=inputs.artifacts,
            deadline_at=inputs.deadline,
        )
    assert refusal.value.code == "SEC_CAPTURE_MISSING"
    assert _retained_files(inputs) == before
