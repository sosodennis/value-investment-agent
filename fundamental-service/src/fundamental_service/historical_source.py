"""Accession-bound original archive selection for historical research parsing."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .contracts import SourceRole
from .sec_archive import read_sec_xbrl_archive
from .serialization import sha256_digest
from .snapshots import SnapshotError

ARCHIVE_POLICY_ID: Literal["sec-original-xbrl-archive-v1"] = (
    "sec-original-xbrl-archive-v1"
)
ARCHIVE_POLICY = {
    "policy_id": ARCHIVE_POLICY_ID,
    "authority": "unchanged root member of the accession-indexed SEC XBRL ZIP",
    "binding": "fixed CIK/accession/original 10-K/acceptance/valuation/primary",
    "direct_response": "retain separately; verify its own indexed size",
    "transformation": "none",
    "difference": "retain; independent semantic and financial checks required",
    "missing_http_receipts": "retain null and discrepancy; do not infer HTTP success",
    "publication": "not approved by selection",
}


class HistoricalSourceReceiptV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    uri: str
    content_hash: str
    byte_length: int
    available_at: datetime
    http_status: int | None


class HistoricalArchiveMemberV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    filename: str
    content_hash: str
    byte_length: int
    direct_index_size: int


class HistoricalArchiveSelectionV1(BaseModel):
    """Source choice evidence, deliberately distinct from release integrity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["historical-archive-selection.v1"] = (
        "historical-archive-selection.v1"
    )
    policy_id: Literal["sec-original-xbrl-archive-v1"] = ARCHIVE_POLICY_ID
    policy_digest: str
    cik: str
    accession: str
    accepted_at: datetime
    valuation_timestamp: datetime
    primary_document: str
    index: HistoricalSourceReceiptV1
    direct: HistoricalSourceReceiptV1
    archive: HistoricalSourceReceiptV1
    members: tuple[HistoricalArchiveMemberV1, ...]
    primary_byte_relation: Literal["equal", "different"]
    discrepancies: tuple[str, ...]
    semantic_equivalence: Literal["not_assessed"] = "not_assessed"
    canonical_publication_approved: Literal[False] = False


@dataclass(frozen=True)
class HistoricalSourceInput:
    """Retained bytes; unavailable capture receipt fields remain unknown."""

    uri: str
    role: SourceRole
    content: bytes
    available_at: datetime
    accession_number: str
    form: str
    http_status: int | None = None
    captured_at: datetime | None = None
    is_amendment: bool = False
    amends_accession: str | None = None
    supersedes_accession: str | None = None
    amendment_scope: str | None = None
    declared_size: int | None = None
    received_size: int | None = None


@dataclass(frozen=True)
class HistoricalArchiveSelection:
    evidence: HistoricalArchiveSelectionV1
    members: tuple[tuple[str, bytes], ...]


def _receipt(source: HistoricalSourceInput) -> HistoricalSourceReceiptV1:
    return HistoricalSourceReceiptV1(
        uri=source.uri,
        content_hash=hashlib.sha256(source.content).hexdigest(),
        byte_length=len(source.content),
        available_at=source.available_at,
        http_status=source.http_status,
    )


def _index_size(entries: list[object], filename: str) -> int:
    matches = [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("name") == filename
    ]
    if len(matches) != 1:
        raise SnapshotError(
            "SOURCE_ARCHIVE_INDEX_MISMATCH",
            "SEC index must uniquely identify every selected source",
        )
    size = matches[0].get("size")
    if not isinstance(size, str) or re.fullmatch(r"[0-9]{1,12}", size) is None:
        raise SnapshotError(
            "SOURCE_ARCHIVE_SIZE_MISSING", "SEC index size is missing or invalid"
        )
    return int(size)


def select_historical_archive(
    *,
    cik: str,
    accession: str,
    accepted_at: datetime,
    valuation_timestamp: datetime,
    primary_document: str,
    archive_index: HistoricalSourceInput,
    direct_response: HistoricalSourceInput,
    archive: HistoricalSourceInput,
    dts_filenames: tuple[str, ...] = (),
) -> HistoricalArchiveSelection:
    """Choose unchanged indexed ZIP bytes without asserting source equivalence.

    The caller supplies the frozen original-filing identity/acceptance evidence.
    This function binds it to retained captures; it does not discover or certify
    that external metadata. Independent parser, applicability, mapping and release
    gates must still run. No filesystem, network or publication side effects.
    """
    if re.fullmatch(r"[0-9]{10}", cik) is None or int(cik) == 0:
        raise SnapshotError("SOURCE_IDENTITY_INVALID", "CIK must be ten digits")
    if re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession) is None:
        raise SnapshotError("SOURCE_IDENTITY_INVALID", "invalid accession number")
    if (
        accepted_at.utcoffset() is None
        or valuation_timestamp.utcoffset() is None
        or accepted_at > valuation_timestamp
    ):
        raise SnapshotError(
            "SOURCE_NOT_AVAILABLE", "filing must be accepted by the replay timestamp"
        )
    required = (primary_document, *dts_filenames)
    if any(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) is None for name in required
    ) or not primary_document.endswith(".xml"):
        raise SnapshotError(
            "SOURCE_PAYLOAD_INVALID", "historical selection requires root XML names"
        )
    base = (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{accession.replace('-', '')}"
    )
    archive_name = f"{accession}-xbrl.zip"
    expected = (
        (archive_index, "index.json", SourceRole.REFERENCE),
        (direct_response, primary_document, SourceRole.FILING),
        (archive, archive_name, SourceRole.FILING),
    )
    for source, filename, role in expected:
        if source.uri != f"{base}/{filename}" or source.accession_number != accession:
            raise SnapshotError(
                "SOURCE_ARCHIVE_ACCESSION_MISMATCH",
                "every source must use the frozen issuer/accession SEC URL",
            )
        if source.http_status not in {None, 200} or source.role != role:
            raise SnapshotError(
                "SOURCE_RECEIPT_INVALID", "known HTTP failure or incorrect source role"
            )
        if (
            source.available_at.utcoffset() is None
            or not accepted_at <= source.available_at <= valuation_timestamp
        ):
            raise SnapshotError(
                "SOURCE_NOT_AVAILABLE", "source availability conflicts with the origin"
            )
        if (
            source.is_amendment
            or source.amends_accession is not None
            or source.supersedes_accession is not None
            or source.amendment_scope is not None
            or (role == SourceRole.FILING and source.form != "10-K")
        ):
            raise SnapshotError(
                "SOURCE_ORIGINAL_REQUIRED",
                "historical selection requires original 10-K",
            )
        if any(
            size is not None and size != len(source.content)
            for size in (source.declared_size, source.received_size)
        ):
            raise SnapshotError(
                "SOURCE_RECEIPT_INVALID", "receipt size differs from retained bytes"
            )
    try:
        entries = json.loads(archive_index.content)["directory"]["item"]
    except (ValueError, KeyError, TypeError) as error:
        raise SnapshotError(
            "SOURCE_ARCHIVE_INDEX_INVALID", "SEC filing index is invalid"
        ) from error
    if not isinstance(entries, list):
        raise SnapshotError(
            "SOURCE_ARCHIVE_INDEX_INVALID", "SEC index items must be a list"
        )
    sizes = {name: _index_size(entries, name) for name in (*required, archive_name)}
    if sizes[primary_document] != len(direct_response.content) or sizes[
        archive_name
    ] != len(archive.content):
        raise SnapshotError(
            "SOURCE_ARCHIVE_SIZE_MISMATCH",
            "direct and ZIP must match their own index sizes",
        )
    members = read_sec_xbrl_archive(
        archive.content,
        primary_document=primary_document,
        dts_filenames=tuple(sorted(dts_filenames)),
    )
    same = members[primary_document] == direct_response.content
    evidence = HistoricalArchiveSelectionV1(
        policy_digest=sha256_digest(ARCHIVE_POLICY),
        cik=cik,
        accession=accession,
        accepted_at=accepted_at,
        valuation_timestamp=valuation_timestamp,
        primary_document=primary_document,
        index=_receipt(archive_index),
        direct=_receipt(direct_response),
        archive=_receipt(archive),
        members=tuple(
            HistoricalArchiveMemberV1(
                filename=name,
                content_hash=hashlib.sha256(content).hexdigest(),
                byte_length=len(content),
                direct_index_size=sizes[name],
            )
            for name, content in sorted(members.items())
        ),
        primary_byte_relation="equal" if same else "different",
        discrepancies=(
            (() if same else ("DIRECT_ARCHIVE_BYTES_DIFFER",))
            + (
                ("CAPTURE_HTTP_RECEIPTS_UNAVAILABLE",)
                if any(source.http_status is None for source, _, _ in expected)
                else ()
            )
        ),
    )
    return HistoricalArchiveSelection(evidence, tuple(sorted(members.items())))
