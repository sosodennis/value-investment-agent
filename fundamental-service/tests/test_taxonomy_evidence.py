"""Real cache-directory semantics, without network resources or fake blob hashes."""

import hashlib
import io
import json
import stat
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from fundamental_service.arelle_parser import _directory_hash
from fundamental_service.data_releases import ArtifactRefV1, DataReleaseError
from fundamental_service.taxonomy_evidence import (
    TAXONOMY_CACHE_ARCHIVE_ROLE,
    build_taxonomy_cache_archive,
    require_original_taxonomy,
    taxonomy_cache_archive_digest,
)
from test_automatic_mapping import case, evaluate
from test_issuer_operating_release import fixture, resign, rebind_original
from fundamental_service.original_issuer import evaluate_original_issuer
from fundamental_service.serialization import canonical_bytes


def directory(tmp_path):
    root = tmp_path / "taxonomy-cache"
    for name, content in (
        ("http/example.org/a/schema.xsd", b"exact \x00 schema\r\n"),
        ("http/example.org/a.xsd", b"path order differs from string order"),
        ("http/example.org/schema.xml", b"<taxonomy/>"),
        ("__pycache__/ignore.pyc", b"excluded from parser digest"),
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return root


def reference(raw):
    return ArtifactRefV1(
        artifact_id="taxonomy-cache",
        content_hash=hashlib.sha256(raw).hexdigest(),
        media_type="application/zip",
        role=TAXONOMY_CACHE_ARCHIVE_ROLE,
    )


def test_retained_cache_archive_replays_real_parser_directory_hash(tmp_path):
    root = directory(tmp_path)
    raw = build_taxonomy_cache_archive(root)
    assert raw == build_taxonomy_cache_archive(root)
    assert taxonomy_cache_archive_digest(raw) == _directory_hash(root)
    ref = reference(raw)
    require_original_taxonomy(_directory_hash(root), (ref,), {ref.content_hash: raw})
    with pytest.raises(DataReleaseError):
        require_original_taxonomy("a" * 64, (ref,), {ref.content_hash: raw})
    with pytest.raises(DataReleaseError):
        require_original_taxonomy(
            _directory_hash(root), (ref,), {ref.content_hash: raw + b"changed"}
        )
    assert not (tmp_path / "extracted").exists()


@pytest.mark.parametrize(
    "name",
    (
        "../outside",
        "/absolute",
        "a/../b",
        "a\\b",
        "a//b",
        "a/",
        "__pycache__/x",
        "x.pyc",
    ),
)
def test_unsafe_or_excluded_members_are_rejected(tmp_path, name):
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(name, b"data")
    with pytest.raises(DataReleaseError) as error:
        taxonomy_cache_archive_digest(buffer.getvalue())
    assert error.value.code == "DATA_RELEASE_TAXONOMY_ARCHIVE_INVALID"


@pytest.mark.parametrize("names", (("b", "a"), ("a", "a"), ()))
def test_order_duplicate_and_empty_archives_are_rejected(names):
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, b"data")
    with pytest.raises(DataReleaseError):
        taxonomy_cache_archive_digest(buffer.getvalue())


def test_symlink_and_truncated_archives_are_rejected():
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        member = ZipInfo("symbolic-link")
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(member, b"target")
    for raw in (buffer.getvalue(), buffer.getvalue()[:20]):
        with pytest.raises(DataReleaseError):
            taxonomy_cache_archive_digest(raw)


def test_corrupt_deflate_member_retains_typed_evidence_failure():
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("schema.xsd", b"x" * 10_000)
    raw = bytearray(buffer.getvalue())
    raw[30 + len("schema.xsd")] = 255
    with pytest.raises(DataReleaseError) as error:
        taxonomy_cache_archive_digest(bytes(raw))
    assert error.value.code == "DATA_RELEASE_TAXONOMY_ARCHIVE_INVALID"


def test_automatic_approval_accepts_original_directory_evidence(tmp_path):
    request, store, _, _ = case(tmp_path)
    root = directory(tmp_path)
    raw = build_taxonomy_cache_archive(root)
    ref = reference(raw)
    store.put_bytes_with_receipt(ref.artifact_id, raw, media_type=ref.media_type)
    digest = _directory_hash(root)

    original = evaluate_original_issuer(
        request.original.report.model_copy(update={"taxonomy_cache_hash": digest}),
        source=request.original.source,
        decision_at=request.original.decision_at,
    )
    changed = request.model_copy(
        update={
            "original": original,
            "integrity": request.integrity.model_copy(
                update={"taxonomy_manifest_hash": digest}
            ),
            "evidence_refs": tuple(
                sorted((*request.evidence_refs, ref), key=lambda item: item.artifact_id)
            ),
        }
    )
    assert evaluate(changed, store).status == "approved"


def test_issuer_release_canary_replays_cache_archive_instead_of_blob(tmp_path):
    bundle, service, evidence, _, _ = fixture(tmp_path)
    root = directory(tmp_path)
    raw, digest = build_taxonomy_cache_archive(root), _directory_hash(root)
    ref = evidence.add("retained-cache", raw, TAXONOMY_CACHE_ARCHIVE_ROLE)

    changed = rebind_original(bundle, report_changes={"taxonomy_cache_hash": digest})
    integrity = json.loads(evidence.values["synthetic-integrity"])
    integrity["taxonomy_manifest_hash"] = digest
    integrity_ref = evidence.add(
        "cache-integrity", canonical_bytes(integrity), "sec-issuer-integrity-v1"
    )
    changed = resign(
        changed,
        taxonomy_refs=(ref,),
        artifact_refs=tuple(
            integrity_ref if r.role == "sec-issuer-integrity-v1" else r
            for r in changed.manifest.artifact_refs
        ),
    )
    assert service.publish(changed).wrote
