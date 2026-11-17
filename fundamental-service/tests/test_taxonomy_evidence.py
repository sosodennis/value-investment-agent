"""Real cache-directory semantics, without network resources or fake blob hashes."""

import hashlib
import io
import json
import stat
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from fundamental_service.arelle_parser import _directory_hash
from fundamental_service.data_releases import ArtifactRefV1, DataReleaseError
from fundamental_service.taxonomy_evidence import (
    TAXONOMY_CACHE_ARCHIVE_ROLE,
    TaxonomyArchiveChecks,
    build_taxonomy_cache_archive,
    require_original_taxonomy,
    taxonomy_cache_archive_digest,
)
from fundamental_service import taxonomy_evidence
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


def test_taxonomy_scope_reuses_computation_but_checks_each_binding(
    tmp_path, monkeypatch
):
    root = directory(tmp_path)
    raw = build_taxonomy_cache_archive(root)
    ref, expected = reference(raw), _directory_hash(root)
    calculate = taxonomy_evidence.taxonomy_cache_archive_digest
    calls = []

    def observed(content):
        calls.append(hashlib.sha256(content).hexdigest())
        return calculate(content)

    monkeypatch.setattr(taxonomy_evidence, "taxonomy_cache_archive_digest", observed)
    checks = TaxonomyArchiveChecks()
    for _ in range(4):
        require_original_taxonomy(
            expected, (ref,), {ref.content_hash: raw}, archive_checks=checks
        )
    assert calls == [ref.content_hash]
    for digest, refs, contents in (
        ("f" * 64, (ref,), {ref.content_hash: raw}),
        (expected, (ref,), {ref.content_hash: raw + b"changed"}),
        (
            expected,
            (ref.model_copy(update={"role": "unrelated"}),),
            {ref.content_hash: raw},
        ),
        (expected, (), {ref.content_hash: raw}),
    ):
        with pytest.raises(DataReleaseError):
            require_original_taxonomy(digest, refs, contents, archive_checks=checks)
    require_original_taxonomy(
        expected,
        (ref,),
        {ref.content_hash: raw},
        archive_checks=TaxonomyArchiveChecks(),
    )
    assert calls == [ref.content_hash, ref.content_hash]


@pytest.mark.parametrize(
    "limits", ({"max_entries": 0}, {"max_retained_bytes": 0}, {"max_entries": 1})
)
def test_taxonomy_scope_capacity_recomputes_without_changing_results(
    tmp_path, monkeypatch, limits
):
    root = directory(tmp_path)
    first = build_taxonomy_cache_archive(root)
    (root / "other.xml").write_bytes(b"another dependency")
    second = build_taxonomy_cache_archive(root)
    calculate = taxonomy_evidence.taxonomy_cache_archive_digest
    calls = []

    def observed(content):
        calls.append(True)
        return calculate(content)

    monkeypatch.setattr(taxonomy_evidence, "taxonomy_cache_archive_digest", observed)
    checks = TaxonomyArchiveChecks(**limits)
    for raw in (first, second, first):
        assert checks.digest(raw) == calculate(raw)
    assert len(calls) == 3


def test_taxonomy_scope_does_not_retain_failed_checks_or_trust_mutable_bytes(
    tmp_path, monkeypatch
):
    raw = build_taxonomy_cache_archive(directory(tmp_path))
    calculate = taxonomy_evidence.taxonomy_cache_archive_digest
    calls = []

    def observed(content):
        calls.append(True)
        return calculate(content)

    monkeypatch.setattr(taxonomy_evidence, "taxonomy_cache_archive_digest", observed)
    checks = TaxonomyArchiveChecks()
    mutable = bytearray(raw)
    assert checks.digest(mutable) == calculate(raw)
    mutable[:] = b"invalid archive"
    for _ in range(2):
        with pytest.raises(DataReleaseError):
            checks.digest(mutable)
    assert len(calls) == 3
    assert checks.digest(raw) == calculate(raw)
    assert len(calls) == 3


@pytest.mark.parametrize("limits", ({"max_entries": -1}, {"max_retained_bytes": -1}))
def test_taxonomy_scope_rejects_negative_limits(limits):
    with pytest.raises(ValueError):
        TaxonomyArchiveChecks(**limits)


def test_taxonomy_scope_hits_preserve_positive_retained_byte_budget(tmp_path):
    root = directory(tmp_path)
    first = build_taxonomy_cache_archive(root)
    (root / "other.xml").write_bytes(b"another dependency")
    second = build_taxonomy_cache_archive(root)
    checks = TaxonomyArchiveChecks(max_retained_bytes=900)
    for _ in range(25):
        for raw in (first, second):
            assert checks.digest(raw) == taxonomy_cache_archive_digest(raw)
            retained = sys.getsizeof(checks._digests) + sum(
                sys.getsizeof(key) + sys.getsizeof(value)
                for key, value in checks._digests.items()
            )
            assert retained <= 900


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


def archive_request(tmp_path):
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
    return changed, store


def test_automatic_approval_accepts_original_directory_evidence(tmp_path):
    request, store = archive_request(tmp_path)
    assert evaluate(request, store).status == "approved"


def test_distinct_source_checks_share_taxonomy_but_independent_checks_do_not(
    tmp_path, monkeypatch
):
    from fundamental_service.automatic_mapping_evidence import (
        AutomaticMappingEvidenceChecks,
    )

    request, store = archive_request(tmp_path)
    contents = {
        ref.content_hash: store.read(ref.artifact_id) for ref in request.evidence_refs
    }
    alternatives = tuple(
        request.model_copy(update={"source_revision": letter * 40})
        for letter in ("a", "b", "c")
    )
    expected = tuple(
        AutomaticMappingEvidenceChecks().assess(item, contents=contents)
        for item in alternatives
    )
    calculate = taxonomy_evidence.taxonomy_cache_archive_digest
    calls = []

    def observed(raw):
        calls.append(True)
        return calculate(raw)

    monkeypatch.setattr(taxonomy_evidence, "taxonomy_cache_archive_digest", observed)
    checks = AutomaticMappingEvidenceChecks()
    assert (
        tuple(checks.assess(item, contents=contents) for item in alternatives)
        == expected
    )
    assert calls == [True]
    assert (
        AutomaticMappingEvidenceChecks().assess(request, contents=contents)
        == expected[0]
    )
    assert calls == [True, True]


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
