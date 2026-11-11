from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
from threading import Barrier, Lock, Thread
from time import sleep
import sys

import pytest

from fundamental_service.replay import (
    ArtifactStore,
    CacheLifecycle,
    DependencyManifestV1,
    build_provenance_graph,
    build_release_manifest,
    ReplayEnvelopeV1,
    replay_calculation,
)
from fundamental_service.application.service import FundamentalApplication
from fundamental_service.operations import OperationalMetrics, OperationsConfig
from fundamental_service.calculator import calculate
from fundamental_service.testsupport import make_valuation
from fundamental_service.snapshots import SnapshotError


def test_offline_replay_matches_and_reports_first_difference(tmp_path: Path):
    request = make_valuation().with_digest()
    expected = calculate(request)
    report = replay_calculation(request, expected)
    assert report.status == "match"
    changed = request.model_copy(update={"model_version": "fcff_dcf-v2"}).with_digest()
    mismatch = replay_calculation(changed, expected)
    assert mismatch.status == "mismatch"
    assert mismatch.first_difference


def test_artifact_store_and_cache_lifecycle_are_separate(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")
    dependency_a = "a" * 64
    dependency_b = "b" * 64
    record = store.put("release-1", {"value": "immutable"}, (dependency_a,))
    assert store.get("release-1").content_hash == record.content_hash
    assert store.invalidate_dependency(dependency_a) == ("release-1",)
    store.reset_operational_cache()
    assert store.get("release-1").status == "stale"
    restarted = ArtifactStore(tmp_path / "artifacts")
    assert restarted.get("release-1").status == "stale"
    assert restarted.read("release-1") == b'{"value":"immutable"}'
    rebuilt = restarted.rebuild("release-1", {"value": "rebuilt"}, (dependency_b,))
    assert rebuilt.status == "valid"
    assert rebuilt.artifact_id != "release-1"
    assert restarted.get("release-1").status == "stale"
    assert restarted.invalidate("release-1").status == "invalidated"
    cache_record = restarted.put(
        "cache-1", {"value": "temporary"}, retention="operational_cache"
    )
    assert cache_record.retention == "operational_cache"
    restarted.invalidate("cache-1")
    assert restarted.prune_expired() == ("cache-1",)
    assert restarted.get("release-1").retention == "evidence"
    cache = CacheLifecycle()
    assert cache.get("key")[0] == "miss"
    cache.put("key", {"projection": 1})
    assert cache.get("key")[0] == "hit"
    cache.put("dependent", 1, (dependency_a,))
    cache.put("independent", 2, (dependency_b,))
    assert cache.invalidate_dependency(dependency_a) == ("dependent",)
    assert cache.get("dependent")[0] == "stale"
    assert cache.get("independent") == ("hit", 2)


def test_artifact_publication_receipt_reports_unchanged_and_rejects_corruption(
    tmp_path: Path,
):
    store = ArtifactStore(tmp_path / "artifacts")
    first = store.put_with_receipt("source-preparation", {"value": 42})
    repeated = store.put_with_receipt("source-preparation", {"value": 42})

    assert first.wrote is True
    assert repeated.wrote is False
    assert repeated.artifact == first.artifact

    artifact_path = store._artifact_path(
        first.artifact.content_hash, "application/json"
    )
    artifact_path.write_bytes(b"corrupt")
    with pytest.raises(SnapshotError, match="failed verification"):
        store.put_with_receipt("source-preparation", {"value": 42})


def test_cache_rebuild_populates_once_for_concurrent_callers():
    cache = CacheLifecycle()
    barrier = Barrier(3)
    calls = 0
    calls_lock = Lock()
    values: list[object] = []

    def factory() -> object:
        nonlocal calls
        with calls_lock:
            calls += 1
        sleep(0.01)
        return {"value": 42}

    def worker() -> None:
        barrier.wait()
        values.append(cache.rebuild("key", factory))

    threads = [Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert calls == 1
    assert values == [{"value": 42}, {"value": 42}]


def test_bounded_cache_evicts_the_oldest_operational_entry():
    cache = CacheLifecycle(max_entries=2)
    cache.put("release-one", 1)
    cache.put("release-two", 2)
    cache.put("release-three", 3)

    assert cache.get("release-one") == ("miss", None)
    assert cache.get("release-two") == ("hit", 2)
    assert cache.get("release-three") == ("hit", 3)


def test_provenance_graph_is_content_addressed():
    observed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    metadata = {
        node_id: {
            "source_id": "source-1",
            "unit": "currency",
            "quality_status": "verified",
            "observed_at": observed_at,
        }
        for node_id in (
            "snapshot-1",
            "a" * 64,
            "b" * 64,
            "reported_intrinsic_value",
            "response-1",
            "filing-1",
            "xbrl-fact-1",
            "fact-1",
            "metric-1",
            "assumption-1",
            "model-input-1",
            "node-1",
            "scenario-1",
            "interval-1",
        )
    }
    graph = build_provenance_graph(
        snapshot_id="snapshot-1",
        fact_ids=("fact-1",),
        assumption_ids=("assumption-1",),
        model_input_ids=("model-input-1",),
        calculation_node_ids=("node-1",),
        scenario_ids=("scenario-1",),
        raw_response_ids=("response-1",),
        filing_package_ids=("filing-1",),
        xbrl_fact_ids=("xbrl-fact-1",),
        normalized_metric_ids=("metric-1",),
        interval_ids=("interval-1",),
        node_metadata=metadata,
        code_version="service-1",
        policy_version="policy-1",
        quality_status="verified",
        input_digest="a" * 64,
        result_hash="b" * 64,
    )
    assert graph.graph_digest
    assert any(edge.relation == "calculated_by" for edge in graph.edges)
    assert {node.node_type for node in graph.nodes} >= {
        "filing_snapshot",
        "canonical_fact",
        "assumption",
        "model_input",
        "calculation_node",
        "scenario",
        "reported_value",
    }


def test_release_manifest_is_stable_and_pins_dependencies():
    dependencies = DependencyManifestV1(
        runtime_version="python-3.11",
        parser_version="parser-1",
        taxonomy_version="taxonomy-1",
        model_version="fcff_dcf-v1",
        policy_version="policy-1",
        calculation_version="calculator-v1",
        source_content_hashes=("a" * 64,),
    )
    manifest = build_release_manifest(
        release_id="release-1",
        service_version="service-1",
        snapshot_ids=("snapshot-1",),
        input_hashes=("b" * 64,),
        artifact_hashes=("c" * 64,),
        artifact_ids=("artifact-1",),
        dependencies=dependencies,
        quality_policy_version="quality-1",
        decision_timestamp=make_valuation().valuation_context.valuation_timestamp,
        issuer_id="issuer-1",
        security_id="security-1",
        canonical_fact_ids=("fact-1",),
        assumption_ids=("assumption-1",),
        calibration_artifact_ids=("calibration-1",),
        numerical_settings={"precision": "50"},
        release_profile_thresholds={"quality": "verified"},
    )
    assert manifest.manifest_digest
    assert manifest.input_hashes == ("b" * 64,)
    assert manifest.source_content_hashes == ("a" * 64,)


def test_manifest_driven_replay_is_offline(tmp_path: Path):
    request = make_valuation().with_digest()
    expected = calculate(request)
    store = ArtifactStore(tmp_path / "artifacts")
    store.put("artifact-1", expected)
    source_record = store.put("source", {"source": "source"})
    dependencies = DependencyManifestV1(
        runtime_version=f"python-{sys.version_info.major}.{sys.version_info.minor}",
        parser_version=request.provenance.parser_version,
        taxonomy_version=request.provenance.taxonomy_version,
        model_version=request.model_version,
        policy_version=request.policy_id,
        calculation_version=expected.calculation_version,
        source_content_hashes=(source_record.content_hash,),
    )
    manifest = build_release_manifest(
        release_id="release-1",
        service_version="0.1.0",
        snapshot_ids=(request.valuation_context.data_snapshot_id,),
        input_hashes=(request.input_digest,),
        artifact_hashes=(expected.result_hash,),
        artifact_ids=("artifact-1",),
        dependencies=dependencies,
        quality_policy_version="quality-1",
        decision_timestamp=request.valuation_context.valuation_timestamp,
        issuer_id=request.identity.issuer_id,
        security_id=request.identity.security_id,
        canonical_fact_ids=request.historical_facts,
        assumption_ids=("assumptions",),
        calibration_artifact_ids=("calibration-1",),
        numerical_settings={"precision": "50"},
        release_profile_thresholds={"quality": "verified"},
    )
    application = FundamentalApplication(
        artifact_store=store,
        content_store=None,
        config=OperationsConfig.testing(),
        metrics=OperationalMetrics(),
        snapshot_repository=SimpleNamespace(
            get=lambda snapshot_id: SimpleNamespace(
                snapshot_id=snapshot_id,
                coverage_status=SimpleNamespace(value="verified"),
                identity=SimpleNamespace(
                    issuer_id=request.identity.issuer_id,
                    security_id=request.identity.security_id,
                ),
                valuation_timestamp=request.valuation_context.valuation_timestamp,
                source_records=(
                    SimpleNamespace(content_hash=source_record.content_hash),
                ),
            )
        ),
    )
    report = application.replay_valuation(
        ReplayEnvelopeV1(manifest=manifest, request=request, expected=expected)
    )
    assert report.status == "match"
    assert report.offline is True


def test_operational_cleanup_cannot_remove_shared_evidence(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")
    evidence = store.put("release", {"same": True})
    cache = store.put(
        "cache",
        {"same": True},
        retention="operational_cache",
    )
    store.invalidate("cache")
    assert store.prune_expired() == ()
    assert store.read("release")
    assert evidence.content_hash == cache.content_hash


def test_cache_ttl_expires_without_touching_retained_values():
    cache = CacheLifecycle()
    cache.put("expiring", 1, ttl_seconds=0.001)
    sleep(0.01)
    assert cache.get("expiring")[0] == "stale"
    cache.put("retained", 2, retained=True, ttl_seconds=0.001)
    sleep(0.01)
    assert cache.get("retained") == ("hit", 2)
