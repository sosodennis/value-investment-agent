"""Retained taxonomy bytes reproduce the parser's ordered directory digest."""

from __future__ import annotations

import hashlib
import io
import stat
import sys
import zlib
from collections import OrderedDict
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile, ZipInfo

from .data_releases import ArtifactRefV1, DataReleaseError

TAXONOMY_CACHE_ARCHIVE_ROLE = "sec-taxonomy-cache-archive-v1"
_MAX_ENTRIES = 10_000
_MAX_UNCOMPRESSED_BYTES = 1_024 * 1_024 * 1_024


class TaxonomyArchiveChecks:
    """One operation's bounded results of complete archive validation."""

    def __init__(
        self, *, max_entries: int = 64, max_retained_bytes: int = 64 * 1024
    ) -> None:
        if min(max_entries, max_retained_bytes) < 0:
            raise ValueError("taxonomy retention limits must be nonnegative")
        self._max_entries = max_entries
        self._max_retained_bytes = max_retained_bytes
        self._digests: OrderedDict[str, str] = OrderedDict()
        self._size = 0

    def digest(self, raw: bytes) -> str:
        content_digest = hashlib.sha256(raw).hexdigest()
        retained = self._digests.get(content_digest)
        if retained is not None:
            self._digests.move_to_end(content_digest)
            return retained
        result = taxonomy_cache_archive_digest(raw)
        self._digests[content_digest] = result
        self._size += sys.getsizeof(content_digest) + sys.getsizeof(result)
        while self._digests and (
            len(self._digests) > self._max_entries
            or self._size + sys.getsizeof(self._digests) > self._max_retained_bytes
        ):
            key, value = self._digests.popitem(last=False)
            self._size -= sys.getsizeof(key) + sys.getsizeof(value)
        return result


def _member_name_is_safe(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(
        name
        and "\\" not in name
        and "\0" not in name
        and not path.is_absolute()
        and name == path.as_posix()
        and all(part not in {".", ".."} for part in path.parts)
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
        and not name.endswith("/")
    )


def build_taxonomy_cache_archive(root: Path) -> bytes:
    """Package exact parser cache members in stable order with fixed ZIP metadata."""
    paths = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.relative_to(root).parts
        and path.suffix not in {".pyc", ".pyo"}
    )
    if not paths or len(paths) > _MAX_ENTRIES:
        raise ValueError("taxonomy cache must have a bounded nonempty member set")
    if sum(path.stat().st_size for path in paths) > _MAX_UNCOMPRESSED_BYTES:
        raise ValueError("taxonomy cache exceeds archive size limit")
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in paths:
            name = path.relative_to(root).as_posix()
            if not _member_name_is_safe(name):
                raise ValueError("taxonomy cache contains an unsafe member name")
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)
    return output.getvalue()


def taxonomy_cache_archive_digest(raw: bytes) -> str:
    """Hash path + NUL + bytes exactly as Arelle, without extracting or fetching."""
    try:
        with ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            names = tuple(item.filename for item in entries)
            if (
                not entries
                or len(entries) > _MAX_ENTRIES
                or names != tuple(sorted(set(names), key=PurePosixPath))
                or sum(item.file_size for item in entries) > _MAX_UNCOMPRESSED_BYTES
                or any(
                    not _member_name_is_safe(item.filename)
                    or item.flag_bits & 1
                    or stat.S_ISLNK(item.external_attr >> 16)
                    for item in entries
                )
            ):
                raise ValueError("taxonomy cache archive members are invalid")
            digest = hashlib.sha256()
            for item in entries:
                digest.update(item.filename.encode("utf-8"))
                digest.update(b"\0")
                with archive.open(item) as handle:
                    consumed = 0
                    while chunk := handle.read(1024 * 1024):
                        consumed += len(chunk)
                        if consumed > item.file_size:
                            raise ValueError("taxonomy cache member size mismatch")
                        digest.update(chunk)
                if consumed != item.file_size:
                    raise ValueError("taxonomy cache member size mismatch")
            return digest.hexdigest()
    except (
        BadZipFile,
        ValueError,
        RuntimeError,
        NotImplementedError,
        EOFError,
        zlib.error,
    ) as error:
        raise DataReleaseError(
            "DATA_RELEASE_TAXONOMY_ARCHIVE_INVALID",
            "retained taxonomy cache archive failed validation",
        ) from error


def require_original_taxonomy(
    expected_digest: str,
    references: tuple[ArtifactRefV1, ...],
    contents: dict[str, bytes],
    *,
    archive_checks: TaxonomyArchiveChecks | None = None,
) -> None:
    """Accept the exact original manifest or replay its pinned cache archive."""
    for reference in references:
        raw = contents.get(reference.content_hash)
        if raw is None or hashlib.sha256(raw).hexdigest() != reference.content_hash:
            continue
        if reference.content_hash == expected_digest:
            return
        if (
            reference.role == TAXONOMY_CACHE_ARCHIVE_ROLE
            and (
                archive_checks.digest(raw)
                if archive_checks is not None
                else taxonomy_cache_archive_digest(raw)
            )
            == expected_digest
        ):
            return
    raise DataReleaseError(
        "DATA_RELEASE_TAXONOMY_MANIFEST_UNAVAILABLE",
        "retain the original taxonomy manifest or a cache archive reproducing its tree digest",
    )
