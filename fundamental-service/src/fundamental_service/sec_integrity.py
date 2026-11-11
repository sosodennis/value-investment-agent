"""Accession-bound SEC byte integrity and narrowly approved normalization."""

from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import io
import json
import posixpath
import re
import stat
from dataclasses import dataclass
from typing import Literal
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile, ZipInfo

from .contracts import RemovedByteRangeV1
from .serialization import sha256_digest
from .snapshots import CapturedSource, SnapshotError

_EDGE_SCRIPT_AT_END = re.compile(
    rb'(?P<script><script type="text/javascript"\s+'
    rb'src="/[A-Za-z0-9/_-]+"></script>)'
    rb"(?P<closing></body>(?:\n</html>|</html>)\n?)$"
)
_NORMALIZATION_POLICY_ID = "sec-edgar-akamai-trailing-script-v2"
_NORMALIZATION_RULE = (
    "remove one terminal SEC edge script from an accession-matched primary "
    "document only when archive index size, Akamai response metadata, and "
    "the exact archive member independently prove the representation delta"
)
_MAX_STAGED_GRAPHICS_BYTES = 32 * 1024 * 1024
_XML_LINE_END_POLICY_ID = "sec-edgar-xbrl-xml10-line-ends-v1"
_XML_LINE_END_RULE = (
    "reconstruct the original archive XML 1.0 XBRL instance from its direct LF "
    "representation only when replacing archive CRLF pairs with LF reproduces "
    "the exact direct response and its indexed size; insert CR bytes only; "
    "preserve all original bytes and validate the reconstructed archive instance"
)
_XML_FINAL_LF_POLICY_ID = "sec-edgar-xbrl-xml10-terminal-lf-v1"
_XML_FINAL_LF_RULE = (
    "remove exactly one direct-response terminal LF after an XML 1.0 XBRL "
    "closing element only when the SEC index confirms the full direct size "
    "and the remaining bytes equal the accession-matched ZIP member exactly; "
    "preserve both representations and validate the unchanged archive instance"
)
_XML_COMBINED_LF_POLICY_ID = "sec-edgar-xbrl-xml10-line-ends-terminal-lf-v1"
_XML_COMBINED_LF_RULE = (
    "reconstruct the unchanged accession-matched archive XML 1.0 XBRL instance "
    "only when replacing its CRLF pairs with LF and appending exactly one LF "
    "after its closing root reproduces every indexed direct-response byte; "
    "retain both representations, the removed LF offset and inserted CR count"
)


def _is_xml10_xbrl(content: bytes) -> bool:
    if not re.match(rb"<\?xml\s+version\s*=\s*(['\"])1\.0\1(?:\s|\?>)", content):
        return False
    if b"<!DOCTYPE" in content:
        return False
    try:
        root = next(ElementTree.iterparse(io.BytesIO(content), events=("start",)))[1]
    except (ElementTree.ParseError, StopIteration):
        return False
    return root.tag == "{http://www.xbrl.org/2003/instance}xbrl"


class _ImageSourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._capture(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._capture(tag, attrs)

    def _capture(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return
        source = next((value for name, value in attrs if name.lower() == "src"), None)
        if source:
            self.sources.append(source)


def extract_referenced_graphics(
    *,
    html_content: bytes,
    archive_content: bytes,
    primary_document: str,
    max_total_bytes: int = _MAX_STAGED_GRAPHICS_BYTES,
) -> tuple[tuple[str, bytes], ...]:
    """Read local image references from the accession-matched SEC archive.

    External and unresolved references are left for Arelle's EFM validation to
    reject. Archive paths are never written directly from untrusted HTML.
    """
    parser = _ImageSourceParser()
    parser.feed(html_content.decode("utf-8", errors="replace"))
    parser.close()

    requested_paths: set[str] = set()
    for source in parser.sources:
        parsed = urlsplit(source)
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.path.startswith("/")
            or "\\" in parsed.path
        ):
            continue
        decoded_path = unquote(parsed.path)
        if (
            not decoded_path
            or decoded_path.startswith("/")
            or "\x00" in decoded_path
            or "\\" in decoded_path
        ):
            continue
        archive_path = posixpath.normpath(
            posixpath.join(posixpath.dirname(primary_document), decoded_path)
        )
        if archive_path in {"", ".", ".."} or archive_path.startswith("../"):
            continue
        requested_paths.add(archive_path)

    if not requested_paths:
        return ()

    try:
        with ZipFile(io.BytesIO(archive_content)) as package:
            info_by_name: dict[str, list[ZipInfo]] = {}
            for info in package.infolist():
                if info.filename in requested_paths:
                    info_by_name.setdefault(info.filename, []).append(info)
            resources: list[tuple[str, bytes]] = []
            total_bytes = 0
            for archive_path in sorted(requested_paths):
                matches = info_by_name.get(archive_path, [])
                if not matches:
                    continue
                if len(matches) != 1:
                    raise SnapshotError(
                        "SOURCE_ARCHIVE_RESOURCE_AMBIGUOUS",
                        "SEC archive contains duplicate referenced image paths",
                    )
                info = matches[0]
                file_type = stat.S_IFMT(info.external_attr >> 16)
                if info.is_dir() or file_type not in {0, stat.S_IFREG}:
                    raise SnapshotError(
                        "SOURCE_ARCHIVE_RESOURCE_INVALID",
                        "SEC archive referenced image is not a regular file",
                    )
                total_bytes += info.file_size
                if total_bytes > max_total_bytes:
                    raise SnapshotError(
                        "SOURCE_ARCHIVE_RESOURCE_LIMIT",
                        "referenced SEC images exceed the offline staging limit",
                    )
                resources.append((archive_path, package.read(info)))
            return tuple(resources)
    except (BadZipFile, OSError) as error:
        raise SnapshotError(
            "SOURCE_ARCHIVE_INVALID", "SEC XBRL archive is invalid"
        ) from error


@dataclass(frozen=True)
class SecIntegrityAssessment:
    relation: Literal["exact", "normalized"]
    normalized_content: bytes
    declared_primary_size: int
    archive_member_name: str
    archive_member: bytes
    raw_content_hash: str
    archive_index_hash: str
    archive_hash: str
    archive_member_hash: str
    normalized_content_hash: str
    removed_ranges: tuple[RemovedByteRangeV1, ...]
    normalization_policy_id: str | None
    normalization_rule_signature: str | None
    normalization_reason: str | None


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def assess_filing_response(
    *,
    raw_response: CapturedSource,
    archive_index: CapturedSource,
    archive: CapturedSource,
) -> SecIntegrityAssessment:
    """Match raw response, SEC archive index, and XBRL ZIP member.

    Versioned rules cover a terminal Akamai script/final LF and the exact
    XML 1.0 CRLF/LF, terminal LF and their exact combined representation
    differences. They reconstruct the original accession-matched archive bytes.
    Every other mismatch blocks.
    """
    try:
        index_data = json.loads(archive_index.content)
        entries = index_data["directory"]["item"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise SnapshotError(
            "SOURCE_ARCHIVE_INDEX_INVALID", "SEC filing index is invalid"
        ) from error
    if not isinstance(entries, list):
        raise SnapshotError(
            "SOURCE_ARCHIVE_INDEX_INVALID", "SEC filing index has no item list"
        )
    expected_accession = raw_response.accession_number
    if (
        not expected_accession
        or archive_index.accession_number != expected_accession
        or archive.accession_number != expected_accession
        or archive_index.uri.rsplit("/", 1)[0] != archive.uri.rsplit("/", 1)[0]
    ):
        raise SnapshotError(
            "SOURCE_ARCHIVE_ACCESSION_MISMATCH",
            "SEC index and archive must belong to the same filing accession",
        )
    primary_name = raw_response.uri.rsplit("/", 1)[-1]
    matches = [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("name") == primary_name
    ]
    if len(matches) != 1:
        raise SnapshotError(
            "SOURCE_ARCHIVE_INDEX_MISMATCH",
            "SEC index does not uniquely identify the primary document",
        )
    entry = matches[0]
    declared = entry.get("size")
    if not isinstance(declared, str) or not declared.isdecimal():
        raise SnapshotError(
            "SOURCE_ARCHIVE_SIZE_MISSING",
            "SEC index does not declare the primary document size",
        )
    declared_size = int(declared)
    archive_name = f"{expected_accession}-xbrl.zip"
    archive_entries = [
        item
        for item in entries
        if isinstance(item, dict) and item.get("name") == archive_name
    ]
    if len(archive_entries) != 1 or archive_entries[0].get("size") != str(
        len(archive.content)
    ):
        raise SnapshotError(
            "SOURCE_ARCHIVE_SIZE_MISMATCH",
            "SEC index archive entry does not match received ZIP bytes",
        )
    try:
        with ZipFile(io.BytesIO(archive.content)) as package:
            member_names = [
                name
                for name in package.namelist()
                if name.rsplit("/", 1)[-1] == primary_name
            ]
            if len(member_names) != 1:
                raise SnapshotError(
                    "SOURCE_ARCHIVE_MEMBER_MISMATCH",
                    "accession XBRL ZIP does not uniquely contain the primary document",
                )
            member_name = member_names[0]
            member = package.read(member_name)
    except (BadZipFile, OSError) as error:
        raise SnapshotError(
            "SOURCE_ARCHIVE_INVALID", "SEC XBRL archive is invalid"
        ) from error

    raw = raw_response.content
    raw_hash = _digest(raw)
    archive_hash = _digest(archive.content)
    member_hash = _digest(member)
    index_hash = _digest(archive_index.content)
    if (
        primary_name.endswith(".xml")
        and len(raw) == declared_size
        and raw == member + b"\n"
        and re.search(rb"</(?:[A-Za-z_][A-Za-z0-9_.-]*:)?xbrl>$", member)
        and _is_xml10_xbrl(member)
    ):
        return SecIntegrityAssessment(
            relation="normalized",
            normalized_content=member,
            declared_primary_size=declared_size,
            archive_member_name=member_name,
            archive_member=member,
            raw_content_hash=raw_hash,
            archive_index_hash=index_hash,
            archive_hash=archive_hash,
            archive_member_hash=member_hash,
            normalized_content_hash=member_hash,
            removed_ranges=(
                RemovedByteRangeV1(
                    start=len(member), end=len(raw), content_hash=_digest(b"\n")
                ),
            ),
            normalization_policy_id=_XML_FINAL_LF_POLICY_ID,
            normalization_rule_signature=sha256_digest(
                {
                    "policy_id": _XML_FINAL_LF_POLICY_ID,
                    "rule": _XML_FINAL_LF_RULE,
                    "accession": expected_accession,
                    "primary_document": primary_name,
                    "declared_size": declared_size,
                    "raw_content_hash": raw_hash,
                    "archive_index_hash": index_hash,
                    "archive_hash": archive_hash,
                    "archive_member_hash": member_hash,
                    "removed_lf_offset": len(member),
                }
            ),
            normalization_reason=_XML_FINAL_LF_RULE,
        )
    line_ended_member = member.replace(b"\r\n", b"\n")
    combined_lf = (
        raw == line_ended_member + b"\n"
        and re.search(rb"</(?:[A-Za-z_][A-Za-z0-9_.-]*:)?xbrl>$", member) is not None
    )
    if (
        primary_name.endswith(".xml")
        and len(raw) == declared_size
        and b"\r\n" in member
        and b"\r" not in raw
        and (raw == line_ended_member or combined_lf)
        and _is_xml10_xbrl(raw)
    ):
        policy_id = (
            _XML_COMBINED_LF_POLICY_ID if combined_lf else _XML_LINE_END_POLICY_ID
        )
        rule = _XML_COMBINED_LF_RULE if combined_lf else _XML_LINE_END_RULE
        return SecIntegrityAssessment(
            relation="normalized",
            normalized_content=member,
            declared_primary_size=declared_size,
            archive_member_name=member_name,
            archive_member=member,
            raw_content_hash=raw_hash,
            archive_index_hash=index_hash,
            archive_hash=archive_hash,
            archive_member_hash=member_hash,
            normalized_content_hash=member_hash,
            removed_ranges=(
                (
                    RemovedByteRangeV1(
                        start=len(raw) - 1,
                        end=len(raw),
                        content_hash=_digest(b"\n"),
                    ),
                )
                if combined_lf
                else ()
            ),
            normalization_policy_id=policy_id,
            normalization_rule_signature=sha256_digest(
                {
                    "policy_id": policy_id,
                    "rule": rule,
                    "accession": expected_accession,
                    "primary_document": primary_name,
                    "declared_size": declared_size,
                    "raw_content_hash": raw_hash,
                    "archive_index_hash": index_hash,
                    "archive_hash": archive_hash,
                    "archive_member_hash": member_hash,
                    "inserted_cr_count": member.count(b"\r\n"),
                    **({"removed_lf_offset": len(raw) - 1} if combined_lf else {}),
                }
            ),
            normalization_reason=rule,
        )
    if len(member) > declared_size or declared_size - len(member) > 1:
        raise SnapshotError(
            "SOURCE_ARCHIVE_SIZE_MISMATCH",
            "SEC index size and archive member size are inconsistent",
        )
    if raw == member:
        if len(raw) != declared_size:
            raise SnapshotError(
                "SOURCE_INTEGRITY_MISMATCH",
                "exact direct response does not match SEC index size",
            )
        return SecIntegrityAssessment(
            relation="exact",
            normalized_content=raw,
            declared_primary_size=declared_size,
            archive_member_name=member_name,
            archive_member=member,
            raw_content_hash=raw_hash,
            archive_index_hash=index_hash,
            archive_hash=archive_hash,
            archive_member_hash=member_hash,
            normalized_content_hash=raw_hash,
            removed_ranges=(),
            normalization_policy_id=None,
            normalization_rule_signature=None,
            normalization_reason=None,
        )

    headers = dict(raw_response.response_headers)
    if headers.get("x-akamai-transformed") != "0 - 0 -":
        raise SnapshotError(
            "SOURCE_INTEGRITY_MISMATCH",
            "SEC direct response differs without the expected Akamai metadata",
        )
    match = _EDGE_SCRIPT_AT_END.search(raw)
    if match is None or _EDGE_SCRIPT_AT_END.search(raw, match.start() + 1) is not None:
        raise SnapshotError(
            "SOURCE_INTEGRITY_MISMATCH",
            "SEC direct response does not match the approved terminal script shape",
        )
    script = match.group("script")
    script_start, script_end = match.span("script")
    without_script = raw[:script_start] + raw[script_end:]
    if len(without_script) != declared_size or not without_script.endswith(
        (b"</body></html>\n", b"</body>\n</html>\n")
    ):
        raise SnapshotError(
            "SOURCE_INTEGRITY_MISMATCH",
            "SEC index size does not corroborate the exact script removal",
        )
    final_lf_start = len(raw) - 1
    normalized = without_script[:-1]
    removed_ranges = (
        RemovedByteRangeV1(
            start=script_start,
            end=script_end,
            content_hash=_digest(script),
        ),
        RemovedByteRangeV1(
            start=final_lf_start,
            end=final_lf_start + 1,
            content_hash=_digest(b"\n"),
        ),
    )
    if normalized != member:
        raise SnapshotError(
            "SOURCE_INTEGRITY_MISMATCH",
            "approved SEC response normalization does not reproduce archive bytes",
        )
    rule_payload = {
        "policy_id": _NORMALIZATION_POLICY_ID,
        "rule": _NORMALIZATION_RULE,
        "script_shape": _EDGE_SCRIPT_AT_END.pattern.decode("ascii"),
        "accession": raw_response.accession_number,
        "primary_document": primary_name,
        "required_header": ("x-akamai-transformed", "0 - 0 -"),
        "declared_size": declared_size,
        "archive_member_hash": member_hash,
    }
    return SecIntegrityAssessment(
        relation="normalized",
        normalized_content=normalized,
        declared_primary_size=declared_size,
        archive_member_name=member_name,
        archive_member=member,
        raw_content_hash=raw_hash,
        archive_index_hash=index_hash,
        archive_hash=archive_hash,
        archive_member_hash=member_hash,
        normalized_content_hash=_digest(normalized),
        removed_ranges=removed_ranges,
        normalization_policy_id=_NORMALIZATION_POLICY_ID,
        normalization_rule_signature=sha256_digest(rule_payload),
        normalization_reason=_NORMALIZATION_RULE,
    )
