from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from fundamental_service.contracts import (
    IdentityV1,
    QualityStatus,
    SourceRecordV1,
    SourceRole,
    SourceSnapshotV1,
)
from fundamental_service.facts import CanonicalMappingV1
from fundamental_service.metadata import (
    SCHEMA_VERSION,
    PostgresArtifactStore,
    PostgresContentStore,
    PostgresMetadataStore,
    PostgresSnapshotRepository,
)
from fundamental_service.policies import PolicyRecordV1, initial_model_specs
from fundamental_service.serialization import sha256_digest
from fundamental_service.snapshots import SnapshotError
from fundamental_service.testsupport import make_valuation

DATABASE_URL = os.getenv("FUNDAMENTAL_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason=(
        "FUNDAMENTAL_TEST_DATABASE_URL is required for the PostgreSQL acceptance suite"
    ),
)


def _snapshot(suffix: str, *, policy_version: str = "policy-v1") -> SourceSnapshotV1:
    now = datetime(2026, 1, 2, tzinfo=UTC)
    source = SourceRecordV1(
        source_id="sec-companyfacts",
        uri=f"https://example.test/{suffix}",
        role=SourceRole.FILING,
        available_at=now,
        captured_at=now,
        http_status=200,
        media_type="application/json",
        terms_reference="sec-public",
        content_hash="a" * 64,
        parser_version="parser-v1",
    )
    identity = IdentityV1(
        issuer_id="0000000001",
        issuer_name="Example Co",
        security_id="EXAMPLE-COMMON",
        share_class="COMMON",
        domicile="US",
        reporting_basis="us-gaap",
        currency="USD",
    )
    payload = {
        "contract_version": "fundamental.v1",
        "snapshot_id": f"snapshot-{suffix}",
        "identity": identity,
        "valuation_timestamp": now,
        "captured_at": now,
        "source_records": (source,),
        "taxonomy_manifest_id": None,
        "parser_version": "parser-v1",
        "policy_version": policy_version,
        "coverage_status": QualityStatus.VERIFIED,
        "issues": (),
    }
    return SourceSnapshotV1(
        **payload,
        manifest_digest=sha256_digest(
            {key: value for key, value in payload.items() if key != "snapshot_id"}
        ),
    )


@pytest.fixture
def metadata() -> PostgresMetadataStore:
    assert DATABASE_URL is not None
    store = PostgresMetadataStore(DATABASE_URL, auto_migrate=True)
    store.start()
    yield store
    store.close()


def test_schema_and_snapshot_survive_restart(metadata: PostgresMetadataStore):
    snapshot = _snapshot(uuid4().hex)
    repository = PostgresSnapshotRepository(metadata)
    repository.publish(snapshot)
    assert metadata.health == type(metadata.health)(True, SCHEMA_VERSION)

    metadata.close()
    restarted = PostgresMetadataStore(DATABASE_URL or "", auto_migrate=False)
    restarted.start()
    try:
        assert (
            PostgresSnapshotRepository(restarted).get(snapshot.snapshot_id) == snapshot
        )
        assert restarted.health.schema_version == SCHEMA_VERSION
    finally:
        restarted.close()


def test_snapshot_metadata_is_immutable(metadata: PostgresMetadataStore):
    suffix = uuid4().hex
    repository = PostgresSnapshotRepository(metadata)
    repository.publish(_snapshot(suffix))
    with pytest.raises(SnapshotError, match="immutable"):
        repository.publish(_snapshot(suffix, policy_version="policy-v2"))


def test_versioned_releases_and_mappings_are_durable_and_immutable(
    metadata: PostgresMetadataStore,
):
    model = initial_model_specs()[0]
    metadata.publish_model(
        model, model_id=model.model_id, model_version=model.model_version
    )
    assert metadata.get_model(model.model_id, model.model_version) == model

    request = make_valuation()
    policy_payload = {
        "contract_version": "fundamental.v1",
        "policy_id": "policy-postgres-v1",
        "policy_version": "policy-postgres-v1",
        "profile_id": "us-gaap-public-v1",
        "model_id": model.model_id,
        "assumptions": request.assumptions,
        "source_refs": ("public-policy",),
        "effective_at": datetime(2026, 1, 1, tzinfo=UTC),
        "status": "active",
    }
    policy = PolicyRecordV1(
        **policy_payload, policy_digest=sha256_digest(policy_payload)
    )
    metadata.publish_policy(
        policy, policy_id=policy.policy_id, policy_version=policy.policy_version
    )
    assert metadata.get_policy(policy.policy_id, policy.policy_version) == policy

    mapping = CanonicalMappingV1(
        contract_version="fundamental.v1",
        decision_id="mapping-postgres-v1",
        source_concept="us-gaap:Revenue",
        normalized_field="revenue",
        mapping_version="mapping-v1",
        confidence="high",
        status="approved",
    )
    metadata.publish_mapping(mapping)
    assert metadata.get_mapping(mapping.decision_id) == mapping

    with pytest.raises(SnapshotError, match="immutable"):
        metadata.publish_mapping(mapping.model_copy(update={"mapping_version": "v2"}))


def test_schema_mismatch_fails_readiness_closed(
    monkeypatch: pytest.MonkeyPatch,
):
    assert DATABASE_URL is not None
    store = PostgresMetadataStore(DATABASE_URL, auto_migrate=False)

    async def stale_schema() -> str:
        return "stale-schema"

    monkeypatch.setattr(store, "_schema_version", stale_schema)
    try:
        with pytest.raises(SnapshotError, match="unavailable"):
            store.start()
        assert store.ready is False
        assert store.health.schema_version is None
    finally:
        store.close()


def test_artifact_publication_is_concurrent_and_hash_verified(
    metadata: PostgresMetadataStore, tmp_path: Path
):
    content = PostgresContentStore(tmp_path / "content", metadata)
    artifacts = PostgresArtifactStore(metadata, content)
    artifact_id = f"artifact-{uuid4().hex}"

    def publish() -> str:
        return artifacts.put(artifact_id, {"value": "immutable"}).content_hash

    with ThreadPoolExecutor(max_workers=6) as executor:
        hashes = tuple(executor.map(lambda _: publish(), range(12)))
    assert set(hashes) == {hashes[0]}
    assert artifacts.read(artifact_id) == b'{"value":"immutable"}'

    record = artifacts.get(artifact_id)
    path = content._filesystem._path(record.content_hash, record.media_type)
    path.write_bytes(b"tampered")
    with pytest.raises(SnapshotError, match="verification"):
        artifacts.read(artifact_id)
