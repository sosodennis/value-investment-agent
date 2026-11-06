import hashlib
import io
import json
from dataclasses import replace
from datetime import datetime, timezone
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fundamental_service.contracts import SourceRole
from fundamental_service.sec_integrity import (
    assess_filing_response,
    extract_referenced_graphics,
)
from fundamental_service.snapshots import CapturedSource, SnapshotError

ACCESSION = "0000320193-24-000123"
BASE_URI = (
    f"https://www.sec.gov/Archives/edgar/data/320193/{ACCESSION.replace('-', '')}"
)
PRIMARY_NAME = "aapl-20240928.htm"
ARCHIVE_NAME = f"{ACCESSION}-xbrl.zip"
CAPTURED_AT = datetime(2026, 11, 6, tzinfo=timezone.utc)


def _archive(member: bytes) -> bytes:
    payload = io.BytesIO()
    with ZipFile(payload, "w", compression=ZIP_DEFLATED) as package:
        package.writestr(PRIMARY_NAME, member)
    return payload.getvalue()


def _source(
    *, source_id: str, uri: str, role: SourceRole, content: bytes, **kwargs: object
) -> CapturedSource:
    return CapturedSource(
        source_id=source_id,
        uri=uri,
        role=role,
        content=content,
        media_type="application/json"
        if source_id == "sec-filing-index"
        else "text/html",
        http_status=200,
        available_at=CAPTURED_AT,
        captured_at=CAPTURED_AT,
        **kwargs,
    )


def _fixtures(
    *, direct: bytes, member: bytes, headers: tuple[tuple[str, str], ...] = ()
):
    archive = _archive(member)
    index = json.dumps(
        {
            "directory": {
                "item": [
                    {
                        "name": PRIMARY_NAME,
                        "size": str(len(member) + (1 if direct != member else 0)),
                    },
                    {"name": ARCHIVE_NAME, "size": str(len(archive))},
                ]
            }
        }
    ).encode()
    raw = _source(
        source_id="sec-filing",
        uri=f"{BASE_URI}/{PRIMARY_NAME}",
        role=SourceRole.FILING,
        content=direct,
        accession_number=ACCESSION,
        form="10-K",
        filed_at=datetime(2024, 11, 1, tzinfo=timezone.utc),
        response_headers=headers,
    )
    index_source = _source(
        source_id="sec-filing-index",
        uri=f"{BASE_URI}/index.json",
        role=SourceRole.REFERENCE,
        content=index,
        accession_number=ACCESSION,
    )
    archive_source = _source(
        source_id="sec-filing-archive",
        uri=f"{BASE_URI}/{ARCHIVE_NAME}",
        role=SourceRole.FILING,
        content=archive,
        accession_number=ACCESSION,
        form="10-K",
        filed_at=datetime(2024, 11, 1, tzinfo=timezone.utc),
    )
    return raw, index_source, archive_source


def test_terminal_edge_script_normalizes_only_with_archive_proof():
    member = b"<html><body>canonical</body></html>"
    script = b'<script type="text/javascript" src="/edge/path/token"></script>'
    direct = member[: -len(b"</body></html>")] + script + b"</body></html>\n"
    raw, index, archive = _fixtures(
        direct=direct,
        member=member,
        headers=(("x-akamai-transformed", "0 - 0 -"),),
    )

    result = assess_filing_response(
        raw_response=raw, archive_index=index, archive=archive
    )

    assert result.relation == "normalized"
    assert result.normalized_content == member
    assert result.raw_content_hash == hashlib.sha256(direct).hexdigest()
    assert result.normalized_content_hash == hashlib.sha256(member).hexdigest()
    assert len(result.removed_ranges) == 2
    assert result.normalization_policy_id == "sec-edgar-akamai-trailing-script-v2"


def test_terminal_edge_script_preserves_canonical_body_closing_newline():
    member = b"<html><body>canonical</body>\n</html>"
    script = b'<script type="text/javascript" src="/edge/path/token"></script>'
    direct = member[: -len(b"</body>\n</html>")] + script + b"</body>\n</html>\n"
    raw, index, archive = _fixtures(
        direct=direct,
        member=member,
        headers=(("x-akamai-transformed", "0 - 0 -"),),
    )

    result = assess_filing_response(
        raw_response=raw, archive_index=index, archive=archive
    )

    assert result.relation == "normalized"
    assert result.normalized_content == member
    assert len(result.removed_ranges) == 2
    assert tuple(
        raw.content[item.start : item.end] for item in result.removed_ranges
    ) == (script, b"\n")
    assert all(
        hashlib.sha256(raw.content[item.start : item.end]).hexdigest()
        == item.content_hash
        for item in result.removed_ranges
    )


def test_exact_archive_member_requires_exact_declared_size():
    member = b"<html><body>canonical</body></html>"
    raw, index, archive = _fixtures(direct=member, member=member)

    result = assess_filing_response(
        raw_response=raw, archive_index=index, archive=archive
    )

    assert result.relation == "exact"
    assert result.removed_ranges == ()
    assert result.normalized_content == member


@pytest.mark.parametrize(
    "headers, direct, expected_code",
    [
        (
            (),
            b"<html><body>canonical<script>unexpected</script></body></html>\n",
            "SOURCE_INTEGRITY_MISMATCH",
        ),
        (
            (("x-akamai-transformed", "0 - 0 -"),),
            b"<html><body>different</body></html>\n",
            "SOURCE_INTEGRITY_MISMATCH",
        ),
    ],
)
def test_unexplained_direct_representation_difference_is_blocked(
    headers: tuple[tuple[str, str], ...], direct: bytes, expected_code: str
):
    member = b"<html><body>canonical</body></html>"
    raw, index, archive = _fixtures(direct=direct, member=member, headers=headers)

    with pytest.raises(SnapshotError) as error:
        assess_filing_response(raw_response=raw, archive_index=index, archive=archive)

    assert error.value.code == expected_code


def test_accession_mismatch_is_blocked_before_normalization():
    member = b"<html><body>canonical</body></html>"
    raw, index, archive = _fixtures(direct=member, member=member)
    mismatched_archive = replace(archive, accession_number="0000320193-24-000124")

    with pytest.raises(SnapshotError) as error:
        assess_filing_response(
            raw_response=raw, archive_index=index, archive=mismatched_archive
        )

    assert error.value.code == "SOURCE_ARCHIVE_ACCESSION_MISMATCH"


def test_referenced_graphics_are_read_from_the_accession_archive():
    image = b"\xff\xd8\xffjpeg"
    archive_payload = io.BytesIO()
    with ZipFile(archive_payload, "w", compression=ZIP_DEFLATED) as package:
        package.writestr(PRIMARY_NAME, b"<html><body></body></html>")
        package.writestr("aapl-20240928_g1.jpg", image)
    html = (
        b'<html><img src="aapl-20240928_g1.jpg">'
        b'<img src="https://example.test/tracker.png">'
        b"</html>"
    )

    resources = extract_referenced_graphics(
        html_content=html,
        archive_content=archive_payload.getvalue(),
        primary_document=PRIMARY_NAME,
    )

    assert resources == (("aapl-20240928_g1.jpg", image),)


@pytest.mark.parametrize(
    "source",
    (
        b"../outside.jpg",
        b"%2e%2e/outside.jpg",
        b"..\\outside.jpg",
        b"%2Foutside.jpg",
    ),
)
def test_referenced_graphics_never_extract_paths_outside_the_filing_root(
    source: bytes,
):
    archive_payload = _archive(b"<html></html>")

    resources = extract_referenced_graphics(
        html_content=b'<html><img src="' + source + b'"></html>',
        archive_content=archive_payload,
        primary_document=PRIMARY_NAME,
    )

    assert resources == ()


def test_percent_encoded_backslash_path_is_not_extracted():
    archive_payload = io.BytesIO()
    with ZipFile(archive_payload, "w", compression=ZIP_DEFLATED) as package:
        package.writestr("..\\outside.jpg", b"unsafe")

    resources = extract_referenced_graphics(
        html_content=b'<html><img src="%2e%2e%5coutside.jpg"></html>',
        archive_content=archive_payload.getvalue(),
        primary_document=PRIMARY_NAME,
    )

    assert resources == ()


def test_percent_encoded_absolute_path_is_not_extracted():
    archive_payload = io.BytesIO()
    with ZipFile(archive_payload, "w", compression=ZIP_DEFLATED) as package:
        package.writestr("/outside.jpg", b"unsafe")

    resources = extract_referenced_graphics(
        html_content=b'<html><img src="%2Foutside.jpg"></html>',
        archive_content=archive_payload.getvalue(),
        primary_document=PRIMARY_NAME,
    )

    assert resources == ()
