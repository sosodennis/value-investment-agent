"""Verify and restore the immutable research archive outside the Git tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import IO

CHUNK_SIZE = 1024 * 1024


class ArchiveVerificationError(ValueError):
    pass


def _digest_stream(stream: IO[bytes]) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while block := stream.read(CHUNK_SIZE):
        digest.update(block)
        size += len(block)
    return digest.hexdigest(), size


def _safe_member_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ArchiveVerificationError("manifest contains an invalid member path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise ArchiveVerificationError(f"unsafe archive member path: {value!r}")
    return path.as_posix()


def _manifest_entries(manifest: dict[str, object]) -> dict[str, tuple[int, str]]:
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ArchiveVerificationError("manifest files must be an array")
    entries: dict[str, tuple[int, str]] = {}
    for item in files:
        if not isinstance(item, dict):
            raise ArchiveVerificationError("manifest file entry must be an object")
        path = _safe_member_path(item.get("path"))
        size, digest = item.get("byte_length"), item.get("sha256")
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ArchiveVerificationError(f"invalid size or digest for {path}")
        if path in entries:
            raise ArchiveVerificationError(f"duplicate manifest path: {path}")
        entries[path] = (size, digest)
    return entries


def _verify_archive_contents(
    archive: Path, entries: dict[str, tuple[int, str]]
) -> None:
    seen: set[str] = set()
    try:
        with tarfile.open(archive, mode="r:gz") as bundle:
            for member in bundle:
                if member.isdir():
                    continue
                path = _safe_member_path(member.name)
                if not member.isfile() or member.issym() or member.islnk():
                    raise ArchiveVerificationError(
                        f"archive contains a non-regular file: {path}"
                    )
                if path not in entries:
                    raise ArchiveVerificationError(f"unlisted archive member: {path}")
                if path in seen:
                    raise ArchiveVerificationError(f"duplicate archive member: {path}")
                expected_size, expected_digest = entries[path]
                if member.size != expected_size:
                    raise ArchiveVerificationError(f"size mismatch: {path}")
                source = bundle.extractfile(member)
                if source is None:
                    raise ArchiveVerificationError(
                        f"cannot read archive member: {path}"
                    )
                with source:
                    actual_digest, actual_size = _digest_stream(source)
                if (actual_size, actual_digest) != (expected_size, expected_digest):
                    raise ArchiveVerificationError(f"content digest mismatch: {path}")
                seen.add(path)
    except (OSError, tarfile.TarError) as error:
        raise ArchiveVerificationError("archive cannot be read") from error
    if seen != set(entries):
        missing = sorted(set(entries) - seen)
        raise ArchiveVerificationError(
            f"archive is missing {len(missing)} manifest files"
        )


def _copy_verified(
    archive: Path, entries: dict[str, tuple[int, str]], root: Path
) -> None:
    seen: set[str] = set()
    with tarfile.open(archive, mode="r:gz") as bundle:
        for member in bundle:
            if member.isdir():
                continue
            path = _safe_member_path(member.name)
            if not member.isfile() or path not in entries or path in seen:
                raise ArchiveVerificationError(
                    f"archive changed during restore: {path}"
                )
            expected_size, expected_digest = entries[path]
            source = bundle.extractfile(member)
            if source is None:
                raise ArchiveVerificationError(f"cannot read archive member: {path}")
            target = root.joinpath(*PurePosixPath(path).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary_path: Path | None = None
            try:
                with source:
                    with tempfile.NamedTemporaryFile(
                        mode="wb", dir=target.parent, delete=False
                    ) as output:
                        temporary_path = Path(output.name)
                        shutil.copyfileobj(source, output, CHUNK_SIZE)
                        output.flush()
                        os.fsync(output.fileno())
                with temporary_path.open("rb") as copied:
                    actual_digest, actual_size = _digest_stream(copied)
                if (actual_size, actual_digest) != (expected_size, expected_digest):
                    raise ArchiveVerificationError(f"copy digest mismatch: {path}")
                os.replace(temporary_path, target)
            except BaseException:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
                raise
            seen.add(path)
    if seen != set(entries):
        raise ArchiveVerificationError("archive changed during restore")


def _verify_restored(root: Path, entries: dict[str, tuple[int, str]]) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ArchiveVerificationError(
            "destination already exists with a different shape"
        )
    seen = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ArchiveVerificationError("existing destination contains a symlink")
        if path.is_dir():
            continue
        relative = path.relative_to(root).as_posix()
        if not path.is_file() or relative not in entries:
            raise ArchiveVerificationError(
                "existing destination contains an unlisted file"
            )
        with path.open("rb") as stream:
            actual_digest, actual_size = _digest_stream(stream)
        if (actual_size, actual_digest) != entries[relative]:
            raise ArchiveVerificationError(
                "existing destination differs from its manifest"
            )
        seen.add(relative)
    if seen != set(entries):
        raise ArchiveVerificationError("existing destination is incomplete")


def restore_archive(
    archive: Path,
    manifest_path: Path,
    destination: Path,
    *,
    expected_archive_sha256: str,
    expected_manifest_sha256: str,
    expected_source_commit: str,
) -> dict[str, object]:
    with archive.open("rb") as stream:
        archive_digest, archive_size = _digest_stream(stream)
    with manifest_path.open("rb") as stream:
        manifest_digest, _ = _digest_stream(stream)
    if archive_digest != expected_archive_sha256:
        raise ArchiveVerificationError("archive SHA-256 differs from the pinned digest")
    if manifest_digest != expected_manifest_sha256:
        raise ArchiveVerificationError(
            "manifest SHA-256 differs from the pinned digest"
        )
    manifest = json.loads(manifest_path.read_bytes())
    if not isinstance(manifest, dict):
        raise ArchiveVerificationError("manifest root must be an object")
    if manifest.get("source_commit") != expected_source_commit:
        raise ArchiveVerificationError("manifest source commit differs from the pin")
    if manifest.get("archive_sha256") != archive_digest:
        raise ArchiveVerificationError("manifest archive digest does not match")
    if manifest.get("archive_byte_length") != archive_size:
        raise ArchiveVerificationError("manifest archive size does not match")

    entries = _manifest_entries(manifest)
    _verify_archive_contents(archive, entries)
    destination = destination.absolute()
    if os.path.lexists(destination):
        _verify_restored(destination, entries)
        return {
            "archive_sha256": archive_digest,
            "file_count": len(entries),
            "manifest_sha256": manifest_digest,
            "source_commit": expected_source_commit,
            "status": "restored_and_verified",
            "wrote": False,
        }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.restore-", dir=destination.parent)
    )
    try:
        _copy_verified(archive, entries, temporary_root)
        os.replace(temporary_root, destination)
    except BaseException:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise
    return {
        "archive_sha256": archive_digest,
        "file_count": len(entries),
        "manifest_sha256": manifest_digest,
        "source_commit": expected_source_commit,
        "status": "restored_and_verified",
        "wrote": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--expected-archive-sha256", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--expected-source-commit", required=True)
    args = parser.parse_args()
    result = restore_archive(
        args.archive,
        args.manifest,
        args.destination,
        expected_archive_sha256=args.expected_archive_sha256,
        expected_manifest_sha256=args.expected_manifest_sha256,
        expected_source_commit=args.expected_source_commit,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
