import hashlib
import importlib.util
import io
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
