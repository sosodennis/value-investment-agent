from __future__ import annotations

import hashlib
import json
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from verify_issue361_research_archive import ArchiveVerificationError, restore_archive


def _make_archive(
    root: Path, *, member_path: str = "study/report.json"
) -> tuple[Path, Path]:
    content = b'{"status":"fixture"}\n'
    source = root / "source.json"
    source.write_bytes(content)
    archive = root / "fixture.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(source, arcname=member_path)
    manifest = {
        "archive_byte_length": archive.stat().st_size,
        "archive_filename": archive.name,
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "files": [
            {
                "byte_length": len(content),
                "path": member_path,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
        "source_commit": "a" * 40,
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return archive, manifest_path


def _restore(archive: Path, manifest: Path, destination: Path) -> dict[str, object]:
    return restore_archive(
        archive,
        manifest,
        destination,
        expected_archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        expected_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        expected_source_commit="a" * 40,
    )


def test_restore_verifies_and_writes_to_new_destination(tmp_path: Path) -> None:
    archive, manifest = _make_archive(tmp_path)
    destination = tmp_path / "restored"

    result = _restore(archive, manifest, destination)

    assert result["status"] == "restored_and_verified"
    assert result["file_count"] == 1
    assert (destination / "study/report.json").read_bytes() == b'{"status":"fixture"}\n'


@pytest.mark.parametrize(
    "member_path", ["../outside.json", "/outside.json", "..\\outside.json"]
)
def test_restore_rejects_unsafe_member_path(tmp_path: Path, member_path: str) -> None:
    archive, manifest = _make_archive(tmp_path, member_path=member_path)

    with pytest.raises(ArchiveVerificationError):
        _restore(archive, manifest, tmp_path / "restored")


def test_restore_rejects_existing_destination_and_preserves_it(tmp_path: Path) -> None:
    archive, manifest = _make_archive(tmp_path)
    destination = tmp_path / "restored"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_text("keep", encoding="ascii")

    with pytest.raises(ArchiveVerificationError, match="existing destination"):
        _restore(archive, manifest, destination)

    assert sentinel.read_text(encoding="ascii") == "keep"


def test_restore_reuses_verified_destination_without_rewriting(tmp_path: Path) -> None:
    archive, manifest = _make_archive(tmp_path)
    destination = tmp_path / "restored"
    assert _restore(archive, manifest, destination)["wrote"] is True
    target = destination / "study/report.json"
    before = target.stat().st_mtime_ns
    assert _restore(archive, manifest, destination)["wrote"] is False
    assert target.stat().st_mtime_ns == before
    target.write_bytes(b"corrupt")
    with pytest.raises(ArchiveVerificationError, match="differs"):
        _restore(archive, manifest, destination)


def test_restore_rejects_manifest_content_mismatch_before_writing(
    tmp_path: Path,
) -> None:
    archive, manifest_path = _make_archive(tmp_path)
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ArchiveVerificationError, match="content digest mismatch"):
        _restore(archive, manifest_path, tmp_path / "restored")

    assert not (tmp_path / "restored").exists()
