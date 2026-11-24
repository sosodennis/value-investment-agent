import hashlib
import io
import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fundamental_service.contracts import SourceRole
from fundamental_service.sec_integrity import (
    SecIntegrityAssessment,
    assess_filing_response,
    require_registered_html_resource_scope,
)
from fundamental_service.sec_html_representation_registry import (
    REGISTERED_HTML_BLOCK_POLICY,
    REGISTRATIONS,
)
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import CapturedSource, SnapshotError


ACCESSION = "0001564590-21-039151"
PRIMARY = "msft-10k_20210630.htm"
BASE_URI = (
    f"https://www.sec.gov/Archives/edgar/data/789019/{ACCESSION.replace('-', '')}"
)
SCRIPT = b'<script type="text/javascript" src="/edge/path/token"></script>'
CAPTURED_AT = datetime(2026, 11, 24, tzinfo=UTC)
Sources = tuple[CapturedSource, CapturedSource, CapturedSource, CapturedSource]


def _source(name: str, content: bytes, *, source_id: str) -> CapturedSource:
    return CapturedSource(
        source_id=source_id,
        uri=f"{BASE_URI}/{name}",
        content=content,
        role=SourceRole.FILING,
        media_type="text/html",
        http_status=200,
        captured_at=CAPTURED_AT,
        available_at=CAPTURED_AT,
        accession_number=ACCESSION,
        response_headers=(("x-akamai-transformed", "0 - 0 -"),),
    )


def _sources(
    *,
    remove_intertag_lf: bool = False,
    member: bytes = b"<html>\r\n<head></head>\r\n<body>\r\n<p>Revenue 123</p>\r\n<p>456</p>\r\n</body>\r\n</html>\r\n",
    body: bytes | None = None,
) -> tuple[Sources, bytes]:
    body = member.replace(b"\r\n", b"\n") if body is None else body
    if remove_intertag_lf:
        body = body.replace(b"</p>\n<p>", b"</p><p>")
    raw = _source(
        PRIMARY,
        body.replace(b"</body>", SCRIPT + b"</body>"),
        source_id="sec-filing",
    )
    payload = io.BytesIO()
    with ZipFile(payload, "w", ZIP_DEFLATED) as package:
        package.writestr(PRIMARY, member)
    archive = _source(
        f"{ACCESSION}-xbrl.zip", payload.getvalue(), source_id="sec-filing-archive"
    )
    index = _source(
        "index.json",
        json.dumps(
            {
                "directory": {
                    "item": [
                        {"name": PRIMARY, "size": str(len(body))},
                        {
                            "name": f"{ACCESSION}-xbrl.zip",
                            "size": str(len(archive.content)),
                        },
                    ]
                }
            }
        ).encode(),
        source_id="sec-filing-index",
    )
    submission = _source(
        f"{ACCESSION}.txt",
        (
            f"<SEC-DOCUMENT>{ACCESSION}.txt\n<DOCUMENT>\n<TYPE>10-K\n"
            f"<FILENAME>{PRIMARY}\n<TEXT>\n<XBRL>\n".encode()
            + body
            + b"</XBRL>\n</TEXT>\n</DOCUMENT>\n</SEC-DOCUMENT>\n"
        ),
        source_id="sec-filing-submission",
    )
    return (raw, index, archive, submission), member


def _assess(sources: Sources) -> SecIntegrityAssessment:
    raw, index, archive, submission = sources
    return assess_filing_response(
        raw_response=raw,
        archive_index=index,
        archive=archive,
        submission_source=submission,
    )


def test_submission_proves_html_crlf_representation_and_preserves_archive():
    sources, member = _sources()
    result = _assess(sources)

    assert result.normalized_content == result.archive_member == member
    assert result.normalized_content_hash == hashlib.sha256(member).hexdigest()
    assert result.normalization_policy_id == "sec-edgar-submission-html-crlf-v1"
    assert (
        result.submission_content_hash == hashlib.sha256(sources[3].content).hexdigest()
    )
    assert result == _assess(sources)
    assert tuple(
        sources[0].content[item.start : item.end] for item in result.removed_ranges
    ) == (SCRIPT,)


@pytest.mark.parametrize(
    "mutation",
    (
        "metadata",
        "raw-uri",
        "archive-accession",
        "index-size",
        "zip-size",
        "zip-bytes",
        "submission-uri",
        "submission-accession",
        "submission-header",
        "submission-incomplete",
        "submission-duplicate",
        "submission-filename",
        "submission-value",
        "direct-value",
        "matched-value",
        "matched-text-space",
        "no-script",
        "duplicate-script",
        "moved-script",
        "extra-final-lf",
    ),
)
def test_html_representation_rejects_unproved_sources_or_content(mutation: str):
    (raw, index, archive, submission), _ = _sources(remove_intertag_lf=True)
    if mutation == "metadata":
        raw = replace(raw, response_headers=())
    elif mutation == "raw-uri":
        raw = replace(raw, uri=raw.uri.replace("/789019/", "/320193/"))
    elif mutation == "archive-accession":
        archive = replace(archive, accession_number="0001564590-22-039151")
    elif mutation in {"index-size", "zip-size"}:
        data = json.loads(index.content)
        item = data["directory"]["item"][1 if mutation == "zip-size" else 0]
        item["size"] = str(int(item["size"]) + 1)
        index = replace(index, content=json.dumps(data).encode())
    elif mutation == "zip-bytes":
        archive = replace(archive, content=archive.content + b"\n")
    elif mutation == "submission-uri":
        submission = replace(submission, uri=f"{BASE_URI}/other.txt")
    elif mutation == "submission-accession":
        submission = replace(submission, accession_number="0001564590-22-039151")
    elif mutation == "submission-header":
        submission = replace(
            submission,
            content=submission.content.replace(
                ACCESSION.encode(), b"0001564590-22-039151"
            ),
        )
    elif mutation == "submission-incomplete":
        submission = replace(
            submission, content=submission.content.replace(b"</SEC-DOCUMENT>", b"")
        )
    elif mutation == "submission-duplicate":
        start = submission.content.index(b"<DOCUMENT>")
        end = submission.content.index(b"</SEC-DOCUMENT>")
        submission = replace(
            submission, content=submission.content[:end] + submission.content[start:]
        )
    elif mutation == "submission-filename":
        submission = replace(
            submission,
            content=submission.content.replace(PRIMARY.encode(), b"other.htm"),
        )
    elif mutation == "submission-value":
        submission = replace(
            submission, content=submission.content.replace(b"123", b"124")
        )
    elif mutation in {"direct-value", "matched-value"}:
        raw = replace(raw, content=raw.content.replace(b"123", b"124"))
        if mutation == "matched-value":
            submission = replace(
                submission, content=submission.content.replace(b"123", b"124")
            )
    elif mutation == "matched-text-space":
        raw = replace(raw, content=raw.content.replace(b"Revenue", b"Re venue"))
        submission = replace(
            submission, content=submission.content.replace(b"Revenue", b"Re venue")
        )
    elif mutation == "no-script":
        raw = replace(raw, content=raw.content.replace(SCRIPT, b""))
    elif mutation == "duplicate-script":
        raw = replace(raw, content=raw.content.replace(SCRIPT, SCRIPT + SCRIPT))
    elif mutation == "moved-script":
        raw = replace(
            raw,
            content=raw.content.replace(SCRIPT, b"").replace(b"123", SCRIPT + b"123"),
        )
    elif mutation == "extra-final-lf":
        raw = replace(raw, content=raw.content + b"\n")
    with pytest.raises(SnapshotError):
        _assess((raw, index, archive, submission))


def test_html_representation_requires_independent_submission():
    (raw, index, archive, _), _ = _sources()
    with pytest.raises(SnapshotError):
        assess_filing_response(raw_response=raw, archive_index=index, archive=archive)


@pytest.mark.parametrize(
    "markup",
    (
        b'<p data-note=">\r\n<">123</p>',
        b"<!-- >\r\n< --><p>123</p>",
        b"<![unknown[ >\r\n< ]]><p>123</p>",
        b"<script>var token = '>\r\n<';</script><p>123</p>",
        b"<p>Revenue\r\n123</p>",
        b"<p>123</p> \r\n<p>456</p>",
    ),
    ids=(
        "attribute",
        "comment",
        "declaration",
        "script-data",
        "financial-text",
        "space-before-lf",
    ),
)
def test_html_line_removal_cannot_change_tag_content_or_other_whitespace(markup: bytes):
    member = b"<html>\r\n<body>\r\n" + markup + b"\r\n</body>\r\n</html>\r\n"
    body = member.replace(b"\r\n", b"\n")
    body = body.replace(markup.replace(b"\r\n", b"\n"), markup.replace(b"\r\n", b""))
    sources, _ = _sources(member=member, body=body)
    with pytest.raises(SnapshotError):
        _assess(sources)


def test_unknown_intertag_offsets_refuse_even_with_multibyte_html_text():
    member = (
        "<html>\r\n<body>\r\n<p>Révenue 123</p>\r\n<p>456</p>\r\n</body>\r\n</html>\r\n"
    ).encode()
    sources, _ = _sources(member=member, remove_intertag_lf=True)
    with pytest.raises(SnapshotError) as refused:
        _assess(sources)
    assert refused.value.code == "SOURCE_HTML_REPRESENTATION_UNREGISTERED"


@pytest.mark.parametrize(
    "tag",
    (
        "pre",
        "listing",
        "xmp",
        "plaintext",
        "iframe",
        "noembed",
        "noframes",
        "noscript",
        "select",
        "script",
        "style",
        "textarea",
        "title",
        "ix:nonNumeric",
        "ix:nonFraction",
        "ix:continuation",
        "ix:footnote",
        "span",
        "unknown-container",
    ),
)
@pytest.mark.parametrize("case", ("lowercase", "uppercase", "nested", "unclosed"))
def test_intertag_removal_refuses_content_sensitive_or_unknown_ancestors(
    tag: str, case: str
):
    tag = tag.upper() if case == "uppercase" else tag
    opening, closing = f"<{tag}>".encode(), f"</{tag}>".encode()
    if case == "nested":
        opening, closing = opening + b"<div>", b"</div>" + closing
    elif case == "unclosed":
        closing = b""
    member = (
        b"<html>\r\n<body>\r\n"
        + opening
        + b"<p>Operating</p>\r\n<p>Lease</p>"
        + closing
        + b"\r\n</body>\r\n</html>\r\n"
    )
    sources, _ = _sources(member=member, remove_intertag_lf=True)
    with pytest.raises(SnapshotError):
        _assess(sources)


@pytest.mark.parametrize(
    "prefix",
    (
        b"<pre/>",
        b"<PRE />",
        b"<listing/>",
        b"<xmp/>",
        b"<plaintext/>",
        b"<iframe/>",
        b"<noembed/>",
        b"<noframes/>",
        b"<noscript/>",
        b"<select/>",
        b"<script/>",
        b"<style/>",
        b"<textarea/>",
        b"<title/>",
        b"<ix:nonNumeric/>",
        b"<pre><div></pre>",
        b"<plaintext>text</plaintext>",
        b"<unknown/>",
    ),
)
def test_intertag_removal_refuses_ambiguous_or_mismatched_context(prefix: bytes):
    member = (
        b"<html>\r\n<body>\r\n"
        + prefix
        + b"<p>Operating</p>\r\n<p>Lease</p>\r\n</body>\r\n</html>\r\n"
    )
    sources, _ = _sources(member=member, remove_intertag_lf=True)
    with pytest.raises(SnapshotError):
        _assess(sources)


@pytest.mark.parametrize(
    "attributes",
    (
        b'xml:space="preserve"',
        b'style="white-space: pre"',
        b'style="WHITE-SPACE:pre-wrap"',
        b'style="white-space-collapse:preserve"',
        b'style="display:inline"',
    ),
)
def test_intertag_removal_refuses_explicit_whitespace_preserving_layout(
    attributes: bytes,
):
    member = (
        b"<html>\r\n<body>\r\n<div "
        + attributes
        + b"><p>Operating</p>\r\n<p>Lease</p></div>\r\n</body>\r\n</html>\r\n"
    )
    sources, _ = _sources(member=member, remove_intertag_lf=True)
    with pytest.raises(SnapshotError):
        _assess(sources)


def test_html_representation_policies_have_distinct_replay_identity():
    (raw, index, archive, submission), member = _sources()
    original = _assess((raw, index, archive, submission))
    changed_submission = replace(
        submission, content=submission.content.replace(b"<TYPE>10-K", b"<TYPE>10-K\n")
    )
    changed = _assess((raw, index, archive, changed_submission))
    assert original.normalized_content == changed.normalized_content == member
    assert original.normalization_policy_id == changed.normalization_policy_id
    assert original.normalization_rule_signature != changed.normalization_rule_signature


@pytest.mark.parametrize(
    ("accession", "policy"),
    (
        (
            "0001564590-20-034944",
            REGISTERED_HTML_BLOCK_POLICY,
        ),
        ("0001564590-21-039151", "sec-edgar-submission-html-crlf-v1"),
        ("0001564590-22-026876", "sec-edgar-submission-html-crlf-v1"),
    ),
)
def test_frozen_microsoft_originals_reconstruct_unchanged_archive(
    accession: str, policy: str
):
    sources, original_states = _retained_sources(accession)
    raw, index, archive, submission = sources
    first = _assess(sources)
    with ZipFile(io.BytesIO(archive.content)) as package:
        assert first.normalized_content == package.read(raw.uri.rsplit("/", 1)[1])
    assert first.normalization_policy_id == policy
    assert (
        first.submission_content_hash == hashlib.sha256(submission.content).hexdigest()
    )
    assert first == _assess(sources)
    for path, modified_at, content in original_states:
        assert path.stat().st_mtime_ns == modified_at
        assert path.read_bytes() == content


def _retained_sources(accession: str) -> tuple[Sources, list[tuple[Path, int, bytes]]]:
    configured = os.getenv("ISSUE494_SEC_EVIDENCE_DIR")
    if configured is None:
        pytest.skip("set ISSUE494_SEC_EVIDENCE_DIR to verify frozen original bytes")
    cohort = json.loads(
        (
            Path(__file__).parent / "fixtures/annual-statements/issue494-cohort.json"
        ).read_bytes()
    )
    filing = next(
        item for item in cohort["filings"] if item["accession_number"] == accession
    )
    sources = []
    original_states = []
    for suffix, source_id in (
        (".htm", "sec-filing"),
        ("index.json", "sec-filing-index"),
        ("-xbrl.zip", "sec-filing-archive"),
        (".txt", "sec-filing-submission"),
    ):
        retained = next(
            item for item in filing["source_records"] if item["uri"].endswith(suffix)
        )
        extension = ".json" if retained["media_type"] == "application/json" else ".bin"
        path = (
            Path(configured)
            / "content"
            / retained["content_hash"][:2]
            / (retained["content_hash"] + extension)
        )
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == retained["content_hash"]
        assert len(content) == retained["received_size"]
        original_states.append((path, path.stat().st_mtime_ns, content))
        sources.append(
            CapturedSource(
                source_id=source_id,
                uri=retained["uri"],
                content=content,
                role=SourceRole.FILING,
                media_type=retained["media_type"],
                http_status=retained["http_status"],
                captured_at=datetime.fromisoformat(retained["captured_at"]),
                available_at=datetime.fromisoformat(filing["accepted_at"]),
                accession_number=accession,
                response_headers=tuple(
                    tuple(pair) for pair in retained["response_headers"]
                ),
            )
        )
    raw, index, archive, submission = sources
    return (raw, index, archive, submission), original_states


def test_registered_html_proof_binds_exact_sources_schema_and_resource_scope():
    (registered,) = REGISTRATIONS
    proof_bytes = (
        Path(__file__).parent
        / "fixtures/sec-integrity/msft-2020-html-block-representation-proof.json"
    ).read_bytes()
    proof = json.loads(proof_bytes)
    assert hashlib.sha256(canonical_bytes(proof)).hexdigest() == registered.proof_digest
    assert proof["issuer_id"] == registered.issuer_id
    assert proof["accession_number"] == registered.accession_number
    assert proof["primary_document"] == registered.primary_document
    assert proof["archive_member_sha256"] == registered.archive_member_hash
    assert proof["archive_sha256"] == registered.archive_hash
    assert proof["archive_index_sha256"] == registered.archive_index_hash
    assert proof["scriptless_primary_sha256"] == registered.scriptless_primary_hash
    assert proof["submission_sha256"] == registered.submission_hash
    assert proof["archive_crlf_count"] == registered.archive_crlf_count
    assert tuple(proof["lf_member_deleted_lf_offsets"]) == registered.deleted_lf_offsets
    assert proof["validation_profile_digest"] == registered.validation_profile_digest
    assert proof["taxonomy_cache_sha256"] == registered.taxonomy_cache_hash
    assert len(registered.deleted_lf_offsets) == 136
    assert len(proof["concept_type_proof"]) == 38
    assert {item["type_qname"] for item in proof["concept_type_proof"]} == {
        "{http://www.xbrl.org/dtr/type/non-numeric}textBlockItemType"
    }
    assert hashlib.sha256(canonical_bytes(proof["concept_type_proof"])).hexdigest() == (
        registered.concept_type_proof_digest
    )
    assert hashlib.sha256(canonical_bytes(proof["context_proof"])).hexdigest() == (
        registered.context_proof_digest
    )


@pytest.mark.parametrize(
    "mutation", (None, "profile", "cache", "missing-cache", "member")
)
def test_registered_html_requires_the_actual_report_resource_identity(
    mutation: str | None,
):
    (registered,) = REGISTRATIONS
    profile = registered.validation_profile_digest
    cache = registered.taxonomy_cache_hash
    member = registered.archive_member_hash
    if mutation == "profile":
        profile = "a" * 64
    elif mutation == "cache":
        cache = "a" * 64
    elif mutation == "missing-cache":
        cache = None
    elif mutation == "member":
        member = "a" * 64
    if mutation is None:
        require_registered_html_resource_scope(
            normalization_policy_id=REGISTERED_HTML_BLOCK_POLICY,
            archive_member_hash=member,
            validation_profile_digest=profile,
            taxonomy_cache_hash=cache,
        )
    else:
        with pytest.raises(SnapshotError) as refused:
            require_registered_html_resource_scope(
                normalization_policy_id=REGISTERED_HTML_BLOCK_POLICY,
                archive_member_hash=member,
                validation_profile_digest=profile,
                taxonomy_cache_hash=cache,
            )
        assert (
            refused.value.code == "SOURCE_HTML_REPRESENTATION_RESOURCE_SCOPE_MISMATCH"
        )


@pytest.mark.parametrize(
    "mutation", ("financial-value", "cross-issuer", "zip", "index")
)
def test_registered_html_refuses_corruption_or_changed_source_identity(mutation: str):
    (raw, index, archive, submission), _ = _retained_sources("0001564590-20-034944")
    if mutation == "financial-value":
        assert b"143,015" in raw.content and b"143,015" in submission.content
        raw = replace(raw, content=raw.content.replace(b"143,015", b"143,016"))
        submission = replace(
            submission, content=submission.content.replace(b"143,015", b"143,016")
        )
    elif mutation == "cross-issuer":
        raw = replace(raw, uri=raw.uri.replace("/789019/", "/320193/"))
        index = replace(index, uri=index.uri.replace("/789019/", "/320193/"))
        archive = replace(archive, uri=archive.uri.replace("/789019/", "/320193/"))
        submission = replace(
            submission, uri=submission.uri.replace("/789019/", "/320193/")
        )
    elif mutation == "zip":
        archive = replace(archive, content=archive.content + b"\n")
        data = json.loads(index.content)
        for item in data["directory"]["item"]:
            if item["name"].endswith("-xbrl.zip"):
                item["size"] = str(len(archive.content))
        index = replace(index, content=json.dumps(data).encode())
    elif mutation == "index":
        index = replace(index, content=index.content + b"\n")
    with pytest.raises(SnapshotError) as refused:
        _assess((raw, index, archive, submission))
    assert refused.value.code == "SOURCE_HTML_REPRESENTATION_PROOF_MISMATCH"
