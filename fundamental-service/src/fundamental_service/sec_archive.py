"""Bounded in-memory SEC archive reads shared by acquisition and replay."""

from __future__ import annotations

import stat
import zlib
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from .snapshots import SnapshotError

_MAX_SEC_XBRL_ARCHIVE_BYTES = 24_000_000
_MAX_SEC_XBRL_ARCHIVE_MEMBERS = 4096
_MAX_SEC_XBRL_ARCHIVE_UNCOMPRESSED_BYTES = 256_000_000
_MAX_SEC_XBRL_PRIMARY_BYTES = 24_000_000
_MAX_SEC_XBRL_RESOURCE_BYTES = 12_000_000
_MAX_SEC_XBRL_SELECTED_BYTES = 48_000_000


def read_sec_xbrl_archive(
    content: bytes, *, primary_document: str, dts_filenames: tuple[str, ...]
) -> dict[str, bytes]:
    """Read only bounded, index-selected root members without extracting paths."""
    if len(content) > _MAX_SEC_XBRL_ARCHIVE_BYTES:
        raise SnapshotError(
            "INGESTION_BUDGET_EXCEEDED", "SEC XBRL archive exceeds the byte limit"
        )
    required = (primary_document, *dts_filenames)
    if len(set(required)) != len(required):
        raise SnapshotError(
            "SOURCE_PAYLOAD_INVALID", "SEC XBRL member selection contains duplicates"
        )
    if any(
        not name or "/" in name or "\\" in name or "\x00" in name or name in {".", ".."}
        for name in required
    ):
        raise SnapshotError(
            "SOURCE_PAYLOAD_INVALID", "SEC XBRL member path is not a root filename"
        )
    try:
        with ZipFile(BytesIO(content)) as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_SEC_XBRL_ARCHIVE_MEMBERS:
                raise SnapshotError(
                    "INGESTION_BUDGET_EXCEEDED",
                    "SEC XBRL archive contains too many members",
                )
            all_names: set[str] = set()
            selected_infos = {}
            uncompressed_size = 0
            for info in infos:
                if info.filename in all_names:
                    raise SnapshotError(
                        "SOURCE_PAYLOAD_INVALID",
                        "SEC XBRL archive repeats a member name",
                    )
                all_names.add(info.filename)
                uncompressed_size += info.file_size
                if uncompressed_size > _MAX_SEC_XBRL_ARCHIVE_UNCOMPRESSED_BYTES:
                    raise SnapshotError(
                        "INGESTION_BUDGET_EXCEEDED",
                        "SEC XBRL archive exceeds the uncompressed byte limit",
                    )
                if info.filename in required:
                    file_type = stat.S_IFMT(info.external_attr >> 16)
                    if (
                        info.is_dir()
                        or info.orig_filename != info.filename
                        or file_type not in {0, stat.S_IFREG}
                    ):
                        raise SnapshotError(
                            "SOURCE_PAYLOAD_INVALID",
                            "SEC XBRL selected member is not a regular root file",
                        )
                    if info.flag_bits & 0x1:
                        raise SnapshotError(
                            "SOURCE_PAYLOAD_INVALID",
                            "SEC XBRL archive contains an encrypted member",
                        )
                    selected_infos[info.filename] = info
            missing = sorted(set(required) - selected_infos.keys())
            if missing:
                raise SnapshotError(
                    "SOURCE_PAYLOAD_INVALID",
                    "SEC XBRL archive is missing an index-selected member",
                )
            selected_size = 0
            members: dict[str, bytes] = {}
            for filename in required:
                info = selected_infos[filename]
                file_limit = (
                    _MAX_SEC_XBRL_PRIMARY_BYTES
                    if filename == primary_document
                    else _MAX_SEC_XBRL_RESOURCE_BYTES
                )
                if info.file_size > file_limit:
                    raise SnapshotError(
                        "INGESTION_BUDGET_EXCEEDED",
                        "SEC XBRL member exceeds the supported size",
                    )
                selected_size += info.file_size
                if selected_size > _MAX_SEC_XBRL_SELECTED_BYTES:
                    raise SnapshotError(
                        "INGESTION_BUDGET_EXCEEDED",
                        "SEC XBRL selected members exceed the byte limit",
                    )
                member = archive.read(info)
                if len(member) != info.file_size:
                    raise SnapshotError(
                        "SOURCE_PAYLOAD_INVALID",
                        "SEC XBRL member size does not match its directory entry",
                    )
                members[filename] = member
            return members
    except SnapshotError:
        raise
    except (
        BadZipFile,
        EOFError,
        NotImplementedError,
        OSError,
        RuntimeError,
        zlib.error,
    ) as error:
        raise SnapshotError(
            "SOURCE_PAYLOAD_INVALID", "SEC XBRL archive could not be verified"
        ) from error
