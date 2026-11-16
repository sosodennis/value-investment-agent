"""Document-set completeness, exact byte identities, and real Arelle extraction."""

import hashlib
import json
import re
from pathlib import Path
from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from pydantic import ValidationError

from fundamental_service.arelle_parser import (
    ArelleParserError,
    ArelleValidationProfileV1,
    fact_semantic_digest,
    parse_filing_offline,
)
from fundamental_service.inline_xbrl import (
    InlineDocumentInputV1,
    InlineDocumentSetError,
    InlineDocumentSetInputV1,
    read_inline_document_input,
    select_inline_document_set,
    archive_inline_document_names,
    inline_document_metadata,
    submission_html_documents,
)
from fundamental_service.serialization import canonical_bytes


def documents():
    namespaces = (
        'xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" '
        'xmlns:xbrli="http://www.xbrl.org/2003/instance" '
        'xmlns:link="http://www.xbrl.org/2003/linkbase" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" '
        'xmlns:iso4217="http://www.xbrl.org/2003/iso4217" '
        'xmlns:ex="http://example.test/gaap"'
    )
    cover = f"""<html {namespaces}><head><title>Cover</title></head><body>
<ix:nonFraction name="ex:Revenue" contextRef="c1" unitRef="USD" decimals="0">100</ix:nonFraction>
</body></html>""".encode()
    financials = f"""<html {namespaces}><head><title>Financials</title></head><body>
<div style="display:none"><ix:header><ix:references>
<link:schemaRef xlink:type="simple" xlink:href="simple.xsd"/>
</ix:references><ix:resources>
<xbrli:unit id="USD"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
<xbrli:context id="c1"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:context id="c2"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
</ix:resources></ix:header></div>
<ix:nonFraction name="ex:Revenue" contextRef="c2" unitRef="USD" decimals="0">200</ix:nonFraction>
</body></html>""".encode()
    return {"cover.htm": cover, "financials.htm": financials}


def submission_and_index(members):
    submission = b"<SEC-DOCUMENT>0000000001-26-000001.txt\n"
    for name, content in members.items():
        submission += (
            b"<DOCUMENT>\n<TYPE>10-K\n<FILENAME>"
            + name.encode()
            + b"\n<TEXT>\n<XBRL>\n"
            + content
            + b"\n</XBRL>\n</TEXT>\n</DOCUMENT>\n"
        )
    submission += b"</SEC-DOCUMENT>\n"
    index = json.dumps(
        {"directory": {"item": [{"name": n} for n in (*members, "simple.xsd")]}}
    ).encode()
    return submission, index


def stage(tmp_path, encoded_namespace=False):
    members = documents()
    if encoded_namespace:
        members = {
            name: raw.replace(b"/inlineXBRL", b"/inline&#88;BRL")
            for name, raw in members.items()
        }
        members["cover.htm"], members["financials.htm"] = (
            members["financials.htm"],
            members["cover.htm"],
        )
    for name, content in members.items():
        (tmp_path / name).write_bytes(content)
    (tmp_path / "simple.xsd").write_bytes(
        (Path(__file__).parent / "fixtures/simple.xsd").read_bytes()
    )
    manifest = InlineDocumentSetInputV1(
        documents=tuple(
            InlineDocumentInputV1(
                filename=name, content_hash=hashlib.sha256(content).hexdigest()
            )
            for name, content in sorted(members.items())
        )
    )
    path = tmp_path / "input.ixds.json"
    path.write_bytes(canonical_bytes(manifest))
    cache = tmp_path / "cache"
    with ZipFile(
        Path(__file__).parent / "fixtures/sec-edgar/arelle-taxonomy-cache-2024.zip"
    ) as archive:
        archive.extractall(cache)
    return path, manifest, cache


def test_submission_reader_preserves_html_bytes_including_terminal_whitespace():
    members = {"cover.htm": b"<html><body>value \t\n</body></html>\n"}
    submission, _ = submission_and_index(members)
    assert dict(submission_html_documents(submission)) == {
        name: raw + b"\n" for name, raw in members.items()
    }


def test_submission_selects_complete_set_and_exhibit_schema_without_issuer_rules():
    members = documents()
    submission, index = submission_and_index(members)
    assert select_inline_document_set(submission, index, "cover.htm") == (
        ("cover.htm", "financials.htm"),
        "simple.xsd",
    )
    reversed_submission, _ = submission_and_index(
        dict(reversed(tuple(members.items())))
    )
    assert select_inline_document_set(
        reversed_submission, index, "cover.htm"
    ) == select_inline_document_set(submission, index, "cover.htm")


@pytest.mark.parametrize(
    "fault",
    (
        "truncated",
        "duplicate",
        "missing_index",
        "foreign_schema",
        "named_target",
        "unsafe",
        "many",
        "missing_primary",
    ),
)
def test_document_set_refuses_incomplete_ambiguous_or_unsupported_scope(fault):
    members = documents()
    if fault == "foreign_schema":
        members["financials.htm"] = members["financials.htm"].replace(
            b"simple.xsd", b"https://example.test/simple.xsd"
        )
    elif fault == "named_target":
        members["cover.htm"] = members["cover.htm"].replace(
            b"<ix:nonFraction ", b'<ix:nonFraction target="other" '
        )
    elif fault == "unsafe":
        members["../outside.htm"] = members.pop("cover.htm")
    elif fault == "many":
        members.update({f"extra-{i}.htm": members["cover.htm"] for i in range(7)})
    submission, index = submission_and_index(members)
    if fault == "truncated":
        submission = submission.replace(b"</DOCUMENT>", b"", 1)
    elif fault == "duplicate":
        submission = submission.replace(b"financials.htm", b"cover.htm")
    elif fault == "missing_index":
        index = index.replace(b"financials.htm", b"other.htm")
    with pytest.raises(InlineDocumentSetError):
        select_inline_document_set(
            submission,
            index,
            "missing.htm" if fault == "missing_primary" else "cover.htm",
        )


def test_uppercase_extension_and_default_inline_namespace_are_not_omitted():
    members = documents()
    members["notes.HTM"] = (
        members["cover.htm"]
        .replace(
            b"<ix:nonFraction ",
            b'<nonFraction xmlns="http://www.xbrl.org/2013/inlineXBRL" ',
        )
        .replace(b"</ix:nonFraction>", b"</nonFraction>")
    )
    submission, index = submission_and_index(members)
    expected = ("cover.htm", "financials.htm", "notes.HTM")
    assert select_inline_document_set(submission, index, "cover.htm")[0] == expected
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, raw in members.items():
            archive.writestr(name, raw)
    assert archive_inline_document_names(buffer.getvalue()) == expected
    assert (
        InlineDocumentInputV1(filename="notes.HTM", content_hash="a" * 64).filename
        == "notes.HTM"
    )


@pytest.mark.parametrize("container", ("script", "style", "deep"))
def test_xml_inline_nodes_are_never_silently_omitted_from_inventory(container):
    members = documents()
    opening, closing = (
        (b"<div>" * 300, b"</div>" * 300)
        if container == "deep"
        else (f"<{container}>".encode(), f"</{container}>".encode())
    )
    members["notes.htm"] = (
        members["cover.htm"]
        .replace(b"<ix:nonFraction ", opening + b"<ix:nonFraction ")
        .replace(b"</ix:nonFraction>", b"</ix:nonFraction>" + closing)
    )
    submission, index = submission_and_index(members)
    expected = ("cover.htm", "financials.htm", "notes.htm")
    assert select_inline_document_set(submission, index, "cover.htm")[0] == expected
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, raw in members.items():
            archive.writestr(name, raw)
    assert archive_inline_document_names(buffer.getvalue()) == expected


def test_xml_depth_limit_refuses_instead_of_accepting_truncated_inventory():
    raw = documents()["cover.htm"].replace(b"<body>", b"<body>" + b"<div>" * 512)
    with pytest.raises(InlineDocumentSetError, match="XML structure exceeds"):
        inline_document_metadata(raw)


def test_plain_html_without_namespace_cannot_be_inline_even_with_void_elements():
    raw = b"<html><body>" + b"<br>" * 6000 + b"</body></html>"
    assert inline_document_metadata(raw) == (False, ())


def test_utf16_inline_xml_is_not_misclassified_as_namespace_free_ascii():
    raw = documents()["cover.htm"].decode().encode("utf-16")
    assert inline_document_metadata(raw) == (True, ())


@pytest.mark.parametrize(
    ("inline", "size", "accepted"),
    ((True, 13_000_000, True), (False, 13_000_000, False), (True, 24_000_001, False)),
)
def test_inline_members_use_document_limits_and_taxonomy_keeps_resource_limit(
    inline, size, accepted
):
    from fundamental_service.ingestion import read_sec_xbrl_archive
    from fundamental_service.snapshots import SnapshotError

    buffer = BytesIO()
    name = "financials.htm" if inline else "taxonomy.xsd"
    payload = b" " * size
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("cover.htm", documents()["cover.htm"])
        archive.writestr(name, payload)
    args = dict(
        primary_document="cover.htm",
        dts_filenames=() if inline else (name,),
        inline_documents=("cover.htm", name) if inline else (),
    )
    if accepted:
        assert read_sec_xbrl_archive(buffer.getvalue(), **args)[name] == payload
    else:
        with pytest.raises(SnapshotError, match="supported size"):
            read_sec_xbrl_archive(buffer.getvalue(), **args)


def test_schema_reference_under_inherited_xml_base_refuses():
    raw = documents()["financials.htm"].replace(
        b"<body>", b'<body xml:base="https://other.test/">'
    )
    with pytest.raises(InlineDocumentSetError, match="accession base URI"):
        inline_document_metadata(raw)


def test_inline_parser_loads_both_documents_and_cross_document_contexts(tmp_path):
    path, manifest, cache = stage(tmp_path)
    reports = [
        parse_filing_offline(
            path,
            profile=ArelleValidationProfileV1(
                profile_id="inline-set-offline-fixture-v1"
            ),
            taxonomy_version="fixture-taxonomy-v1",
            taxonomy_cache_dir=cache,
            source_content_hash=manifest.digest,
        )
        for _ in range(2)
    ]
    for report in reports:
        assert sorted((f.context_id, f.value) for f in report.facts) == [
            ("c1", "100"),
            ("c2", "200"),
        ]
        assert report.source_content_hash == manifest.digest
        assert report.network_attempt_count == 0
        assert (
            f"sec-inline-document-set-v1:{manifest.digest}"
            in report.validation_evidence
        )
    assert fact_semantic_digest(reports[0]) == fact_semantic_digest(reports[1])
    assert reports[0].replay_digest() == reports[1].replay_digest()


@pytest.mark.parametrize("fault", ("corrupt", "missing", "symlink", "noncanonical"))
def test_manifest_cannot_hide_changed_missing_or_redirected_member_bytes(
    tmp_path, fault
):
    path, manifest, cache = stage(tmp_path)
    if fault == "corrupt":
        (tmp_path / "cover.htm").write_bytes(b"changed")
    elif fault == "missing":
        (tmp_path / "cover.htm").unlink()
    elif fault == "symlink":
        (tmp_path / "cover.htm").rename(tmp_path / "other.htm")
        (tmp_path / "cover.htm").symlink_to(tmp_path / "other.htm")
    else:
        path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(InlineDocumentSetError):
        read_inline_document_input(path)
    with pytest.raises(ArelleParserError, match="inline"):
        parse_filing_offline(
            path,
            profile=ArelleValidationProfileV1(
                profile_id="inline-set-offline-fixture-v1"
            ),
            taxonomy_version="fixture-taxonomy-v1",
            taxonomy_cache_dir=cache,
        )


def test_manifest_rejects_duplicate_members_and_path_traversal():
    doc = InlineDocumentInputV1(filename="cover.htm", content_hash="a" * 64)
    with pytest.raises(ValidationError):
        InlineDocumentSetInputV1(documents=(doc, doc))
    with pytest.raises(ValidationError):
        InlineDocumentInputV1(filename="../cover.htm", content_hash="a" * 64)


@pytest.mark.parametrize(
    ("fault", "encoded_namespace", "padding_member"),
    (
        (None, False, None),
        (None, True, None),
        (None, False, "cover.htm"),
        (None, False, "financials.htm"),
        ("omit_member", False, None),
        ("omit_all", False, None),
        ("corrupt_member", False, None),
    ),
)
def test_ingestion_and_release_bind_every_document_and_manifest(
    tmp_path, monkeypatch, fault, encoded_namespace, padding_member
):
    """Mock regulatory completion only; real acquisition-byte and release guards run."""
    from fundamental_service.contracts import IdentityV1, SourceRole
    from fundamental_service.data_releases import DataReleaseError
    from fundamental_service.ingestion import SecIngestionService
    from fundamental_service.issuer_release_evidence import verify_original_bytes
    from fundamental_service.replay import ArtifactStore
    from fundamental_service.snapshots import (
        CapturedSource,
        FilesystemContentStore,
        FilesystemSnapshotRepository,
        SnapshotError,
    )
    from fundamental_service.source_acquisition import (
        SecAcquisitionUseCase,
        _SelectedFiling,
    )
    from test_source_acquisition import _validation_profile

    path, manifest, cache = stage(tmp_path, encoded_namespace)
    if padding_member is not None:
        padded = tmp_path / padding_member
        padded.write_bytes(
            padded.read_bytes().replace(b"</body>", b"<p>Note \t\n</p>\n</body>")
        )
        manifest = InlineDocumentSetInputV1(
            documents=tuple(
                InlineDocumentInputV1(
                    filename=d.filename,
                    content_hash=hashlib.sha256(
                        (tmp_path / d.filename).read_bytes()
                    ).hexdigest(),
                )
                for d in manifest.documents
            )
        )
        path.write_bytes(canonical_bytes(manifest))
    actual = parse_filing_offline(
        path,
        profile=ArelleValidationProfileV1(profile_id="inline-set-offline-fixture-v1"),
        taxonomy_version="fixture-taxonomy-v1",
        taxonomy_cache_dir=cache,
    )
    members = {
        name: (tmp_path / name).read_bytes() for name in (*documents(), "simple.xsd")
    }
    if fault == "omit_all":
        # A self-contained primary cannot permit silently omitting its exhibit.
        members["cover.htm"], members["financials.htm"] = (
            members["financials.htm"],
            members["cover.htm"],
        )
    direct_members = dict(members)
    if padding_member is not None:
        direct_members[padding_member] = re.sub(
            rb"[ \t]+(?=\n)", b"", members[padding_member]
        )
    submission, _ = submission_and_index(direct_members)
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, raw in members.items():
            archive.writestr(name, raw)
    archive_bytes = buffer.getvalue()
    accession = "0000000001-26-000001"
    archive_name = accession + "-xbrl.zip"
    base = "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/"
    index = json.dumps(
        {
            "directory": {
                "item": [
                    {
                        "name": n,
                        "size": str(
                            len(direct_members[n]) + 1
                            if n == padding_member
                            else len(raw)
                        ),
                    }
                    for n, raw in (members | {archive_name: archive_bytes}).items()
                ]
            }
        }
    ).encode()
    now = datetime(2026, 1, 15, tzinfo=UTC)

    def captured(name, raw, source_id, role, media_type="text/html"):
        return CapturedSource(
            source_id=source_id,
            uri=base + name,
            role=role,
            content=raw,
            media_type=media_type,
            http_status=200,
            available_at=now,
            captured_at=now,
            filed_at=now,
            accession_number=accession,
            form="10-K",
            declared_size=len(raw),
            received_size=len(raw),
            response_headers=(("content-length", str(len(raw))),),
        )

    class Adapter:
        def capture_filing_index(self, **kwargs):
            return captured(
                "index.json",
                index,
                "sec-filing-index",
                SourceRole.REFERENCE,
                "application/json",
            )

        def capture_filing_submission(self, **kwargs):
            return captured(
                accession + ".txt",
                submission,
                "sec-filing-submission",
                SourceRole.FILING,
                "text/plain",
            )

        def capture_filing_archive(self, **kwargs):
            return captured(
                archive_name,
                archive_bytes,
                "sec-filing-archive",
                SourceRole.FILING,
                "application/zip",
            )

        def capture_filing(self, *, primary_document, **kwargs):
            raw = members[primary_document]
            if primary_document == padding_member:
                raw = (direct_members[primary_document] + b"\n").replace(
                    b"</body>",
                    b'<script type="text/javascript" src="/edge/path/token"></script></body>',
                )
            if fault == "corrupt_member" and primary_document == "financials.htm":
                raw = raw.replace(b">200<", b">201<")
            result = captured(primary_document, raw, "sec-filing", SourceRole.FILING)
            if primary_document == padding_member:
                from dataclasses import replace

                result = replace(
                    result,
                    response_headers=(
                        *result.response_headers,
                        ("x-akamai-transformed", "0 - 0 -"),
                    ),
                )
            return result

    adapter = Adapter()
    package = object.__new__(SecAcquisitionUseCase)._capture_original_package(
        adapter=adapter,
        cik="0000000001",
        filing=_SelectedFiling(accession, "10-K", now.date(), now, "cover.htm", True),
        deadline_at=now,
    )
    assert package.inline_documents == ("cover.htm", "financials.htm")
    assert package.dts_filenames == ("simple.xsd",)
    calls = []

    def regulatory_fixture(path, *, profile, source_content_hash, **kwargs):
        assert read_inline_document_input(path) == manifest
        calls.append(source_content_hash)
        return actual.model_copy(
            update={
                "filing_path": str(path),
                "validation_profile": profile,
                "validation_profile_digest": profile.digest(),
                "validation_engines": ("sec-efm", "dqc-us"),
                "validation_evidence": (
                    "strict-sec-efm-profile-selected",
                    "dqc-dqcrt-checks-completed",
                    f"sec-inline-document-set-v1:{manifest.digest}",
                ),
            }
        )

    monkeypatch.setattr(
        "fundamental_service.ingestion.parse_filing_offline", regulatory_fixture
    )
    content = FilesystemContentStore(tmp_path / "objects")
    service = SecIngestionService(
        source_adapter=adapter,
        content_store=content,
        snapshot_repository=FilesystemSnapshotRepository(tmp_path / "snapshots"),
        audit_store=ArtifactStore(tmp_path / "artifacts"),
    )
    args = dict(
        cik="0000000001",
        accession_number=accession,
        primary_document="cover.htm",
        filing_archive_filename=archive_name,
        filed_at=now,
        captured_at=now,
        accepted_at=now,
        taxonomy_manifest_id="synthetic-taxonomy",
        taxonomy_version="fixture-taxonomy-v1",
        taxonomy_cache_dir=cache,
        dts_filenames=("simple.xsd",),
        profile=_validation_profile(),
        submission_source=adapter.capture_filing_submission(),
        inline_documents=("cover.htm",)
        if fault == "omit_member"
        else ()
        if fault == "omit_all"
        else package.inline_documents,
    )
    if fault is not None:
        with pytest.raises(SnapshotError):
            service.validate_filing(**args)
        assert not calls
        return
    validated = service.validate_filing(**args)
    integrity = validated.integrity_evidence
    assert integrity.parser_input_hash == manifest.digest
    assert len(integrity.inline_documents) == 2
    assert {s.source_id for s in validated.captured_sources} >= {
        "sec-filing",
        "sec-inline-document",
    }
    contents = {p.stem: p.read_bytes() for p in (tmp_path / "objects").glob("*/*")}
    verify_original_bytes(integrity, contents)
    if padding_member is not None:
        submission_hash = hashlib.sha256(submission).hexdigest()
        assert integrity.submission_content_hashes == (submission_hash,)
        assert integrity.submission_content_hash == (
            submission_hash if padding_member == "cover.htm" else None
        )
        member = next(
            d
            for d in integrity.inline_documents
            if d.document.filename == padding_member
        )
        assert member.submission_content_hash == submission_hash
        with pytest.raises(DataReleaseError):
            verify_original_bytes(
                integrity, {k: v for k, v in contents.items() if k != submission_hash}
            )
    mixed_submission = integrity.model_copy(
        update={
            "inline_documents": tuple(
                member.model_copy(
                    update={"submission_content_hash": "a" * 64 if i == 0 else "b" * 64}
                )
                for i, member in enumerate(integrity.inline_documents)
            )
        }
    )
    with pytest.raises(ValidationError, match="one complete submission"):
        type(integrity).model_validate(mixed_submission.model_dump())
    with pytest.raises(DataReleaseError, match="same complete submission"):
        verify_original_bytes(mixed_submission, contents)
    single_claim = integrity.model_copy(
        update={
            "inline_documents": (),
            "parser_input_hash": integrity.normalized_content_hash,
            "validation_evidence": tuple(
                v
                for v in integrity.validation_evidence
                if not v.startswith("sec-inline-document-set-v1:")
            ),
        }
    )
    with pytest.raises(DataReleaseError) as missing_set:
        verify_original_bytes(single_claim, contents)
    assert missing_set.value.code == "DATA_RELEASE_ORIGINAL_DOCUMENT_SET_MISMATCH"
    extra_members = members | {"notes.HTM": members["cover.htm"]}
    extra_buffer = BytesIO()
    with ZipFile(extra_buffer, "w") as archive:
        for name, raw in extra_members.items():
            archive.writestr(name, raw)
    extra_zip = extra_buffer.getvalue()
    extra_index = json.dumps(
        {
            "directory": {
                "item": [
                    {"name": n, "size": str(len(raw))}
                    for n, raw in (extra_members | {archive_name: extra_zip}).items()
                ]
            }
        }
    ).encode()
    extra_zip_hash = hashlib.sha256(extra_zip).hexdigest()
    extra_index_hash = hashlib.sha256(extra_index).hexdigest()
    partial_claim = integrity.model_copy(
        update={
            "archive_hash": extra_zip_hash,
            "archive_size": len(extra_zip),
            "archive_index_hash": extra_index_hash,
        }
    )
    with pytest.raises(DataReleaseError) as omitted_third:
        verify_original_bytes(
            partial_claim,
            contents | {extra_zip_hash: extra_zip, extra_index_hash: extra_index},
        )
    assert omitted_third.value.code == "DATA_RELEASE_ORIGINAL_DOCUMENT_SET_MISMATCH"
    with pytest.raises(DataReleaseError, match="retain raw"):
        verify_original_bytes(
            integrity,
            {
                k: v
                for k, v in contents.items()
                if k != manifest.documents[1].content_hash
            },
        )
    with pytest.raises(DataReleaseError) as corrupt_bytes:
        verify_original_bytes(
            integrity, contents | {manifest.documents[1].content_hash: b"changed"}
        )
    assert corrupt_bytes.value.code in {
        "SOURCE_INTEGRITY_MISMATCH",
        "DATA_RELEASE_ORIGINAL_BYTES_MISMATCH",
    }
    prepared = service.prepare_filing(
        **args,
        valuation_timestamp=now,
        parser_version="2.47.4",
        policy_version="synthetic",
        identity=IdentityV1(
            issuer_id="0000000001",
            issuer_name="Synthetic",
            domicile="US",
            reporting_basis="us-gaap",
            security_id="EX",
            share_class="common",
            currency="USD",
        ),
        mappings=(),
    )
    assert any(
        s.source_id == "sec-inline-document" for s in prepared.snapshot.source_records
    )
    assert prepared.snapshot.sec_integrity_evidence == integrity
