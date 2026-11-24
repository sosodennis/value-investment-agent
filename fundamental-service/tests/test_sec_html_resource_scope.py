from dataclasses import replace
from pathlib import Path

import pytest
from fundamental_service.contracts import (
    SecIntegrityEvidenceV1,
    SecInlineDocumentIntegrityV1,
)
from fundamental_service.data_releases import DataReleaseError
from fundamental_service.ingestion import SecIngestionService
from fundamental_service.issuer_release_evidence import (
    verify_original_bytes,
    verify_original_integrity,
)
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_html_representation_registry import (
    REGISTERED_HTML_BLOCK_POLICY,
    REGISTRATIONS,
)
from fundamental_service.snapshots import (
    FilesystemContentStore,
    FilesystemSnapshotRepository,
    SnapshotError,
)
from test_issuer_operating_release import fixture
from test_sec_html_representation import _assess, _retained_sources


@pytest.mark.parametrize("mutation", ("profile", "cache", "missing-cache"))
@pytest.mark.parametrize("representation", ("normalized", "archive"))
def test_ingestion_refuses_registered_html_with_wrong_actual_parser_resources(
    tmp_path: Path, monkeypatch, mutation: str, representation: str
):
    (registered,) = REGISTRATIONS
    sources, _ = _retained_sources(registered.accession_number)
    raw, index, archive, submission = sources
    accepted_at = raw.available_at
    submission = replace(submission, form="10-K", filed_at=accepted_at)
    bundle, _, _, _, _ = fixture(tmp_path / "synthetic-report")
    report = bundle.sources[0].originals[0].report
    calls = []

    def fake_parser(path, *, source_content_hash, **_kwargs):
        name = Path(path).parent.name
        calls.append(name)
        profile, cache = (
            registered.validation_profile_digest,
            registered.taxonomy_cache_hash,
        )
        if name == representation:
            if mutation == "profile":
                profile = "a" * 64
            else:
                cache = None if mutation == "missing-cache" else "a" * 64
        return report.model_copy(
            update={
                "source_content_hash": source_content_hash,
                "validation_profile_digest": profile,
                "taxonomy_cache_hash": cache,
            }
        )

    class RetainedAdapter:
        def capture_filing_archive(self, **_kwargs):
            return archive

        def capture_filing(self, **_kwargs):
            return raw

    monkeypatch.setattr(
        "fundamental_service.ingestion.parse_filing_offline", fake_parser
    )
    snapshots = FilesystemSnapshotRepository(tmp_path / "snapshots")
    service = SecIngestionService(
        source_adapter=RetainedAdapter(),
        content_store=FilesystemContentStore(tmp_path / "content"),
        snapshot_repository=snapshots,
        audit_store=ArtifactStore(tmp_path / "artifacts"),
    )
    with pytest.raises(SnapshotError) as refused:
        service.validate_filing(
            cik=registered.issuer_id,
            accession_number=registered.accession_number,
            primary_document=registered.primary_document,
            filed_at=accepted_at,
            captured_at=raw.captured_at,
            taxonomy_manifest_id="test-resource-scope-boundary",
            taxonomy_version=report.taxonomy_version,
            taxonomy_cache_dir=tmp_path,
            reference_sources=(index,),
            submission_source=submission,
            profile=report.validation_profile,
        )
    assert refused.value.code == "SOURCE_HTML_REPRESENTATION_RESOURCE_SCOPE_MISMATCH"
    assert calls == (
        ["normalized"] if representation == "normalized" else ["normalized", "archive"]
    )
    assert not tuple(snapshots.root.glob("*.json"))


@pytest.mark.parametrize("mutation", ("profile", "cache", "missing-cache"))
@pytest.mark.parametrize("location", ("primary", "inline-member"))
def test_release_rechecks_registered_html_against_actual_report_resources(
    tmp_path: Path, mutation: str, location: str
):
    (registered,) = REGISTRATIONS
    bundle, _, evidence, _, _ = fixture(tmp_path)
    original = bundle.sources[0].originals[0]
    profile, cache = (
        registered.validation_profile_digest,
        registered.taxonomy_cache_hash,
    )
    if mutation == "profile":
        profile = "a" * 64
    else:
        cache = None if mutation == "missing-cache" else "a" * 64
    original = original.model_copy(
        update={
            "report": original.report.model_copy(
                update={
                    "validation_profile_digest": profile,
                    "taxonomy_cache_hash": cache,
                }
            )
        }
    )
    integrity = SecIntegrityEvidenceV1.model_validate_json(
        evidence.read("synthetic-integrity")
    )
    if location == "primary":
        integrity = integrity.model_copy(
            update={
                "normalization_policy_id": REGISTERED_HTML_BLOCK_POLICY,
                "archive_member_hash": registered.archive_member_hash,
            }
        )
    else:
        member = SecInlineDocumentIntegrityV1(
            document={
                "filename": registered.primary_document,
                "content_hash": registered.archive_member_hash,
            },
            raw_content_hash="a" * 64,
            raw_received_size=1,
            declared_primary_size=1,
            archive_member_hash=registered.archive_member_hash,
            archive_member_size=1,
            integrity_relation="normalized",
            normalization_policy_id=REGISTERED_HTML_BLOCK_POLICY,
            normalization_rule_signature="b" * 64,
        )
        integrity = integrity.model_copy(update={"inline_documents": (member,)})
    with pytest.raises(DataReleaseError) as refused:
        verify_original_integrity(
            original, integrity, parser_version=original.report.parser_version
        )
    assert refused.value.code == "SOURCE_HTML_REPRESENTATION_RESOURCE_SCOPE_MISMATCH"


@pytest.mark.parametrize(
    "mutation", (None, "policy", "signature", "submission", "unbound")
)
def test_release_replays_registered_original_bytes_and_rejects_changed_proof(
    tmp_path: Path, mutation: str | None
):
    (registered,) = REGISTRATIONS
    sources, _ = _retained_sources(registered.accession_number)
    raw, index, archive, submission = sources
    assessment = _assess(sources)
    _, _, evidence, _, _ = fixture(tmp_path)
    base = SecIntegrityEvidenceV1.model_validate_json(
        evidence.read("synthetic-integrity")
    )
    integrity = SecIntegrityEvidenceV1.model_validate(
        base.model_dump()
        | {
            "accession_number": registered.accession_number,
            "primary_document_uri": raw.uri,
            "archive_index_uri": index.uri,
            "archive_uri": archive.uri,
            "archive_size": len(archive.content),
            "raw_received_size": len(raw.content),
            "archive_member_size": len(assessment.archive_member),
            "normalized_content_size": len(assessment.normalized_content),
            "integrity_relation": assessment.relation,
            "parser_input_hash": assessment.normalized_content_hash,
            **{
                name: getattr(assessment, name)
                for name in (
                    "archive_index_hash",
                    "declared_primary_size",
                    "raw_content_hash",
                    "archive_hash",
                    "archive_member_name",
                    "archive_member_hash",
                    "normalized_content_hash",
                    "normalization_policy_id",
                    "normalization_rule_signature",
                    "normalization_reason",
                    "removed_ranges",
                    "submission_content_hash",
                )
            },
            "raw_response_headers": raw.response_headers,
        }
    )
    contents = {
        assessment.raw_content_hash: raw.content,
        assessment.archive_index_hash: index.content,
        assessment.archive_hash: archive.content,
        assessment.normalized_content_hash: assessment.archive_member,
        assessment.submission_content_hash: submission.content,
    }
    if mutation == "policy":
        integrity = integrity.model_copy(
            update={"normalization_policy_id": "unregistered-v0"}
        )
    elif mutation == "signature":
        integrity = integrity.model_copy(
            update={"normalization_rule_signature": "a" * 64}
        )
    elif mutation == "submission":
        contents[assessment.submission_content_hash] = submission.content + b"\n"
    elif mutation == "unbound":
        integrity = integrity.model_copy(update={"submission_content_hash": None})
    if mutation is None:
        verify_original_bytes(integrity, contents)
    else:
        with pytest.raises(DataReleaseError):
            verify_original_bytes(integrity, contents)
