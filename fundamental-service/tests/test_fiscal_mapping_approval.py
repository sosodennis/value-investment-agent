from __future__ import annotations

import base64
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fundamental_service.data_releases import (
    AutomaticMappingEvaluatorV1,
    DataReleaseError,
    DataReleaseTrustRootsV1,
    DataReleaseVerifierV1,
)
from fundamental_service.fiscal_statement_contracts import FiscalObservationV1
from fundamental_service.fiscal_statement_mapping import (
    FISCAL_MAPPING_EVALUATOR_ID,
    FiscalMappingApprovalOwner,
    FiscalStatementMappingBatchV1,
    fiscal_mapping_policy_digest,
)
from fundamental_service.fiscal_statement_registry import fiscal_statement_registry
from fundamental_service.metadata import (
    PostgresArtifactStore,
    PostgresContentStore,
    PostgresMetadataStore,
    metadata_operation_budget,
)
from fundamental_service.replay import ArtifactStore
from fundamental_service.snapshots import SnapshotError

from test_fiscal_projection_builder import _ref
from test_fiscal_statement_projection import _synthetic_input


def _deadline():
    return datetime.now(UTC) + timedelta(seconds=30)


def _synthetic_mapping(tmp_path, artifact_type=ArtifactStore):
    artifacts = artifact_type(tmp_path / "artifacts")
    source = _ref(
        artifacts.put_with_receipt(
            "synthetic-fixture-source", {"protocol": "synthetic-fixture-source"}
        ),
        "fiscal-original-validation",
    )
    raw = _synthetic_input().observations[0]
    observation = FiscalObservationV1.model_validate(
        {
            **raw.model_dump(mode="python"),
            "source_artifact_id": source.artifact_id,
            "source_binding_digest": source.content_hash,
        }
    )
    batch = FiscalStatementMappingBatchV1(
        source_validation_ref=source,
        source_binding_digest=source.content_hash,
        source_revision="0" * 40,
        validation_kind="complete_matched",
        primary_scope_digest="1" * 64,
        registry_digest=fiscal_statement_registry().digest,
        policy_digest=fiscal_mapping_policy_digest(),
        observations=(observation,),
        missing=(),
        disclosures=(),
    )
    reference = _ref(
        artifacts.put_with_receipt(
            batch.artifact_id,
            batch,
            (source.content_hash, batch.primary_scope_digest, batch.policy_digest),
        ),
        "fiscal-statement-mapping-v1",
    )
    key = Ed25519PrivateKey.generate()
    public = base64.b64encode(key.public_key().public_bytes_raw()).decode()
    evaluator = AutomaticMappingEvaluatorV1(
        public_key_ed25519_base64=public, policy_digest=batch.policy_digest
    )
    roots = DataReleaseTrustRootsV1(
        verifiers={
            "synthetic-fixture": DataReleaseVerifierV1(
                workflow_identity="synthetic-fixture",
                public_key_ed25519_base64=public,
                verification_suite_digest="0" * 64,
            )
        },
        automatic_mapping_evaluators={FISCAL_MAPPING_EVALUATOR_ID: evaluator},
    )
    owner = FiscalMappingApprovalOwner(
        artifacts=artifacts, trust_roots=lambda: roots, private_key=lambda: key
    )
    return artifacts, batch, reference, owner, roots


def test_machine_mapping_signature_replays_and_current_revocation_refuses(tmp_path):
    artifacts, batch, reference, owner, roots = _synthetic_mapping(tmp_path)
    approved = owner.approve(batch, reference, deadline_at=_deadline())
    again = owner.approve(batch, reference, deadline_at=_deadline())
    assert again == approved
    assert (
        owner.verify(batch, approved, deadline_at=_deadline()).mapping_digest
        == batch.digest
    )
    owner.trust_roots = lambda: roots.model_copy(
        update={
            "automatic_mapping_evaluators": {
                "another-synthetic-evaluator": roots.automatic_mapping_evaluators[
                    FISCAL_MAPPING_EVALUATOR_ID
                ]
            }
        }
    )
    with pytest.raises(DataReleaseError) as caught:
        owner.verify(batch, approved, deadline_at=_deadline())
    assert caught.value.code == "FISCAL_MAPPING_AUTHORITY_UNTRUSTED"
    assert artifacts.get(approved.artifact_id).status == "valid"


def test_mapping_signer_cannot_use_a_key_outside_deployment_authority(tmp_path):
    _, batch, reference, owner, _ = _synthetic_mapping(tmp_path)
    owner.private_key = Ed25519PrivateKey.generate
    with pytest.raises(SnapshotError):
        owner.approve(batch, reference, deadline_at=_deadline())


def test_mapping_reader_checks_signature_without_using_signing_key(tmp_path):
    _, batch, reference, owner, _ = _synthetic_mapping(tmp_path)
    approved = owner.approve(batch, reference, deadline_at=_deadline())

    def forbidden_key():
        raise AssertionError("read attempted to use the signing key")

    owner.private_key = forbidden_key
    assert (
        owner.verify(batch, approved, deadline_at=_deadline()).mapping_id
        == batch.artifact_id
    )


@pytest.mark.parametrize("naive", (False, True))
def test_mapping_deadline_refuses_before_signing(tmp_path, naive):
    _, batch, reference, owner, _ = _synthetic_mapping(tmp_path)
    deadline = datetime.now(UTC) - timedelta(seconds=1)
    if naive:
        deadline = deadline.replace(tzinfo=None)
    with pytest.raises(SnapshotError) as caught:
        owner.approve(batch, reference, deadline_at=deadline)
    assert caught.value.code == "REQUEST_DEADLINE_EXCEEDED"


def test_mapping_publication_crossing_deadline_cannot_return_success(tmp_path):
    class DeadlineStore(ArtifactStore):
        def after_approval(self):
            return None

        def put_with_receipt(self, artifact_id, *args, **kwargs):
            result = super().put_with_receipt(artifact_id, *args, **kwargs)
            if artifact_id.startswith("fiscal-mapping-approval-v1:"):
                self.after_approval()
            return result

    artifacts, batch, reference, owner, _ = _synthetic_mapping(tmp_path, DeadlineStore)
    start = datetime.now(UTC)
    deadline = start + timedelta(seconds=30)
    clock = [start]
    owner.clock = lambda: clock[0]
    artifacts.after_approval = lambda: clock.__setitem__(0, deadline)
    with pytest.raises(SnapshotError) as caught:
        owner.approve(batch, reference, deadline_at=deadline)
    assert caught.value.code == "REQUEST_DEADLINE_EXCEEDED"
    clock[0] = start
    artifacts.after_approval = lambda: None
    recovered = owner.approve(batch, reference, deadline_at=deadline)
    assert (
        owner.verify(batch, recovered, deadline_at=deadline).mapping_digest
        == batch.digest
    )


@pytest.fixture
def postgres_mapping(tmp_path, recovery_databases):
    url, _ = recovery_databases
    metadata = PostgresMetadataStore(url, auto_migrate=True)
    try:
        metadata.start()
        artifacts = PostgresArtifactStore(
            metadata, PostgresContentStore(tmp_path / "content", metadata)
        )
        yield url, _synthetic_mapping(tmp_path, artifact_type=lambda _: artifacts)
    finally:
        metadata.close()


@pytest.mark.parametrize("operation", ("approve", "verify"))
def test_mapping_deadline_cancels_a_locked_metadata_read_and_allows_retry(
    postgres_mapping, operation
):
    import asyncpg

    url, (artifacts, batch, reference, owner, _) = postgres_mapping
    approval = owner.approve(batch, reference, deadline_at=_deadline())
    acquired, release = Event(), Event()

    async def hold_lock():
        connection = await asyncpg.connect(url, command_timeout=5)
        try:
            async with connection.transaction():
                await connection.execute(
                    "LOCK TABLE fundamental.artifact_references IN ACCESS EXCLUSIVE MODE"
                )
                acquired.set()
                await asyncio.to_thread(release.wait, 3)
        finally:
            await connection.close()

    invoke = owner.approve if operation == "approve" else owner.verify
    operand = reference if operation == "approve" else approval
    with ThreadPoolExecutor(max_workers=2) as pool:
        lock = pool.submit(lambda: asyncio.run(hold_lock()))
        try:
            assert acquired.wait(2)
            deadline = datetime.now(UTC) + timedelta(milliseconds=150)
            request = pool.submit(invoke, batch, operand, deadline_at=deadline)
            with pytest.raises(SnapshotError) as caught:
                request.result(timeout=0.7)
            assert not release.is_set()
            assert caught.value.code == "REQUEST_DEADLINE_EXCEEDED"
        finally:
            release.set()
            lock.result(timeout=5)
    recovered = owner.approve(batch, reference, deadline_at=_deadline())
    assert recovered == approval
    assert (
        owner.verify(batch, approval, deadline_at=_deadline()).mapping_id
        == batch.artifact_id
    )
    assert artifacts.get(reference.artifact_id).status == "valid"


@pytest.mark.parametrize("fails", (False, True))
def test_mapping_operation_restores_the_parent_metadata_budget(postgres_mapping, fails):
    _, (artifacts, batch, reference, owner, _) = postgres_mapping
    remaining = [5.0]

    def parent_expired():
        return SnapshotError("SYNTHETIC_PARENT_DEADLINE", "parent deadline expired")

    with metadata_operation_budget(lambda: remaining[0], parent_expired):
        if fails:
            with pytest.raises(SnapshotError) as caught:
                owner.approve(
                    batch,
                    reference,
                    deadline_at=datetime.now(UTC) - timedelta(seconds=1),
                )
            assert caught.value.code == "REQUEST_DEADLINE_EXCEEDED"
        else:
            approval = owner.approve(batch, reference, deadline_at=_deadline())
            assert (
                owner.verify(batch, approval, deadline_at=_deadline()).mapping_id
                == batch.artifact_id
            )
        remaining[0] = 0
        with pytest.raises(SnapshotError) as caught:
            artifacts.get(reference.artifact_id)
        assert caught.value.code == "SYNTHETIC_PARENT_DEADLINE"
    assert artifacts.get(reference.artifact_id).status == "valid"
