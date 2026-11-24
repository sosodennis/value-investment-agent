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
)
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


@pytest.mark.parametrize("remove_intertag_lf", (False, True))
def test_submission_proves_html_line_representation_and_preserves_archive(
    remove_intertag_lf: bool,
):
    sources, member = _sources(remove_intertag_lf=remove_intertag_lf)
    result = _assess(sources)

    assert result.normalized_content == result.archive_member == member
    assert result.normalized_content_hash == hashlib.sha256(member).hexdigest()
    assert result.normalization_policy_id == (
        "sec-edgar-submission-html-crlf-intertag-lf-v1"
        if remove_intertag_lf
        else "sec-edgar-submission-html-crlf-v1"
    )
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


def test_intertag_offsets_preserve_multibyte_html_text():
    member = (
        "<html>\r\n<body>\r\n<p>Révenue 123</p>\r\n<p>456</p>\r\n</body>\r\n</html>\r\n"
    ).encode()
    sources, _ = _sources(member=member, remove_intertag_lf=True)
    assert _assess(sources).normalized_content == member


def test_html_representation_policies_have_distinct_replay_identity():
    (raw, index, archive, submission), member = _sources()
    original = _assess((raw, index, archive, submission))
    changed_submission = replace(
        submission, content=submission.content.replace(b"<TYPE>10-K", b"<TYPE>10-K\n")
    )
    changed = _assess((raw, index, archive, changed_submission))
    intertag_sources, intertag_member = _sources(remove_intertag_lf=True)
    intertag = _assess(intertag_sources)

    assert original.normalized_content == changed.normalized_content == member
    assert intertag_member == member == intertag.normalized_content
    assert original.normalization_policy_id == changed.normalization_policy_id
    assert original.normalization_policy_id != intertag.normalization_policy_id
    assert (
        len(
            {
                original.normalization_rule_signature,
                changed.normalization_rule_signature,
                intertag.normalization_rule_signature,
            }
        )
        == 3
    )


@pytest.mark.parametrize(
    ("accession", "policy"),
    (
        (
            "0001564590-20-034944",
            "sec-edgar-submission-html-crlf-intertag-lf-v1",
        ),
        ("0001564590-21-039151", "sec-edgar-submission-html-crlf-v1"),
        ("0001564590-22-026876", "sec-edgar-submission-html-crlf-v1"),
    ),
)
def test_frozen_microsoft_originals_reconstruct_unchanged_archive(
    accession: str, policy: str
):
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
    first = assess_filing_response(
        raw_response=raw,
        archive_index=index,
        archive=archive,
        submission_source=submission,
    )
    with ZipFile(io.BytesIO(archive.content)) as package:
        assert first.normalized_content == package.read(filing["primary_document"])
    assert first.normalization_policy_id == policy
    assert (
        first.submission_content_hash == hashlib.sha256(submission.content).hexdigest()
    )
    assert first == assess_filing_response(
        raw_response=raw,
        archive_index=index,
        archive=archive,
        submission_source=submission,
    )
    for path, modified_at, content in original_states:
        assert path.stat().st_mtime_ns == modified_at
        assert path.read_bytes() == content
