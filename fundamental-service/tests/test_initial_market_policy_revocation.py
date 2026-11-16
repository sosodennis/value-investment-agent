"""Unsafe bootstrap policies remain readable but must never be selected again."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fundamental_service.policies import (
    FilesystemPolicyRepository,
    MetadataPolicyRepository,
    PolicyError,
    PolicyRecordV1,
    PolicyRegistry,
    initial_model_specs,
    initial_policy_records,
)
from fundamental_service.metadata import PostgresMetadataStore
from fundamental_service.persistence_recovery import export_backup, restore_backup
from fundamental_service.serialization import sha256_digest


def revoked_seed_policies() -> tuple[PolicyRecordV1, ...]:
    first = PolicyRecordV1.model_validate_json(
        (
            Path(__file__).parent / "fixtures/revoked-initial-market-policy-v1.json"
        ).read_bytes()
    )
    payload = first.model_dump(exclude={"policy_digest"})
    payload.update(
        policy_id="transition_fcff_dcf-us-gaap-public-v2",
        policy_version="transition_fcff_dcf-v2-quality-v1",
        model_id="transition_fcff_dcf",
        model_version="transition_fcff_dcf-v2",
    )
    second = PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
    return first, second


def _select(registry: PolicyRegistry, policy: PolicyRecordV1, *, pinned: bool):
    return registry.select_policy(
        model_id=policy.model_id,
        model_version=policy.model_version,
        valuation_timestamp=datetime(2027, 1, 1, tzinfo=UTC),
        policy_id=policy.policy_id if pinned else None,
    )


@pytest.mark.parametrize("policy", revoked_seed_policies(), ids=lambda p: p.model_id)
def test_retained_unsafe_policy_cannot_be_used_by_explicit_pin(policy):
    registry = PolicyRegistry(initial_model_specs(), (policy,))
    assert registry.policy(policy.policy_id) == policy
    with pytest.raises(PolicyError) as error:
        _select(registry, policy, pinned=True)
    assert error.value.code == "POLICY_REVOKED"
    with pytest.raises(PolicyError) as error:
        _select(registry, policy, pinned=False)
    assert error.value.code == "POLICY_NOT_FOUND"


@pytest.mark.parametrize("reverse", (False, True))
def test_startup_and_restart_preserve_old_bytes_but_select_safe_seeds(
    tmp_path, reverse
):
    repository = FilesystemPolicyRepository(tmp_path)
    for policy in revoked_seed_policies():
        repository.publish(policy)
    old_bytes = {path.name: path.read_bytes() for path in tmp_path.glob("*.json")}
    seeds = initial_policy_records()
    registry = PolicyRegistry(
        initial_model_specs(),
        reversed(seeds) if reverse else seeds,
        repository=repository,
    )
    before = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in tmp_path.glob("*.json")
    }
    restarted = PolicyRegistry(initial_model_specs(), seeds, repository=repository)
    for policy in seeds:
        for current in (registry, restarted):
            selected = _select(current, policy, pinned=False)
            assert selected == policy
            assert selected.assumptions is None
            assert selected.market_inputs is None
    assert len(repository.list()) == 4
    assert before == {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in tmp_path.glob("*.json")
    }
    assert old_bytes == {name: (tmp_path / name).read_bytes() for name in old_bytes}


def test_postgres_backup_cannot_reenable_revoked_market_seeds(
    recovery_databases, tmp_path
):
    source_db, target_db = recovery_databases
    source = tmp_path / "source"
    source.mkdir()
    seeds = initial_policy_records()
    revoked = revoked_seed_policies()
    store = PostgresMetadataStore(source_db, auto_migrate=True)
    store.start()
    try:
        repository = MetadataPolicyRepository(store)
        for policy in revoked:
            repository.publish(policy)
        registry = PolicyRegistry(initial_model_specs(), seeds, repository=repository)
        for policy in seeds:
            assert _select(registry, policy, pinned=False) == policy
        assert {p.policy_id: p for p in repository.list()} == {
            p.policy_id: p for p in (*revoked, *seeds)
        }
    finally:
        store.close()
    backups = tmp_path / "backups"
    receipt = asyncio.run(
        export_backup(source_db, source, backups, source_revision="1" * 40)
    )
    assert receipt.wrote
    assert (
        asyncio.run(
            export_backup(source_db, source, backups, source_revision="1" * 40)
        ).wrote
        is False
    )
    bundle = backups / receipt.manifest_digest
    target = tmp_path / "restored"
    assert (
        asyncio.run(
            restore_backup(
                target_db, target, bundle, manifest_digest=receipt.manifest_digest
            )
        )
        == receipt
    )
    assert (
        asyncio.run(
            restore_backup(
                target_db, target, bundle, manifest_digest=receipt.manifest_digest
            )
        ).wrote
        is False
    )
    for database in (source_db, target_db):
        reopened = PostgresMetadataStore(database)
        reopened.start()
        try:
            repository = MetadataPolicyRepository(reopened)
            registry = PolicyRegistry(
                initial_model_specs(), seeds, repository=repository
            )
            for policy in revoked:
                assert registry.policy(policy.policy_id) == policy
                with pytest.raises(PolicyError) as error:
                    _select(registry, policy, pinned=True)
                assert error.value.code == "POLICY_REVOKED"
            for policy in seeds:
                assert _select(registry, policy, pinned=False) == policy
            assert {p.policy_id: p for p in repository.list()} == {
                p.policy_id: p for p in (*revoked, *seeds)
            }
        finally:
            reopened.close()
