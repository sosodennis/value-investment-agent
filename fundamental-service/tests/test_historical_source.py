"""Original accession selection preserves conflicts and enforces capture bounds."""

from __future__ import annotations

import io
import json
import stat
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zipfile import ZipFile, ZipInfo

import pytest

from fundamental_service import sec_archive
from fundamental_service.contracts import SourceRole
from fundamental_service.historical_source import (
    HistoricalSourceInput,
    select_historical_archive,
)
from fundamental_service.sec_archive import read_sec_xbrl_archive
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError

CIK = "0000766704"
ACCESSION = "0000766704-14-000006"
ACCEPTED = datetime(2014, 2, 21, 21, 43, tzinfo=UTC)
ORIGIN = datetime(2016, 2, 18, 22, 23, 14, tzinfo=UTC)
BASE = f"https://www.sec.gov/Archives/edgar/data/766704/{ACCESSION.replace('-', '')}"
PRIMARY = "hcn-20131231.xml"
ARCHIVE_NAME = f"{ACCESSION}-xbrl.zip"


def captures(
    direct: bytes = b"<xbrl>100</xbrl>",
    member: bytes = b"<xbrl>\n100</xbrl>",
    resources: tuple[tuple[str, bytes], ...] = (),
) -> dict:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(PRIMARY, member)
        for name, content in resources:
            archive.writestr(name, content)
    zipped = buffer.getvalue()
    index = json.dumps(
        {
            "directory": {
                "item": [
                    {"name": PRIMARY, "size": str(len(direct))},
                    {"name": ARCHIVE_NAME, "size": str(len(zipped))},
                    *(
                        {"name": name, "size": str(len(content))}
                        for name, content in resources
                    ),
                ]
            }
        }
    ).encode()

    def source(name: str, content: bytes, role: SourceRole) -> HistoricalSourceInput:
        return HistoricalSourceInput(
            uri=f"{BASE}/{name}",
            role=role,
            content=content,
            http_status=200,
            available_at=ACCEPTED,
            accession_number=ACCESSION,
            form="10-K" if role == SourceRole.FILING else "SEC-FILING-INDEX",
        )

    return dict(
        cik=CIK,
        accession=ACCESSION,
        accepted_at=ACCEPTED,
        valuation_timestamp=ORIGIN,
        primary_document=PRIMARY,
        archive_index=source("index.json", index, SourceRole.REFERENCE),
        direct_response=source(PRIMARY, direct, SourceRole.FILING),
        archive=source(ARCHIVE_NAME, zipped, SourceRole.FILING),
    )


@pytest.mark.parametrize(
    "member", [b"<xbrl>100</xbrl>", b"<xbrl>\n100</xbrl>", b"<xbrl>999</xbrl>"]
)
def test_choice_preserves_exact_bytes_and_never_certifies_differences(
    member: bytes,
) -> None:
    args = captures(member=member)
    selected = select_historical_archive(**args)
    evidence = selected.evidence
    assert dict(selected.members)[PRIMARY] == member
    assert (
        evidence.direct.content_hash != evidence.members[0].content_hash
        or evidence.primary_byte_relation == "equal"
    )
    assert evidence.semantic_equivalence == "not_assessed"
    assert evidence.canonical_publication_approved is False
    assert bool(evidence.discrepancies) == (args["direct_response"].content != member)
    assert canonical_bytes(evidence) == canonical_bytes(
        select_historical_archive(**args).evidence
    )
    # A recapture clock is provenance, never the selection's identity.
    args["direct_response"] = replace(
        args["direct_response"], captured_at=ORIGIN + timedelta(days=2000)
    )
    assert sha256_digest(select_historical_archive(**args).evidence) == sha256_digest(
        evidence
    )


@pytest.mark.parametrize(
    "key, changes, code",
    [
        (
            "archive",
            {"uri": f"{BASE}/../wrong.zip"},
            "SOURCE_ARCHIVE_ACCESSION_MISMATCH",
        ),
        (
            "direct_response",
            {"uri": f"{BASE.replace('/766704/', '/1/')}/{PRIMARY}"},
            "SOURCE_ARCHIVE_ACCESSION_MISMATCH",
        ),
        (
            "archive_index",
            {"accession_number": "0000766704-14-000007"},
            "SOURCE_ARCHIVE_ACCESSION_MISMATCH",
        ),
        (
            "direct_response",
            {"available_at": ORIGIN + timedelta(seconds=1)},
            "SOURCE_NOT_AVAILABLE",
        ),
        (
            "archive",
            {"available_at": ACCEPTED - timedelta(seconds=1)},
            "SOURCE_NOT_AVAILABLE",
        ),
        ("direct_response", {"http_status": 403}, "SOURCE_RECEIPT_INVALID"),
        ("archive", {"role": SourceRole.REFERENCE}, "SOURCE_RECEIPT_INVALID"),
        ("archive", {"received_size": 1}, "SOURCE_RECEIPT_INVALID"),
        ("archive", {"declared_size": 1}, "SOURCE_RECEIPT_INVALID"),
        ("direct_response", {"form": "10-K/A"}, "SOURCE_ORIGINAL_REQUIRED"),
        ("archive", {"is_amendment": True}, "SOURCE_ORIGINAL_REQUIRED"),
        ("archive", {"supersedes_accession": ACCESSION}, "SOURCE_ORIGINAL_REQUIRED"),
    ],
)
def test_wrong_or_unavailable_capture_is_rejected(
    key: str, changes: dict, code: str
) -> None:
    args = captures()
    args[key] = replace(args[key], **changes)
    with pytest.raises(SnapshotError) as error:
        select_historical_archive(**args)
    assert error.value.code == code


@pytest.mark.parametrize(
    "changes",
    [
        {"cik": "766704"},
        {"cik": "0000000000"},
        {"accession": "wrong"},
        {"accepted_at": ORIGIN + timedelta(seconds=1)},
        {"valuation_timestamp": ORIGIN.replace(tzinfo=None)},
        {"primary_document": "../hcn.xml"},
        {"primary_document": "hcn.xml?x=1"},
        {"dts_filenames": ("../hcn.xsd",)},
    ],
)
def test_invalid_frozen_identity_or_origin_is_rejected(changes: dict) -> None:
    with pytest.raises(SnapshotError):
        select_historical_archive(**(captures() | changes))


@pytest.mark.parametrize(
    "mutation, code",
    [
        ("size", "SOURCE_ARCHIVE_SIZE_MISMATCH"),
        ("duplicate", "SOURCE_ARCHIVE_INDEX_MISMATCH"),
        ("missing", "SOURCE_ARCHIVE_INDEX_MISMATCH"),
        ("negative", "SOURCE_ARCHIVE_SIZE_MISSING"),
        ("malformed", "SOURCE_ARCHIVE_INDEX_INVALID"),
    ],
)
def test_index_is_checked_per_object(mutation: str, code: str) -> None:
    args = captures()
    source = args["archive_index"]
    data = json.loads(source.content)
    entries = data["directory"]["item"]
    if mutation == "size":
        entries[0]["size"] = "1"
    elif mutation == "duplicate":
        entries.append(entries[0])
    elif mutation == "missing":
        entries.pop(1)
    elif mutation == "negative":
        entries[0]["size"] = "-1"
    else:
        data = []
    args["archive_index"] = replace(source, content=json.dumps(data).encode())
    with pytest.raises(SnapshotError) as error:
        select_historical_archive(**args)
    assert error.value.code == code


def test_selected_dts_is_preserved_and_order_does_not_change_identity() -> None:
    resources = (("hcn.xsd", b"<schema/>"), ("hcn_lab.xml", b"<labels/>"))
    args = captures(resources=resources)
    selected = select_historical_archive(
        **args, dts_filenames=("hcn.xsd", "hcn_lab.xml")
    )
    reordered = select_historical_archive(
        **args, dts_filenames=("hcn_lab.xml", "hcn.xsd")
    )
    assert dict(selected.members) | dict(resources) == dict(selected.members)
    assert sha256_digest(selected.evidence) == sha256_digest(reordered.evidence)
    with pytest.raises(SnapshotError):
        select_historical_archive(**args, dts_filenames=("hcn.xsd", "hcn.xsd"))


@pytest.mark.parametrize(
    "kind", ["symlink", "crc", "encrypted", "duplicate", "missing", "budget"]
)
def test_bounded_archive_rejects_unsafe_or_corrupt_members(
    kind: str, monkeypatch
) -> None:
    buffer = io.BytesIO()
    info = ZipInfo(PRIMARY)
    if kind == "symlink":
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with ZipFile(buffer, "w") as archive:
        archive.writestr(info, b"UNIQUE-PAYLOAD")
        if kind == "duplicate":
            with pytest.warns(UserWarning):
                archive.writestr(PRIMARY, b"other")
    payload = buffer.getvalue()
    if kind == "crc":
        payload = payload.replace(b"UNIQUE-PAYLOAD", b"BROKEN-PAYLOAD")
    if kind == "encrypted":
        modified = bytearray(payload)
        modified[6] |= 1
        central = payload.index(b"PK\x01\x02")
        modified[central + 8] |= 1
        payload = bytes(modified)
    if kind == "budget":
        monkeypatch.setattr(
            sec_archive, "_MAX_SEC_XBRL_ARCHIVE_BYTES", len(payload) - 1
        )
    with pytest.raises(SnapshotError):
        read_sec_xbrl_archive(
            payload,
            primary_document=PRIMARY,
            dts_filenames=("missing.xsd",) if kind == "missing" else (),
        )
