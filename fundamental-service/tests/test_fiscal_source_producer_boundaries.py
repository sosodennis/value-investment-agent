from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from fundamental_service.fiscal_classification_contracts import (
    SignedFiscalSourceClassificationV2,
)
from fundamental_service.fiscal_source_producer_runtime import producer_reference
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
import test_fiscal_source_producer_runtime as producer_cases
from test_fiscal_admission_authority import change_status

environment = producer_cases.environment
protected_root = producer_cases.protected_root
preparer = producer_cases.preparer
sources = producer_cases.sources
retained_producer = producer_cases.retained_producer
deadline = producer_cases.deadline


@pytest.mark.parametrize("cut", ["unknown", "durable", "checkpoint", "append", "seal"])
def test_classifier_durable_cuts_preserve_exact_signature(
    retained_producer, monkeypatch, cut
):
    runtime, order, env, source, _ = retained_producer
    from fundamental_service.fiscal_admission_history import (
        PostgresFiscalAdmissionHistory,
    )

    tripped = []
    original_artifact = env.store.put_bytes_with_receipt
    original_method = None
    if cut in {"unknown", "durable"}:

        def crash(identity, *args, **kwargs):
            target = (
                identity.endswith(":classification:signed")
                if cut == "unknown"
                else identity.startswith("fiscal-source-classification-v2:")
            )
            if target and not tripped:
                tripped.append(identity)
                raise RuntimeError("classifier durable cut")
            return original_artifact(identity, *args, **kwargs)

        monkeypatch.setattr(env.store, "put_bytes_with_receipt", crash)
    else:
        method = {
            "checkpoint": "checkpoint",
            "append": "append_once",
            "seal": "seal_pending",
        }[cut]
        original_method = getattr(PostgresFiscalAdmissionHistory, method)

        def crash(self, *args, **kwargs):
            target = cut != "seal" or args[0][0].startswith(
                "control:fiscal-classification:"
            )
            if target and not tripped:
                tripped.append(cut)
                if cut == "append":
                    original_method(self, *args, **kwargs)
                raise RuntimeError("classifier durable cut")
            return original_method(self, *args, **kwargs)

        monkeypatch.setattr(PostgresFiscalAdmissionHistory, method, crash)
    with pytest.raises(RuntimeError, match="durable cut"):
        runtime.run(order.order_id, deadline_at=deadline())
    monkeypatch.setattr(env.store, "put_bytes_with_receipt", original_artifact)
    if original_method is not None:
        monkeypatch.setattr(PostgresFiscalAdmissionHistory, method, original_method)
    if cut == "unknown":
        with pytest.raises(SnapshotError) as unknown:
            runtime.run(order.order_id, deadline_at=deadline())
        assert (
            unknown.value.code == "FISCAL_SOURCE_PRODUCER_SIGNING_OUTCOME_UNAVAILABLE"
        )
        return
    work = sha256_digest(
        ("fiscal-source-producer", order.role, order.authority_id, order.order_id)
    )
    import json

    durable = json.loads(
        env.store.read(
            "fiscal-source-producer-job-v1:" + work + ":classification:signed"
        )
    )
    expected = SignedFiscalSourceClassificationV2.model_validate_json(
        canonical_bytes({**durable["body"], "signature": durable["signature"]})
    )
    recovered = runtime.run(order.order_id, deadline_at=deadline())
    assert recovered.signed_classification == expected
    assert env.store.read(
        recovered.publication.artifact.artifact_id
    ) == canonical_bytes(expected)
    assert recovered.signed_classification.review.scope == source.scope


def test_current_policy_source_and_nested_dependency_refusals(retained_producer):
    runtime, order, env, source, release = retained_producer
    from fundamental_service.fiscal_source_classification import (
        FiscalSourceClassificationOwner,
    )
    from fundamental_service.fiscal_source_preparation import (
        FiscalSourceProducerEvidenceVerifier,
    )
    from fundamental_service.fiscal_source_producer_runtime import (
        public_accounting_accreditation_provider,
    )
    from fundamental_service.fiscal_admission_history import (
        ReadOnlyFiscalAdmissionHistory,
    )
    import os

    first = runtime.run(order.order_id, deadline_at=deadline())
    ref = producer_reference(
        first.publication.artifact, "fiscal-source-classification-v2"
    )
    reader = FiscalSourceClassificationOwner(
        artifacts=env.store.as_read_only(),
        history=ReadOnlyFiscalAdmissionHistory(env.history),
        authorities=runtime.authorities,
        sources=runtime.classification_sources,
        producer_evidence=FiscalSourceProducerEvidenceVerifier(
            public_accounting_accreditation_provider(release, owner=os.getuid())
        ),
        require_production_evidence=True,
    )
    original = env.store.read(ref.artifact_id)
    dependencies = (
        source.scope.source_validation_ref,
        source.scope.witness_ref,
        source.scope.parser_action_refs[-1],
    )
    from fundamental_service.fiscal_source_producer_contracts import (
        FiscalClassifierReviewExecutionV2,
        FiscalAccountingAccreditationV1,
    )

    proof = FiscalClassifierReviewExecutionV2.model_validate_json(
        env.store.read(first.signed_classification.reviewer.execution_ref.artifact_id)
    )
    accreditation = FiscalAccountingAccreditationV1.model_validate_json(
        env.store.read(proof.accreditation_ref.artifact_id)
    )
    dependencies += (
        proof.invocation_ref,
        proof.accounting_basis_ref,
        proof.accreditation_ref,
        accreditation.independent_review_ref,
        order.preparation_ref,
    )
    for dependency in dependencies:
        before = env.store.get(dependency.artifact_id)
        change_status(env, dependency.artifact_id, "invalidated")
        with pytest.raises(SnapshotError):
            reader.require_candidate_source(
                source.scope, (ref,), deadline_at=deadline()
            )
        change_status(env, dependency.artifact_id, "valid")
        assert env.store.get(dependency.artifact_id) == before
    assert env.store.read(ref.artifact_id) == original
    assert hashlib.sha256(original).hexdigest() == ref.content_hash
    order_path = runtime.installation.orders_directory / (order.order_id + ".json")
    changed = order.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
    )
    order_path.write_bytes(canonical_bytes(changed))
    with pytest.raises(SnapshotError):
        runtime.run(order.order_id, deadline_at=deadline())


def test_source_preparation_lost_attempt_fences_signature(preparer, monkeypatch):
    runtime, order, env, source = preparer
    from fundamental_service.metadata import IngestionLockLease

    original = env.store.put_bytes_with_receipt

    def lose(identity, *args, **kwargs):
        result = original(identity, *args, **kwargs)
        if identity.endswith(":preparation-signature:signing"):
            leases = tuple(env.metadata._ingestion_lock_connections)
            assert len(leases) == 1
            token = leases[0]
            key, _ = env.metadata._ingestion_lock_connections[token]
            env.metadata.release_ingestion_lock(IngestionLockLease(token, key))
        return result

    monkeypatch.setattr(env.store, "put_bytes_with_receipt", lose)
    with pytest.raises(SnapshotError) as lost:
        runtime.run(order.order_id, deadline_at=deadline())
    assert lost.value.code == "INGESTION_LOCK_LOST"
    monkeypatch.setattr(env.store, "put_bytes_with_receipt", original)
    with pytest.raises(SnapshotError) as unknown:
        runtime.run(order.order_id, deadline_at=deadline())
    assert unknown.value.code == "FISCAL_SOURCE_PRODUCER_SIGNING_OUTCOME_UNAVAILABLE"
    assert source.calls == 1


@pytest.mark.parametrize(
    "unsafe", ["key-mode", "key-mismatch", "order-symlink", "parent-mode"]
)
def test_producer_protected_custody_refuses(preparer, unsafe):
    runtime, order, env, _ = preparer
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    path = runtime.installation.private_key_file
    if unsafe == "key-mode":
        path.chmod(0o644)
    elif unsafe == "key-mismatch":
        path.write_bytes(
            Ed25519PrivateKey.generate().private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    elif unsafe == "order-symlink":
        order_path = runtime.installation.orders_directory / (order.order_id + ".json")
        target = order_path.with_name("target.json")
        order_path.rename(target)
        order_path.symlink_to(target)
    else:
        runtime.installation.orders_directory.chmod(0o777)
    with pytest.raises(SnapshotError):
        runtime.run(order.order_id, deadline_at=deadline())
    work = sha256_digest(
        ("fiscal-source-producer", order.role, order.authority_id, order.order_id)
    )
    with pytest.raises(SnapshotError) as missing:
        env.store.get("fiscal-source-producer-job-v1:" + work + ":preparation")
    assert missing.value.code == "ARTIFACT_NOT_FOUND"


def test_producer_cli_has_only_refs_and_bounded_deadline(monkeypatch):
    from fundamental_service.fiscal_source_producer_runner import main
    import sys

    for arguments in (
        ["classifier", "one", "--deadline-seconds", "nan"],
        ["classifier", "one", "--deadline-seconds", "301"],
        ["classifier", "one", "--opinion", "approved"],
        ["classifier", "one", "--key", "anything"],
    ):
        monkeypatch.setattr(sys, "argv", ["fiscal-source-producer", *arguments])
        with pytest.raises(SystemExit) as rejected:
            main()
        assert rejected.value.code == 2


def test_two_processes_share_one_preparation_intent(preparer, protected_root):
    import json
    import subprocess
    import sys

    runtime, order, env, _ = preparer
    evidence, _ = runtime.sources.execute(order.source_request, deadline_at=deadline())
    source_file = protected_root / "source.json"
    source_file.write_bytes(canonical_bytes(evidence.model_dump(mode="json")))
    discovery_file = protected_root / "discovery.json"
    discovery_file.write_bytes(
        env.store.read(order.source_request.discovery_ref.artifact_id)
    )
    installation_file = protected_root / "installation.json"
    installation_file.write_bytes(
        canonical_bytes(runtime.installation.model_dump(mode="json"))
    )
    start = protected_root / "start"
    script = """
import sys, time
from pathlib import Path
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from fundamental_service.fiscal_source_producer_runtime import FiscalSourceProducerInstallationV1, FiscalSourceProducerRuntime
from fundamental_service.fiscal_source_closure import FiscalSourceClosure
from fundamental_service.fiscal_discovery import FiscalDiscoveryEvidenceV1
from fundamental_service.fiscal_validation_contracts import FiscalOriginalValidationEvidenceV1
from fundamental_service.metadata import PostgresMetadataStore, PostgresArtifactStore, PostgresContentStore
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import SnapshotError
from test_fiscal_source_producer_runtime import RetainedDiscoveryAdapter, RetainedSECAdapter
installed = FiscalSourceProducerInstallationV1.model_validate_json(Path(sys.argv[1]).read_bytes())
metadata = PostgresMetadataStore(sys.argv[2], auto_migrate=False)
try:
    metadata.start_read_only()
    artifacts = PostgresArtifactStore(metadata, PostgresContentStore(Path(sys.argv[3]), metadata))
    evidence = FiscalOriginalValidationEvidenceV1.model_validate_json(Path(sys.argv[4]).read_bytes())
    discovery = FiscalDiscoveryEvidenceV1.model_validate_json(Path(sys.argv[5]).read_bytes())
    discovery_adapter = RetainedDiscoveryAdapter(discovery, evidence, artifacts)
    closure = FiscalSourceClosure(discovery=discovery_adapter, artifacts=artifacts, pin=evidence.request.pin, source=RetainedSECAdapter(evidence), capture_lock=lambda key, at: nullcontext())
    runtime = FiscalSourceProducerRuntime(installation=installed, artifacts=artifacts, metadata=metadata, sources=closure, content=artifacts._content.as_read_only(), classification_sources=None)
    end = time.monotonic() + 30
    while not Path(sys.argv[6]).exists():
        if time.monotonic() >= end:
            raise RuntimeError("start barrier expired")
        time.sleep(0.01)
    try:
        result = runtime.run(sys.argv[7], deadline_at=datetime.now(UTC)+timedelta(seconds=60))
        print(canonical_bytes({"result": result}).decode())
    except SnapshotError as error:
        print(canonical_bytes({"error": error.code}).decode())
finally:
    metadata.close()
"""
    command = [
        sys.executable,
        "-c",
        script,
        str(installation_file),
        env.database_url,
        str(env.store._content._root),
        str(source_file),
        str(discovery_file),
        str(start),
        order.order_id,
    ]
    children = [
        subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        for _ in range(2)
    ]
    try:
        start.touch()
        results = []
        for child in children:
            output, error = child.communicate(timeout=80)
            assert child.returncode == 0, error
            results.append(json.loads(output))
        successes = [item["result"] for item in results if "result" in item]
        assert successes
        assert all(
            item.get("error") == "FISCAL_SOURCE_PRODUCER_IN_FLIGHT"
            for item in results
            if "error" in item
        )
        assert all(item == successes[0] for item in successes)
        final = runtime.run(order.order_id, deadline_at=deadline())
        assert final.model_dump(mode="json") == successes[0]
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)


def test_preparation_orphan_restore_refuses_old_epoch_and_fresh_job_succeeds(
    preparer, protected_root, tmp_path, monkeypatch
):
    import asyncio
    import os
    from contextlib import nullcontext
    from cryptography.hazmat.primitives import serialization
    from fundamental_service.persistence_recovery import (
        export_backup,
        restore_backup,
        _verify_bundle,
    )
    from fundamental_service.metadata import (
        PostgresMetadataStore,
        PostgresArtifactStore,
        PostgresContentStore,
    )
    from fundamental_service.fiscal_admission_history import (
        PostgresFiscalAdmissionHistory,
    )
    from fundamental_service.fiscal_registry_runtime import (
        FiscalRegistryInstallationV1,
        FiscalRegistryOrderV1,
        FiscalRegistryRuntime,
        fiscal_registry_executable_digest,
    )
    from fundamental_service.fiscal_authority_contracts import (
        FiscalGrantAuthorityCommandV1,
        FiscalRevokeAuthorityCommandV1,
    )
    from fundamental_service.fiscal_source_producer_runtime import (
        FiscalSourceProducerRuntime,
    )
    from fundamental_service.fiscal_source_closure import FiscalSourceClosure
    from fundamental_service.fiscal_discovery import FiscalDiscoveryEvidenceV1
    from test_fiscal_history_recovery import target_pin
    from test_fiscal_admission_history import _temporary_database

    runtime, order, env, _ = preparer
    registry_key = env.authorities._signer.private_key
    root_identity = env.authorities._configured().roots[0].identity
    original = env.store.put_bytes_with_receipt

    def crash(identity, *args, **kwargs):
        if identity.endswith(":preparation"):
            raise RuntimeError("orphan preparation in epoch A")
        return original(identity, *args, **kwargs)

    monkeypatch.setattr(env.store, "put_bytes_with_receipt", crash)
    with pytest.raises(RuntimeError, match="orphan preparation"):
        runtime.run(order.order_id, deadline_at=deadline())
    monkeypatch.setattr(env.store, "put_bytes_with_receipt", original)
    source = runtime.sources.read_with_metadata(
        runtime.sources.execute(order.source_request, deadline_at=deadline())[
            0
        ].artifact_id,
        deadline_at=deadline(),
    ).evidence
    discovery = FiscalDiscoveryEvidenceV1.model_validate_json(
        env.store.read(order.source_request.discovery_ref.artifact_id)
    )
    content_root = env.store._content._root
    env.metadata.close()
    receipt = asyncio.run(
        export_backup(
            env.database_url,
            content_root,
            tmp_path / "backups",
            source_revision="a" * 40,
        )
    )
    bundle = tmp_path / "backups" / receipt.manifest_digest
    manifest = _verify_bundle(bundle, receipt.manifest_digest)
    with _temporary_database(os.environ["FUNDAMENTAL_TEST_DATABASE_URL"]) as target:
        with target_pin(target, manifest, protected_root / "restore-pin.json") as pin:
            restored = asyncio.run(
                restore_backup(
                    target,
                    tmp_path / "target-content",
                    bundle,
                    manifest_digest=manifest.digest,
                    authorization_path=pin,
                )
            )
            assert restored.target_origin_id != order.issuance.origin_id
            metadata = PostgresMetadataStore(target, auto_migrate=False)
            try:
                metadata.start_read_only()
                store = PostgresArtifactStore(
                    metadata,
                    PostgresContentStore(tmp_path / "target-content", metadata),
                )
                history = PostgresFiscalAdmissionHistory(metadata)
                discovery_adapter = producer_cases.RetainedDiscoveryAdapter(
                    discovery, source, store
                )
                closure = FiscalSourceClosure(
                    discovery=discovery_adapter,
                    artifacts=store,
                    pin=source.request.pin,
                    source=producer_cases.RetainedSECAdapter(source),
                    capture_lock=lambda key, at: nullcontext(),
                )
                recovered_runtime = FiscalSourceProducerRuntime(
                    installation=runtime.installation,
                    artifacts=store,
                    metadata=metadata,
                    sources=closure,
                    content=store._content.as_read_only(),
                    classification_sources=None,
                )
                with pytest.raises(SnapshotError):
                    recovered_runtime.run(order.order_id, deadline_at=deadline())
                registry_private = protected_root / "registry-b.pem"
                registry_private.write_bytes(
                    registry_key.private_bytes(
                        serialization.Encoding.PEM,
                        serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption(),
                    )
                )
                registry_private.chmod(0o600)
                installed = FiscalRegistryInstallationV1(
                    audience="ephemeral-registry-b",
                    root_id=root_identity.root_id,
                    workload_uid=os.getuid(),
                    deployment_uid=os.getuid(),
                    database_role="fundamental",
                    deployment_file=runtime.installation.deployment_file,
                    orders_directory=runtime.installation.orders_directory,
                    private_key_file=registry_private,
                    executable_digest=fiscal_registry_executable_digest(),
                )
                epoch = history.read_epoch(deadline_at=deadline())
                old_head = history.read(
                    ("control:fiscal-authority:" + order.authority_id,),
                    deadline_at=deadline(),
                ).heads[0]
                now = datetime.now(UTC)
                grant_order = FiscalRegistryOrderV1(
                    order_id="fresh-grant-b",
                    audience=installed.audience,
                    root_id=installed.root_id,
                    deployment_digest=order.deployment_digest,
                    executable_digest=installed.executable_digest,
                    issuance=epoch.issuance_context,
                    command=FiscalGrantAuthorityCommandV1(
                        command_id="fresh-grant-b",
                        authority_id=order.authority_id,
                        expires_at=now + timedelta(hours=1),
                    ),
                    expected_head=old_head,
                    valid_from=now - timedelta(seconds=1),
                    valid_until=now + timedelta(minutes=10),
                )
                (installed.orders_directory / "fresh-grant-b.json").write_bytes(
                    canonical_bytes(grant_order)
                )
                registry = FiscalRegistryRuntime(
                    installation=installed, artifacts=store, metadata=metadata
                )
                old_grant_ref = producer_reference(
                    env.grants["source_preparer"].publication.artifact,
                    "fiscal-authority-record-v1",
                )
                revoke_order = grant_order.model_copy(
                    update={
                        "order_id": "revoke-old-a",
                        "command": FiscalRevokeAuthorityCommandV1(
                            command_id="revoke-old-a",
                            authority_id=order.authority_id,
                            grant_ref=old_grant_ref,
                            reason="replace restored grant with fresh local issuance",
                        ),
                    }
                )
                (installed.orders_directory / "revoke-old-a.json").write_bytes(
                    canonical_bytes(revoke_order)
                )
                revoked = registry.apply(revoke_order.order_id, deadline_at=deadline())
                fresh_head = next(
                    head
                    for head in revoked.history_heads
                    if head.stream_kind == "control"
                )
                grant_order = grant_order.model_copy(
                    update={"expected_head": fresh_head}
                )
                (installed.orders_directory / "fresh-grant-b.json").write_bytes(
                    canonical_bytes(grant_order)
                )
                registry.apply(grant_order.order_id, deadline_at=deadline())
                fresh = order.model_copy(
                    update={
                        "order_id": "fresh-prepare-b",
                        "issuance": epoch.issuance_context,
                        "valid_from": now,
                        "expires_at": now + timedelta(minutes=10),
                    }
                )
                (installed.orders_directory / "fresh-prepare-b.json").write_bytes(
                    canonical_bytes(fresh)
                )
                result = recovered_runtime.run(fresh.order_id, deadline_at=deadline())
                signed = producer_cases.read_source_preparation(
                    producer_cases.FiscalArtifactRead(store, lambda: 60), result
                )
                assert signed.preparation.execution.issuance == epoch.issuance_context
                epoch.require_current_activity(
                    signed.preparation.execution.started_at,
                    signed.preparation.execution.completed_at,
                )
            finally:
                metadata.close()


def test_archive_registration_is_part_of_last_current_snapshot(
    retained_producer, monkeypatch
):
    import os
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from fundamental_service.fiscal_source_classification import (
        FiscalSourceClassificationOwner,
    )
    from fundamental_service.fiscal_source_preparation import (
        FiscalSourceProducerEvidenceVerifier,
    )
    from fundamental_service.fiscal_source_producer_runtime import (
        public_accounting_accreditation_provider,
    )
    from fundamental_service.fiscal_admission_history import (
        ReadOnlyFiscalAdmissionHistory,
    )

    runtime, order, env, source, release = retained_producer
    publication = runtime.run(order.order_id, deadline_at=deadline())
    ref = producer_reference(
        publication.publication.artifact, "fiscal-source-classification-v2"
    )
    reader = FiscalSourceClassificationOwner(
        artifacts=env.store.as_read_only(),
        history=ReadOnlyFiscalAdmissionHistory(runtime.history),
        authorities=runtime.authorities,
        sources=runtime.classification_sources,
        producer_evidence=FiscalSourceProducerEvidenceVerifier(
            public_accounting_accreditation_provider(release, owner=os.getuid())
        ),
        require_production_evidence=True,
    )
    original = runtime.history.finish_observation
    calls, removed, protected = [], [], []

    def remove_before_last_snapshot(*args, **kwargs):
        calls.append(True)
        if len(calls) == 2:

            async def remove(connection):
                await connection.execute(
                    text(
                        "DELETE FROM fundamental.content_objects WHERE content_hash=:digest"
                    ),
                    {"digest": source.evidence.outcome.integrity.archive_hash},
                )

            try:
                env.metadata.run_fiscal_admission_history(remove)
            except DBAPIError:
                protected.append(True)
            else:
                removed.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(
        runtime.history, "finish_observation", remove_before_last_snapshot
    )
    try:
        result = reader.require_candidate_source(
            source.scope, (ref,), deadline_at=deadline()
        )
    except SnapshotError as error:
        assert removed and not protected
        assert error.code == "FISCAL_ADMISSION_HISTORY_UNAVAILABLE"
    else:
        assert protected and not removed
        assert result.source_use.scope == source.scope
    assert len(calls) == 2
