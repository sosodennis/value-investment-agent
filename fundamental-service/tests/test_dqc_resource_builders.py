import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


builder = _load("prepare_dqc_v18_resources")
taxonomy = _load("rebuild_taxonomy_cache")


def test_source_builder_resolves_official_symlink_and_preserves_every_source(
    tmp_path: Path,
):
    raw = b"constant $original = 1"
    digest = hashlib.sha256(raw).hexdigest()
    root = f"dqc_us_rules-{builder.DQC_V18_SOURCE_COMMIT}/"
    prefix = root + "dqc_us_rules/source/us/2022/"
    expected = builder.RuleInventory(
        files=[{"name": "functions.xule", "file_hash": digest}],
        rules={},
        functions={},
        constants={},
        namespaces={},
        output_attributes={},
        xule_compiled_version=23280,
    )
    memory = io.BytesIO()
    with ZipFile(memory, "w") as archive:
        archive.writestr(root + "dqc_us_rules/source/functions.xule", raw)
        link = ZipInfo(prefix + "functions.xule")
        link.external_attr = 0o120777 << 16
        archive.writestr(link, "../../functions.xule")
    with ZipFile(memory) as archive:
        builder._stage_sources(archive, 2022, tmp_path, expected)
    assert (tmp_path / "functions.xule").read_bytes() == raw
    assert (tmp_path / "functions.xule").stat().st_mtime == builder.SOURCE_MTIME
    changed = expected.model_copy(update={"files": ()})
    with ZipFile(memory) as archive, pytest.raises(ValueError, match="differs"):
        builder._stage_sources(archive, 2022, tmp_path, changed)


def test_resource_retention_is_idempotent_and_refuses_replacement(tmp_path: Path):
    path = tmp_path / "resource.zip"
    builder._retain(path, b"pinned")
    before = path.stat().st_mtime_ns
    builder._retain(path, b"pinned")
    assert path.stat().st_mtime_ns == before
    with pytest.raises(ValueError, match="differs"):
        builder._retain(path, b"changed")
    assert path.read_bytes() == b"pinned"


def _manifest(root: Path):
    path = root / "https/xbrl.fasb.org/example.xsd"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"retained taxonomy")
    return taxonomy.TaxonomyManifest(
        protocol="arelle-taxonomy-cache-manifest-v1",
        cache_sha256=taxonomy._directory_hash(root),
        resources=[
            {
                "uri": "https://xbrl.fasb.org/example.xsd",
                "retrieval_uri": "https://xbrl.fasb.org/example.xsd",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "byte_size": path.stat().st_size,
            }
        ],
    )


def test_cache_rebuild_replays_retained_bytes_and_refuses_corruption(tmp_path: Path):
    source, target = tmp_path / "source", tmp_path / "target"
    manifest = _manifest(source)
    assert (
        taxonomy.rebuild(manifest, target, retained_cache=source)
        == manifest.cache_sha256
    )
    assert taxonomy.rebuild(manifest, target) == manifest.cache_sha256
    resource = target / manifest.resources[0].cache_path
    resource.write_bytes(b"changed")
    with pytest.raises(ValueError, match="differs from its pin"):
        taxonomy.rebuild(manifest, target, retained_cache=source)
    assert resource.read_bytes() == b"changed"


def test_cache_rebuild_never_downloads_implicitly(tmp_path: Path):
    manifest = _manifest(tmp_path / "source")
    with pytest.raises(ValueError, match="is unavailable"):
        taxonomy.rebuild(manifest, tmp_path / "target")
    changed = manifest.resources[0].model_dump()
    changed["uri"] = "https://xbrl.fasb.org/../outside.xsd"
    with pytest.raises(ValueError, match="relative cache path"):
        taxonomy.TaxonomyResource.model_validate(changed)


def test_manifest_fragments_rebuild_one_complete_cache_and_refuse_omissions(
    tmp_path: Path,
):
    source = tmp_path / "source"
    first = _manifest(source)
    resource = first.resources[0]
    second = resource.model_copy(
        update={"uri": "https://xbrl.fasb.org/second.xsd", "retrieval_uri": None}
    )
    (source / second.cache_path).write_bytes(
        (source / resource.cache_path).read_bytes()
    )
    digest = taxonomy._directory_hash(source)
    fragments = []
    for ordinal, item in enumerate((resource, second)):
        path = tmp_path / f"part-{ordinal}.json"
        path.write_text(
            first.model_copy(
                update={"cache_sha256": digest, "resources": (item,)}
            ).model_dump_json()
        )
        fragments.append(path)
    destination = tmp_path / "rebuilt"
    with pytest.raises(ValueError, match="composite hash differs"):
        taxonomy.rebuild(
            taxonomy.load_manifest(fragments[:1]), destination, retained_cache=source
        )
    assert (
        taxonomy.rebuild(
            taxonomy.load_manifest(fragments), destination, retained_cache=source
        )
        == digest
    )
    with pytest.raises(ValueError, match="unique and sorted"):
        taxonomy.load_manifest((fragments[0], fragments[0]))
    fragments[1].write_text(first.model_dump_json())
    with pytest.raises(ValueError, match="pin one complete cache"):
        taxonomy.load_manifest(fragments)


def test_issue522_delta_fixture_binds_the_retained_base_and_new_resource(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(root.parent)
    base_paths = tuple(
        Path("fundamental-service/tests/fixtures/annual-statements")
        / f"issue494-sec-taxonomy-resources-part-{part}.json"
        for part in (1, 2)
    )
    delta_path = Path(
        "fundamental-service/tests/fixtures/annual-statements/issue522-ecd-taxonomy-resource-delta.json"
    )
    manifest = taxonomy.load_delta_manifest(base_paths, delta_path)
    assert (
        manifest.cache_sha256
        == "af63b0b36d5cad6f2788e90fc323b56955ce581fd84e41330bac4ba765f3a6f0"
    )
    assert any(
        item.uri == "https://xbrl.sec.gov/ecd/2026/ecd-sub-2026.xsd"
        for item in manifest.resources
    )
    assert len(manifest.resources) == 3230


def test_delta_cli_rebuilds_a_target_cache_and_rejects_extra_files(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "retained"
    source.mkdir()
    resources = []
    for name, payload in (("a.xsd", b"a"), ("b.xsd", b"b")):
        path = source / "https/example.test" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        resources.append(
            taxonomy.TaxonomyResource(
                uri=f"https://example.test/{name}",
                sha256=hashlib.sha256(payload).hexdigest(),
                byte_size=len(payload),
            )
        )
    base_hash = taxonomy._directory_hash(source)
    base_manifests = []
    for ordinal, resource in enumerate(resources):
        fragment = Path(f"base-{ordinal}.json")
        fragment.write_text(
            taxonomy.TaxonomyManifest(
                protocol="arelle-taxonomy-cache-manifest-v1",
                cache_sha256=base_hash,
                resources=(resource,),
            ).model_dump_json()
        )
        base_manifests.append(fragment)
    delta_resource = taxonomy.TaxonomyResource(
        uri="https://example.test/c.xsd",
        sha256=hashlib.sha256(b"c").hexdigest(),
        byte_size=1,
    )
    (source / delta_resource.cache_path).parent.mkdir(parents=True, exist_ok=True)
    (source / delta_resource.cache_path).write_bytes(b"c")
    target_hash = taxonomy._directory_hash(source)
    delta_path = Path("delta.json")
    delta_path.write_text(
        json.dumps(
            {
                "protocol": "arelle-taxonomy-cache-delta-v1",
                "base_manifests": [
                    {
                        "path": str(path),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                    for path in base_manifests
                ],
                "base_cache_sha256": base_hash,
                "cache_sha256": target_hash,
                "resources": [delta_resource.model_dump()],
            }
        )
    )
    destination = tmp_path / "rebuilt"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rebuild_taxonomy_cache.py",
            "--delta-manifest",
            str(delta_path),
            "--base-manifest",
            str(base_manifests[0]),
            "--base-manifest",
            str(base_manifests[1]),
            "--retained-cache",
            str(source),
            "--destination",
            str(destination),
        ],
    )
    taxonomy.main()
    assert capsys.readouterr().out.strip() == target_hash
    resource_mtime = (destination / delta_resource.cache_path).stat().st_mtime_ns
    taxonomy.main()
    assert capsys.readouterr().out.strip() == target_hash
    assert (
        destination / delta_resource.cache_path
    ).stat().st_mtime_ns == resource_mtime
    (destination / "unexpected.txt").write_bytes(b"unexpected")
    with pytest.raises(ValueError, match="composite hash differs"):
        taxonomy.rebuild(
            taxonomy.load_delta_manifest(base_manifests, delta_path),
            destination,
            retained_cache=source,
        )

    source_resource = source / delta_resource.cache_path
    source_payload = source_resource.read_bytes()
    source_resource.write_bytes(b"changed")
    with pytest.raises(ValueError, match="differs from its pin"):
        taxonomy.rebuild(
            taxonomy.load_delta_manifest(tuple(base_manifests), delta_path),
            tmp_path / "corrupt-rebuild",
            retained_cache=source,
        )
    source_resource.unlink()
    with pytest.raises(ValueError, match="is unavailable"):
        taxonomy.rebuild(
            taxonomy.load_delta_manifest(tuple(base_manifests), delta_path),
            tmp_path / "missing-rebuild",
            retained_cache=source,
        )
    source_resource.write_bytes(source_payload)

    original_base = base_manifests[0].read_bytes()
    base_manifests[0].write_bytes(original_base + b"\n")
    with pytest.raises(ValueError, match="base manifest differs from its pin"):
        taxonomy.load_delta_manifest(tuple(base_manifests), delta_path)
    base_manifests[0].write_bytes(original_base)
    with pytest.raises(ValueError, match="destination must differ"):
        taxonomy.rebuild(
            taxonomy.load_delta_manifest(tuple(base_manifests), delta_path),
            source,
            retained_cache=source,
        )


@pytest.mark.parametrize("overlap", ("same", "child", "parent"))
def test_rebuild_rejects_overlapping_roots_before_writing(tmp_path, overlap):
    source = tmp_path / "retained"
    resource = taxonomy.TaxonomyResource(
        uri="https://example.test/a.xsd",
        sha256=hashlib.sha256(b"a").hexdigest(),
        byte_size=1,
    )
    original = source / resource.cache_path
    original.parent.mkdir(parents=True)
    original.write_bytes(b"a")
    before = taxonomy._directory_hash(source)
    manifest = taxonomy.TaxonomyManifest(
        protocol="arelle-taxonomy-cache-manifest-v1",
        cache_sha256=before,
        resources=(resource,),
    )
    destination = {"same": source, "child": source / "nested", "parent": tmp_path}[
        overlap
    ]
    with pytest.raises(ValueError, match="without overlapping"):
        taxonomy.rebuild(manifest, destination, retained_cache=source)
    assert taxonomy._directory_hash(source) == before
    assert not (source / "nested").exists()
    assert not (tmp_path / "https").exists()


@pytest.mark.parametrize("with_retained_cache", (True, False))
def test_rebuild_rejects_resource_symlink_escape_before_writing(
    tmp_path, with_retained_cache
):
    source = tmp_path / "retained"
    existing = source / "https/example.test/a.xsd"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"a")
    before = taxonomy._directory_hash(source)
    resource = taxonomy.TaxonomyResource(
        uri="https://example.test/new.xsd",
        sha256=hashlib.sha256(b"new").hexdigest(),
        byte_size=3,
    )
    manifest = taxonomy.TaxonomyManifest(
        protocol="arelle-taxonomy-cache-manifest-v1",
        cache_sha256="0" * 64,
        resources=(resource,),
    )
    destination = tmp_path / "target"
    destination.mkdir()
    (destination / "https").symlink_to(source / "https", target_is_directory=True)
    with pytest.raises(ValueError, match="must remain within destination"):
        taxonomy.rebuild(
            manifest,
            destination,
            retained_cache=source if with_retained_cache else None,
        )
    assert taxonomy._directory_hash(source) == before
    assert not (source / resource.cache_path).exists()
