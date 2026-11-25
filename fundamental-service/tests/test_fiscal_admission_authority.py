from __future__ import annotations

import base64
import asyncio
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import asyncpg
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError
from sqlalchemy import text

from fundamental_service.data_releases import ArtifactRefV1
from fundamental_service.fiscal_admission_authority import FiscalAuthorityOwner
from fundamental_service.fiscal_admission_history import (
    FiscalCommitReceiptV1,
    PostgresFiscalAdmissionHistory,
)
from fundamental_service.fiscal_authority_contracts import (
    CurrentFiscalAuthorityV1,
    FiscalAuthorityDeploymentV1,
    FiscalAuthorityIdentityV1,
    FiscalConfiguredAuthorityV1,
    FiscalConfiguredRegistryRootV1,
    FiscalGrantAuthorityCommandV1,
    FiscalRegistryExecutionV1,
    FiscalRegistryOperatorV1,
    FiscalRegistryRootIdentityV1,
    FiscalRevokeAuthorityCommandV1,
    HistoricalFiscalAuthorityExplanationV1,
    fiscal_authority_command_artifact_id,
    fiscal_authority_command_digest,
)
from fundamental_service.metadata import (
    PostgresArtifactStore,
    PostgresContentStore,
    PostgresMetadataStore,
)
from fundamental_service.replay import ArtifactRecordV1
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import SnapshotError
from test_fiscal_admission_history import _temporary_database


def deadline() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=20)


@pytest.fixture
def database_url() -> Iterator[str]:
    configured = os.getenv("FUNDAMENTAL_TEST_DATABASE_URL")
    if configured is None:
        pytest.skip("requires PostgreSQL authority storage")
    with _temporary_database(configured) as url:
        yield url


@pytest.fixture
def metadata(database_url: str) -> Iterator[PostgresMetadataStore]:
    store = PostgresMetadataStore(database_url, auto_migrate=True)
    try:
        store.start()
        yield store
    finally:
        store.close()


@pytest.fixture
def artifacts(metadata: PostgresMetadataStore, tmp_path: Path) -> PostgresArtifactStore:
    return PostgresArtifactStore(metadata, PostgresContentStore(tmp_path, metadata))


def reference(record: ArtifactRecordV1, role: str) -> ArtifactRefV1:
    return ArtifactRefV1(
        role=role,
        artifact_id=record.artifact_id,
        content_hash=record.content_hash,
        media_type=record.media_type,
    )


def public_key(key: Ed25519PrivateKey) -> str:
    return base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    ).decode()


class SyntheticRegistrySigner:
    def __init__(self, store, root, private_key):
        self.store = store
        self.root = root
        self.private_key = private_key
        self.sign_calls = 0
        self.on_sign: Callable[[], None] = lambda: None
        self.on_authenticate: Callable[
            [FiscalRegistryOperatorV1], FiscalRegistryOperatorV1
        ] = lambda value: value

    def authenticate(self, command, *, issuance, deadline_at):
        execution = FiscalRegistryExecutionV1(
            root_id=self.root.root_id,
            principal_id=self.root.principal_id,
            principal_kind=self.root.principal_kind,
            key_id=self.root.key_id,
            execution_id="synthetic-execution:" + uuid4().hex,
            operation=command.kind,
            command_digest=fiscal_authority_command_digest(command),
            issuance=issuance,
            started_at=datetime.now(UTC),
        )
        publication = self.store.put_with_receipt(execution.execution_id, execution)
        return self.on_authenticate(
            FiscalRegistryOperatorV1(
                root_id=self.root.root_id,
                principal_id=self.root.principal_id,
                principal_kind=self.root.principal_kind,
                key_id=self.root.key_id,
                execution_ref=reference(
                    publication.artifact, "fiscal-registry-execution-v1"
                ),
            )
        )

    def sign(self, message, *, operator, deadline_at):
        self.sign_calls += 1
        self.on_sign()
        return self.private_key.sign(message).hex()


@dataclass
class Environment:
    owner: FiscalAuthorityOwner
    signer: SyntheticRegistrySigner
    configuration: list[FiscalAuthorityDeploymentV1]
    store: PostgresArtifactStore
    history: PostgresFiscalAdmissionHistory
    metadata: PostgresMetadataStore


@pytest.fixture
def environment(metadata, artifacts):
    administrator = Ed25519PrivateKey.generate()
    business = Ed25519PrivateKey.generate()
    now = datetime.now(UTC)
    root = FiscalRegistryRootIdentityV1(
        root_id="synthetic-registry-root",
        principal_id="machine:synthetic-registry-administrator",
        principal_kind="machine",
        public_key_ed25519_base64=public_key(administrator),
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(days=2),
    )
    identity = FiscalAuthorityIdentityV1(
        authority_id="synthetic-classifier",
        principal_id="machine:synthetic-classifier",
        principal_kind="machine",
        public_key_ed25519_base64=public_key(business),
        role="classifier",
    )
    root_ref = reference(
        artifacts.put_with_receipt("synthetic-root-evidence", root).artifact,
        "fiscal-registry-root-v1",
    )
    provisioning = reference(
        artifacts.put_with_receipt(
            "synthetic-business-provisioning", identity
        ).artifact,
        "fiscal-authority-provisioning-v1",
    )
    configuration = [
        FiscalAuthorityDeploymentV1(
            roots=(
                FiscalConfiguredRegistryRootV1(identity=root, evidence_ref=root_ref),
            ),
            authorities=(
                FiscalConfiguredAuthorityV1(
                    identity=identity, provisioning_ref=provisioning
                ),
            ),
        )
    ]
    history = PostgresFiscalAdmissionHistory(metadata)
    signer = SyntheticRegistrySigner(artifacts, root, administrator)
    owner = FiscalAuthorityOwner(
        artifacts=artifacts,
        history=history,
        deployment=lambda: configuration[0],
        signer=signer,
    )
    return Environment(owner, signer, configuration, artifacts, history, metadata)


def grant_command(*, command_id="synthetic-grant", expires_at=None):
    return FiscalGrantAuthorityCommandV1(
        command_id=command_id,
        authority_id="synthetic-classifier",
        expires_at=expires_at or datetime.now(UTC) + timedelta(hours=1),
    )


def control_head(publication):
    return next(
        head for head in publication.history_heads if head.stream_kind == "control"
    )


def observed_authority_time(environment: Environment) -> datetime:
    return environment.history.read(
        ("control:fiscal-authority:synthetic-classifier",), deadline_at=deadline()
    ).observed_through


def revoke_command(publication, *, command_id="synthetic-revoke"):
    return FiscalRevokeAuthorityCommandV1(
        command_id=command_id,
        authority_id="synthetic-classifier",
        grant_ref=reference(
            publication.publication.artifact, "fiscal-authority-record-v1"
        ),
        reason="Synthetic fixture revocation",
    )


def change_status(environment, identity, status):
    async def change(connection):
        await connection.execute(
            text(
                "UPDATE fundamental.artifact_references SET status=:status WHERE artifact_id=:identity"
            ),
            {"identity": identity, "status": status},
        )

    environment.metadata.run_fiscal_admission_history(change)


def test_real_signed_grant_revoke_and_historical_explanation(environment):
    granted = environment.owner.grant(
        grant_command(), expected_head=None, deadline_at=deadline()
    )
    current = environment.owner.read_current(
        "synthetic-classifier", expected_role="classifier", deadline_at=deadline()
    )
    assert isinstance(current, CurrentFiscalAuthorityV1)
    assert current.grant.identity.principal_kind == "machine"
    assert granted.publication.wrote
    at = observed_authority_time(environment)
    revoked = environment.owner.revoke(
        revoke_command(granted),
        expected_head=control_head(granted),
        deadline_at=deadline(),
    )
    assert revoked.signed_record.record.kind == "revoke"
    with pytest.raises(SnapshotError) as refusal:
        environment.owner.read_current(
            "synthetic-classifier", expected_role="classifier", deadline_at=deadline()
        )
    assert refusal.value.code == "FISCAL_AUTHORITY_REFUSED"
    historical = environment.owner.replay_authority(
        "synthetic-classifier", at=at, deadline_at=deadline()
    )
    assert isinstance(historical, HistoricalFiscalAuthorityExplanationV1)
    assert historical.state == "active" and historical.revocation_ref is None
    assert historical.grant_ref == current.grant_ref
    with pytest.raises(ValidationError):
        CurrentFiscalAuthorityV1.model_validate(historical.model_dump())
    after = environment.owner.replay_authority(
        "synthetic-classifier",
        at=observed_authority_time(environment),
        deadline_at=deadline(),
    )
    assert after.state == "revoked" and after.revocation_ref is not None


def test_same_command_retry_keeps_signature_expiry_and_first_execution(environment):
    command = grant_command()
    first = environment.owner.grant(command, expected_head=None, deadline_at=deadline())
    repeated = environment.owner.grant(
        command, expected_head=None, deadline_at=deadline()
    )
    assert first.signed_record == repeated.signed_record
    assert first.publication.wrote and not repeated.publication.wrote
    assert environment.signer.sign_calls == 1
    assert repeated.signed_record.record.valid_until == command.expires_at
    revoke = revoke_command(first)
    first_revoke = environment.owner.revoke(
        revoke, expected_head=control_head(first), deadline_at=deadline()
    )
    retry_revoke = environment.owner.revoke(
        revoke, expected_head=control_head(first), deadline_at=deadline()
    )
    assert first_revoke.signed_record == retry_revoke.signed_record
    assert not retry_revoke.publication.wrote
    assert environment.signer.sign_calls == 2


def test_same_command_id_cannot_extend_grant_expiry(environment):
    command = grant_command()
    first = environment.owner.grant(command, expected_head=None, deadline_at=deadline())
    changed = command.model_copy(
        update={"expires_at": command.expires_at + timedelta(minutes=1)}
    )
    assert fiscal_authority_command_artifact_id(
        command
    ) == fiscal_authority_command_artifact_id(changed)
    with pytest.raises(SnapshotError) as failure:
        environment.owner.grant(
            changed, expected_head=control_head(first), deadline_at=deadline()
        )
    assert failure.value.code == "FISCAL_AUTHORITY_COMMAND_REUSED"
    assert environment.store.read(
        first.publication.artifact.artifact_id
    ) == canonical_bytes(first.signed_record)


@pytest.mark.parametrize(
    "field,value",
    [
        ("principal_id", "machine:untrusted"),
        ("root_id", "untrusted-root"),
        ("key_id", "e" * 64),
        ("principal_kind", "human"),
    ],
)
def test_operator_cannot_claim_another_root_or_identity(environment, field, value):
    environment.signer.on_authenticate = lambda issuer: issuer.model_copy(
        update={field: value}
    )
    with pytest.raises(SnapshotError) as failure:
        environment.owner.grant(
            grant_command(), expected_head=None, deadline_at=deadline()
        )
    assert failure.value.code == "FISCAL_AUTHORITY_REFUSED"
    assert environment.signer.sign_calls == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("principal_id", "machine:caller"),
        ("public_key_ed25519_base64", "AAAA"),
        ("role", "release_approver"),
        ("valid_from", "2020-01-01T00:00:00Z"),
    ],
)
def test_grant_request_cannot_install_identity_or_backdate_it(field, value):
    payload = grant_command().model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError):
        FiscalGrantAuthorityCommandV1.model_validate(payload)


def test_machine_identity_cannot_be_labeled_human():
    with pytest.raises(ValidationError):
        FiscalAuthorityIdentityV1(
            authority_id="synthetic-human",
            principal_id="machine:synthetic",
            principal_kind="human",
            public_key_ed25519_base64=public_key(Ed25519PrivateKey.generate()),
            role="classifier",
        )


@pytest.mark.parametrize("share", ["principal", "key", "both"])
def test_distinct_business_roles_require_independent_principals_and_keys(
    environment, share
):
    existing = environment.configuration[0].authorities[0]
    identity = existing.identity.model_copy(
        update={
            "authority_id": "synthetic-approver",
            "principal_id": existing.identity.principal_id
            if share in {"principal", "both"}
            else "machine:synthetic-approver",
            "public_key_ed25519_base64": existing.identity.public_key_ed25519_base64
            if share in {"key", "both"}
            else public_key(Ed25519PrivateKey.generate()),
            "role": "release_approver",
        }
    )
    other = existing.model_copy(update={"identity": identity})
    with pytest.raises(ValidationError):
        FiscalAuthorityDeploymentV1(
            roots=environment.configuration[0].roots, authorities=(existing, other)
        )


@pytest.mark.parametrize("seconds", [-1, 3 * 24 * 3600])
def test_grant_rejects_expired_or_root_exceeding_window(environment, seconds):
    command = grant_command(expires_at=datetime.now(UTC) + timedelta(seconds=seconds))
    with pytest.raises(SnapshotError):
        environment.owner.grant(command, expected_head=None, deadline_at=deadline())
    assert environment.signer.sign_calls == 0


def test_unconfigured_history_or_signer_cannot_issue_a_grant(environment):
    for missing in ("history", "signer"):
        owner = FiscalAuthorityOwner(
            artifacts=environment.store,
            history=None if missing == "history" else environment.history,
            signer=None if missing == "signer" else environment.signer,
            deployment=lambda: environment.configuration[0],
        )
        with pytest.raises(SnapshotError):
            owner.grant(grant_command(), expected_head=None, deadline_at=deadline())
    assert environment.signer.sign_calls == 0


def test_signature_must_be_from_the_configured_registry_key(environment):
    environment.signer.private_key = Ed25519PrivateKey.generate()
    command = grant_command()
    with pytest.raises(SnapshotError) as failure:
        environment.owner.grant(command, expected_head=None, deadline_at=deadline())
    assert failure.value.code == "FISCAL_AUTHORITY_INVALID"
    with pytest.raises(SnapshotError) as absent:
        environment.store.get(fiscal_authority_command_artifact_id(command))
    assert absent.value.code == "ARTIFACT_NOT_FOUND"
    with pytest.raises(SnapshotError):
        environment.owner.read_current(
            "synthetic-classifier", expected_role="classifier", deadline_at=deadline()
        )


def test_replay_preserves_old_role_after_deployment_roster_changes(environment):
    publication = environment.owner.grant(
        grant_command(), expected_head=None, deadline_at=deadline()
    )
    at = observed_authority_time(environment)
    environment.configuration[0] = environment.configuration[0].model_copy(
        update={"authorities": ()}
    )
    with pytest.raises(SnapshotError):
        environment.owner.read_current(
            "synthetic-classifier", expected_role="classifier", deadline_at=deadline()
        )
    old = environment.owner.replay_authority(
        "synthetic-classifier", at=at, deadline_at=deadline()
    )
    assert old.state == "active"
    assert old.grant.identity.role == "classifier"
    assert old.grant_ref.artifact_id == publication.publication.artifact.artifact_id


def test_historical_evidence_uses_its_checkpoint_instead_of_current_status(environment):
    publication = environment.owner.grant(
        grant_command(), expected_head=None, deadline_at=deadline()
    )
    at = observed_authority_time(environment)
    change_status(
        environment, publication.publication.artifact.artifact_id, "invalidated"
    )
    environment.history.seal_pending(
        ("evidence:" + publication.publication.artifact.artifact_id,),
        deadline_at=deadline(),
    )
    with pytest.raises(SnapshotError):
        environment.owner.read_current(
            "synthetic-classifier", expected_role="classifier", deadline_at=deadline()
        )
    old = environment.owner.replay_authority(
        "synthetic-classifier", at=at, deadline_at=deadline()
    )
    assert old.state == "active"
    with pytest.raises(SnapshotError):
        environment.owner.replay_authority(
            "synthetic-classifier",
            at=observed_authority_time(environment),
            deadline_at=deadline(),
        )


def test_missing_historical_root_evidence_refuses_replay(environment):
    environment.owner.grant(grant_command(), expected_head=None, deadline_at=deadline())
    current = environment.configuration[0]
    original = current.roots[0]
    foreign = original.identity.model_copy(
        update={
            "root_id": "another-root",
            "principal_id": "machine:another-root",
            "public_key_ed25519_base64": public_key(Ed25519PrivateKey.generate()),
        }
    )
    environment.configuration[0] = current.model_copy(
        update={"roots": (original.model_copy(update={"identity": foreign}),)}
    )
    with pytest.raises(SnapshotError):
        environment.owner.replay_authority(
            "synthetic-classifier",
            at=observed_authority_time(environment),
            deadline_at=deadline(),
        )


def test_request_role_and_revoke_target_must_match_the_retained_grant(environment):
    publication = environment.owner.grant(
        grant_command(), expected_head=None, deadline_at=deadline()
    )
    with pytest.raises(SnapshotError):
        environment.owner.read_current(
            "synthetic-classifier",
            expected_role="release_approver",
            deadline_at=deadline(),
        )
    wrong = revoke_command(publication).model_copy(
        update={
            "grant_ref": reference(publication.publication.artifact, "another-role")
        }
    )
    with pytest.raises(SnapshotError):
        environment.owner.revoke(
            wrong, expected_head=control_head(publication), deadline_at=deadline()
        )


class HistoryHook:
    def __init__(self, actual, *, before=lambda: None, after=lambda: None):
        self.actual = actual
        self.before = before
        self.after = after

    def __getattr__(self, name):
        return getattr(self.actual, name)

    def require_heads(self, heads, *, deadline_at):
        self.before()
        self.actual.require_heads(heads, deadline_at=deadline_at)
        self.after()


def test_current_refuses_revocation_during_its_final_head_check(environment):
    publication = environment.owner.grant(
        grant_command(), expected_head=None, deadline_at=deadline()
    )

    def revoke():
        environment.owner.revoke(
            revoke_command(publication),
            expected_head=control_head(publication),
            deadline_at=deadline(),
        )

    reader = FiscalAuthorityOwner(
        artifacts=environment.store,
        history=HistoryHook(environment.history, before=revoke),
        deployment=lambda: environment.configuration[0],
    )
    with pytest.raises(SnapshotError) as failure:
        reader.read_current(
            "synthetic-classifier", expected_role="classifier", deadline_at=deadline()
        )
    assert failure.value.code == "FISCAL_HISTORY_HEAD_CHANGED"


def test_current_refuses_metadata_aba_even_when_the_final_record_is_valid(environment):
    publication = environment.owner.grant(
        grant_command(), expected_head=None, deadline_at=deadline()
    )

    def change():
        change_status(
            environment, publication.publication.artifact.artifact_id, "invalidated"
        )
        change_status(
            environment, publication.publication.artifact.artifact_id, "valid"
        )

    reader = FiscalAuthorityOwner(
        artifacts=environment.store,
        history=HistoryHook(environment.history, before=change),
        deployment=lambda: environment.configuration[0],
    )
    with pytest.raises(SnapshotError):
        reader.read_current(
            "synthetic-classifier", expected_role="classifier", deadline_at=deadline()
        )
    assert (
        environment.store.get(publication.publication.artifact.artifact_id).status
        == "valid"
    )


def test_current_refuses_configuration_change_after_final_head_check(environment):
    environment.owner.grant(grant_command(), expected_head=None, deadline_at=deadline())

    def change():
        environment.configuration[0] = environment.configuration[0].model_copy(
            update={"authorities": ()}
        )

    reader = FiscalAuthorityOwner(
        artifacts=environment.store,
        history=HistoryHook(environment.history, after=change),
        deployment=lambda: environment.configuration[0],
    )
    with pytest.raises(SnapshotError) as failure:
        reader.read_current(
            "synthetic-classifier", expected_role="classifier", deadline_at=deadline()
        )
    assert failure.value.code == "FISCAL_AUTHORITY_REFUSED"


def test_current_refuses_expiry_crossed_during_final_head_check(environment):
    expires = datetime.now(UTC) + timedelta(seconds=3)
    environment.owner.grant(
        grant_command(expires_at=expires), expected_head=None, deadline_at=deadline()
    )
    current_clock = [lambda: datetime.now(UTC)]

    def advance():
        current_clock[0] = lambda: expires + timedelta(microseconds=1)

    reader = FiscalAuthorityOwner(
        artifacts=environment.store,
        history=HistoryHook(environment.history, after=advance),
        deployment=lambda: environment.configuration[0],
        clock=lambda: current_clock[0](),
    )
    with pytest.raises(SnapshotError) as failure:
        reader.read_current(
            "synthetic-classifier", expected_role="classifier", deadline_at=deadline()
        )
    assert failure.value.code == "FISCAL_AUTHORITY_REFUSED"


def test_orphan_publication_retries_without_signing_again(environment, monkeypatch):
    command = grant_command()
    original = environment.history.checkpoint

    def crash(*args, **kwargs):
        raise SnapshotError(
            "REQUEST_DEADLINE_EXCEEDED", "synthetic checkpoint interruption"
        )

    monkeypatch.setattr(environment.history, "checkpoint", crash)
    with pytest.raises(SnapshotError):
        environment.owner.grant(command, expected_head=None, deadline_at=deadline())
    raw = environment.store.read(fiscal_authority_command_artifact_id(command))
    monkeypatch.setattr(environment.history, "checkpoint", original)
    retried = environment.owner.grant(
        command, expected_head=None, deadline_at=deadline()
    )
    assert environment.signer.sign_calls == 1
    assert not retried.publication.wrote
    assert environment.store.read(retried.publication.artifact.artifact_id) == raw


def test_committed_but_unsealed_command_is_not_current_and_retry_recovers(
    environment, monkeypatch
):
    command = grant_command()
    original = environment.history.seal_pending

    def crash(streams, *, deadline_at):
        if any(stream.startswith("control:") for stream in streams):
            raise SnapshotError(
                "REQUEST_DEADLINE_EXCEEDED", "synthetic seal interruption"
            )
        return original(streams, deadline_at=deadline_at)

    monkeypatch.setattr(environment.history, "seal_pending", crash)
    with pytest.raises(SnapshotError):
        environment.owner.grant(command, expected_head=None, deadline_at=deadline())
    with pytest.raises(SnapshotError):
        environment.owner.read_current(
            "synthetic-classifier", expected_role="classifier", deadline_at=deadline()
        )
    monkeypatch.setattr(environment.history, "seal_pending", original)
    retried = environment.owner.grant(
        command, expected_head=None, deadline_at=deadline()
    )
    assert not retried.publication.wrote and environment.signer.sign_calls == 1
    assert control_head(retried).sequence == 1


def test_competing_first_grants_only_commit_one_authority(environment):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(2)
    environment.signer.on_sign = lambda: barrier.wait(timeout=8)
    commands = [grant_command(command_id="race-" + str(index)) for index in range(2)]

    def attempt(command):
        try:
            return environment.owner.grant(
                command, expected_head=None, deadline_at=deadline()
            )
        except SnapshotError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(attempt, commands))
    successes = [value for value in outcomes if not isinstance(value, SnapshotError)]
    failures = [value for value in outcomes if isinstance(value, SnapshotError)]
    assert len(successes) == len(failures) == 1
    assert failures[0].code == "FISCAL_HISTORY_HEAD_CHANGED"
    assert control_head(successes[0]).sequence == 1


def test_current_and_audit_reads_do_not_write_history(environment):
    environment.owner.grant(grant_command(), expected_head=None, deadline_at=deadline())

    async def counts(connection):
        return tuple(
            [
                await connection.scalar(
                    text("SELECT count(*) FROM fundamental." + table)
                )
                for table in ("fiscal_history_events", "fiscal_history_commit_receipts")
            ]
        )

    before = environment.metadata.run_fiscal_admission_history(counts)
    environment.owner.read_current(
        "synthetic-classifier", expected_role="classifier", deadline_at=deadline()
    )
    environment.owner.replay_authority(
        "synthetic-classifier",
        at=observed_authority_time(environment),
        deadline_at=deadline(),
    )
    assert environment.metadata.run_fiscal_admission_history(counts) == before


def test_source_revocation_while_signing_cannot_publish_authority(environment):
    def invalidate():
        change_status(environment, "synthetic-business-provisioning", "invalidated")

    environment.signer.on_sign = invalidate
    with pytest.raises(SnapshotError):
        environment.owner.grant(
            grant_command(), expected_head=None, deadline_at=deadline()
        )
    with pytest.raises(SnapshotError):
        environment.owner.read_current(
            "synthetic-classifier", expected_role="classifier", deadline_at=deadline()
        )


def test_grant_failure_after_publication_cannot_return_expired_authority(
    environment, monkeypatch
):
    expires = datetime.now(UTC) + timedelta(seconds=3)
    original = environment.store.put_bytes_with_receipt
    changed_clock = [False]

    def publish(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[0].startswith("fiscal-authority-command-v1:"):
            changed_clock[0] = True
        return result

    monkeypatch.setattr(environment.store, "put_bytes_with_receipt", publish)
    owner = FiscalAuthorityOwner(
        artifacts=environment.store,
        history=environment.history,
        deployment=lambda: environment.configuration[0],
        signer=environment.signer,
        clock=lambda: expires + timedelta(microseconds=1)
        if changed_clock[0]
        else datetime.now(UTC),
    )
    command = grant_command(expires_at=expires)
    with pytest.raises(SnapshotError) as failure:
        owner.grant(
            command,
            expected_head=None,
            deadline_at=deadline(),
        )
    assert failure.value.code == "FISCAL_AUTHORITY_REFUSED"
    assert (
        environment.store.get(fiscal_authority_command_artifact_id(command)).status
        == "valid"
    )
    with pytest.raises(SnapshotError):
        owner.read_current(
            "synthetic-classifier", expected_role="classifier", deadline_at=deadline()
        )


def test_replaying_old_grant_command_cannot_undo_a_later_revocation(environment):
    command = grant_command()
    granted = environment.owner.grant(
        command, expected_head=None, deadline_at=deadline()
    )
    revoked = environment.owner.revoke(
        revoke_command(granted),
        expected_head=control_head(granted),
        deadline_at=deadline(),
    )
    calls = environment.signer.sign_calls
    with pytest.raises(SnapshotError):
        environment.owner.grant(
            command, expected_head=control_head(revoked), deadline_at=deadline()
        )
    assert environment.signer.sign_calls == calls
    with pytest.raises(SnapshotError):
        environment.owner.read_current(
            "synthetic-classifier", expected_role="classifier", deadline_at=deadline()
        )


def test_new_grant_after_revocation_has_a_new_exact_reference(environment):
    first = environment.owner.grant(
        grant_command(), expected_head=None, deadline_at=deadline()
    )
    revoked = environment.owner.revoke(
        revoke_command(first), expected_head=control_head(first), deadline_at=deadline()
    )
    renewed = environment.owner.grant(
        grant_command(command_id="synthetic-renewal"),
        expected_head=control_head(revoked),
        deadline_at=deadline(),
    )
    current = environment.owner.read_current(
        "synthetic-classifier", expected_role="classifier", deadline_at=deadline()
    )
    assert current.grant_ref.artifact_id == renewed.publication.artifact.artifact_id
    assert current.grant_ref.artifact_id != first.publication.artifact.artifact_id
    assert control_head(renewed).sequence == 3
    with pytest.raises(SnapshotError):
        environment.owner.revoke(
            revoke_command(first, command_id="stale-revoke"),
            expected_head=control_head(renewed),
            deadline_at=deadline(),
        )


@pytest.mark.parametrize("boundary", ["commit", "visible"])
def test_authority_audit_refuses_commit_visibility_equality(environment, boundary):
    publication = environment.owner.grant(
        grant_command(), expected_head=None, deadline_at=deadline()
    )
    history = environment.history.read(
        (control_head(publication).stream_id,), deadline_at=deadline()
    )
    receipt = history.entries[0].commit_bound
    at = receipt.committed_at if boundary == "commit" else receipt.visible_by
    with pytest.raises(SnapshotError) as failure:
        environment.owner.replay_authority(
            "synthetic-classifier", at=at, deadline_at=deadline()
        )
    assert failure.value.code == "FISCAL_ADMISSION_HISTORY_UNAVAILABLE"
    assert "visibility_ambiguous" in failure.value.message


def test_authority_audit_cannot_claim_coverage_before_genesis_or_in_the_future(
    environment,
):
    command = grant_command()
    publication = environment.owner.grant(
        command, expected_head=None, deadline_at=deadline()
    )
    for at in (
        publication.signed_record.signed_at - timedelta(seconds=1),
        datetime.now(UTC) + timedelta(hours=1),
    ):
        with pytest.raises(SnapshotError) as failure:
            environment.owner.replay_authority(
                "synthetic-classifier", at=at, deadline_at=deadline()
            )
        assert failure.value.code == "FISCAL_ADMISSION_HISTORY_UNAVAILABLE"


def test_owner_enforces_original_deadline_after_signer_returns(environment):
    operation_deadline = deadline()
    late = [False]
    environment.signer.on_sign = lambda: late.__setitem__(0, True)
    owner = FiscalAuthorityOwner(
        artifacts=environment.store,
        history=environment.history,
        deployment=lambda: environment.configuration[0],
        signer=environment.signer,
        clock=lambda: operation_deadline + timedelta(microseconds=1)
        if late[0]
        else datetime.now(UTC),
    )
    command = grant_command()
    with pytest.raises(SnapshotError) as failure:
        owner.grant(command, expected_head=None, deadline_at=operation_deadline)
    assert failure.value.code == "REQUEST_DEADLINE_EXCEEDED"
    with pytest.raises(SnapshotError) as absent:
        environment.store.get(fiscal_authority_command_artifact_id(command))
    assert absent.value.code == "ARTIFACT_NOT_FOUND"


def test_expired_absolute_command_cannot_be_renewed_by_retry(environment):
    expiry = datetime.now(UTC) + timedelta(seconds=3)
    command = grant_command(expires_at=expiry)
    environment.owner.grant(command, expected_head=None, deadline_at=deadline())
    late_owner = FiscalAuthorityOwner(
        artifacts=environment.store,
        history=environment.history,
        deployment=lambda: environment.configuration[0],
        signer=environment.signer,
        clock=lambda: expiry + timedelta(microseconds=1),
    )
    with pytest.raises(SnapshotError):
        late_owner.grant(command, expected_head=None, deadline_at=deadline())
    assert environment.signer.sign_calls == 1


def test_corrupt_retained_bytes_are_rejected_even_with_unchanged_metadata(environment):
    environment.owner.grant(grant_command(), expected_head=None, deadline_at=deadline())

    class CorruptReader:
        def __getattr__(self, name):
            return getattr(environment.store, name)

        def read(self, identity):
            raw = environment.store.read(identity)
            return raw + b" " if identity == "synthetic-business-provisioning" else raw

    owner = FiscalAuthorityOwner(
        artifacts=CorruptReader(),
        history=environment.history,
        deployment=lambda: environment.configuration[0],
    )
    with pytest.raises(SnapshotError) as failure:
        owner.read_current(
            "synthetic-classifier", expected_role="classifier", deadline_at=deadline()
        )
    assert failure.value.code == "FISCAL_AUTHORITY_INVALID"


def test_original_deadline_cancels_a_real_registry_lock_and_retry_recovers(
    environment, database_url
):
    command = grant_command()

    async def blocked_operation():
        connection = await asyncpg.connect(database_url)
        try:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended('control:fiscal-authority:synthetic-classifier', 0))"
                )

                def invoke():
                    return environment.owner.grant(
                        command,
                        expected_head=None,
                        deadline_at=datetime.now(UTC) + timedelta(seconds=0.4),
                    )

                with pytest.raises(SnapshotError) as failure:
                    await asyncio.wait_for(asyncio.to_thread(invoke), timeout=3)
                assert failure.value.code == "REQUEST_DEADLINE_EXCEEDED"
        finally:
            await connection.close()

    asyncio.run(blocked_operation())
    stored = environment.store.read(fiscal_authority_command_artifact_id(command))
    restored = environment.owner.grant(
        command, expected_head=None, deadline_at=deadline()
    )
    assert not restored.publication.wrote
    assert environment.signer.sign_calls == 1
    assert environment.store.read(restored.publication.artifact.artifact_id) == stored
    assert control_head(restored).sequence == 1


@pytest.mark.parametrize("position", ["before_commit", "commit", "visible", "after"])
def test_current_observation_covers_later_evidence_visibility(environment, position):
    publication = environment.owner.grant(
        grant_command(), expected_head=None, deadline_at=deadline()
    )
    control = environment.history.read(
        ("control:fiscal-authority:synthetic-classifier",), deadline_at=deadline()
    )
    grant_bound = control.entries[-1].commit_bound
    assert isinstance(grant_bound, FiscalCommitReceiptV1)
    identity = publication.publication.artifact.artifact_id
    change_status(environment, identity, "invalidated")
    change_status(environment, identity, "valid")
    evidence = environment.history.seal_pending(
        ("evidence:" + identity,), deadline_at=deadline()
    )
    bound = evidence.entries[-1].commit_bound
    assert isinstance(bound, FiscalCommitReceiptV1)
    observed = {
        "before_commit": bound.committed_at - timedelta(microseconds=1),
        "commit": bound.committed_at,
        "visible": bound.visible_by,
        "after": bound.visible_by + timedelta(microseconds=1),
    }[position]
    assert observed > grant_bound.visible_by
    reader = FiscalAuthorityOwner(
        artifacts=environment.store,
        history=environment.history,
        deployment=lambda: environment.configuration[0],
        clock=lambda: observed,
    )
    if position == "after":
        current = reader.read_current(
            "synthetic-classifier", expected_role="classifier", deadline_at=deadline()
        )
        assert current.observed_at == observed
        assert current.grant_ref.artifact_id == identity
    else:
        with pytest.raises(SnapshotError, match="clock"):
            reader.read_current(
                "synthetic-classifier",
                expected_role="classifier",
                deadline_at=deadline(),
            )


def test_grant_success_refuses_clock_reversal_after_current_readback(
    environment, monkeypatch
):
    observed = [None]
    owner = FiscalAuthorityOwner(
        artifacts=environment.store,
        history=environment.history,
        deployment=lambda: environment.configuration[0],
        signer=environment.signer,
        clock=lambda: observed[0] or datetime.now(UTC),
    )
    read_current = owner.read_current

    def reverse_after_readback(*args, **kwargs):
        current = read_current(*args, **kwargs)
        control = environment.history.read(
            ("control:fiscal-authority:synthetic-classifier",), deadline_at=deadline()
        )
        bound = control.entries[-1].commit_bound
        assert isinstance(bound, FiscalCommitReceiptV1)
        observed[0] = bound.visible_by
        return current

    monkeypatch.setattr(owner, "read_current", reverse_after_readback)
    with pytest.raises(SnapshotError, match="clock"):
        owner.grant(grant_command(), expected_head=None, deadline_at=deadline())
    assert (
        environment.owner.read_current(
            "synthetic-classifier", expected_role="classifier", deadline_at=deadline()
        ).grant.identity.role
        == "classifier"
    )


def test_revoke_success_refuses_clock_reversal_at_final_head_check(
    environment, monkeypatch
):
    granted = environment.owner.grant(
        grant_command(), expected_head=None, deadline_at=deadline()
    )
    observed = [None]
    owner = FiscalAuthorityOwner(
        artifacts=environment.store,
        history=environment.history,
        deployment=lambda: environment.configuration[0],
        signer=environment.signer,
        clock=lambda: observed[0] or datetime.now(UTC),
    )
    require_heads = environment.history.require_heads

    def reverse_after_head_check(heads, *, deadline_at):
        require_heads(heads, deadline_at=deadline_at)
        control = environment.history.read(
            ("control:fiscal-authority:synthetic-classifier",),
            deadline_at=deadline_at,
        )
        bound = control.entries[-1].commit_bound
        assert isinstance(bound, FiscalCommitReceiptV1)
        observed[0] = bound.visible_by

    monkeypatch.setattr(environment.history, "require_heads", reverse_after_head_check)
    with pytest.raises(SnapshotError, match="clock"):
        owner.revoke(
            revoke_command(granted),
            expected_head=control_head(granted),
            deadline_at=deadline(),
        )
    with pytest.raises(SnapshotError) as refused:
        environment.owner.read_current(
            "synthetic-classifier", expected_role="classifier", deadline_at=deadline()
        )
    assert refused.value.code == "FISCAL_AUTHORITY_REFUSED"


def test_restored_authority_is_audit_only_until_fresh_local_revoke_and_grant(
    environment, database_url, tmp_path
):
    from fundamental_service.persistence_recovery import (
        export_backup,
        restore_backup,
        _verify_bundle,
    )
    from test_fiscal_history_recovery import target_pin

    env = environment
    original = env.owner.grant(
        grant_command(), expected_head=None, deadline_at=deadline()
    )
    source_read = env.history.read(
        ("control:fiscal-authority:synthetic-classifier",), deadline_at=deadline()
    )
    at = source_read.observed_through
    backups = tmp_path.parent / ("epoch-backups-" + uuid4().hex)
    exported = asyncio.run(
        export_backup(database_url, tmp_path, backups, source_revision="f" * 40)
    )
    bundle = backups / exported.manifest_digest
    manifest = _verify_bundle(bundle, exported.manifest_digest)
    with _temporary_database(os.environ["FUNDAMENTAL_TEST_DATABASE_URL"]) as target:
        target_root = tmp_path.parent / ("epoch-content-" + uuid4().hex)
        with target_pin(
            target, manifest, tmp_path.parent / ("epoch-pin-" + uuid4().hex)
        ) as pin:
            asyncio.run(
                restore_backup(
                    target,
                    target_root,
                    bundle,
                    manifest_digest=manifest.digest,
                    authorization_path=pin,
                )
            )
        current_metadata = PostgresMetadataStore(target)
        current_metadata.start()
        try:
            current_store = PostgresArtifactStore(
                current_metadata, PostgresContentStore(target_root, current_metadata)
            )
            current_history = PostgresFiscalAdmissionHistory(current_metadata)
            current_signer = SyntheticRegistrySigner(
                current_store, env.signer.root, env.signer.private_key
            )
            owner = FiscalAuthorityOwner(
                artifacts=current_store,
                history=current_history,
                deployment=lambda: env.configuration[0],
                signer=current_signer,
            )
            recovered = current_history.read(
                ("control:fiscal-authority:synthetic-classifier",),
                deadline_at=deadline(),
            )
            assert (
                recovered.entries[0].payload_bytes
                == source_read.entries[0].payload_bytes
            )
            assert (
                recovered.entries[0].commit_bound == source_read.entries[0].commit_bound
            )
            assert (
                owner.replay_authority(
                    "synthetic-classifier", at=at, deadline_at=deadline()
                ).state
                == "active"
            )
            with pytest.raises(SnapshotError, match="fresh|epoch|recovered"):
                owner.read_current(
                    "synthetic-classifier",
                    expected_role="classifier",
                    deadline_at=deadline(),
                )
            revoked = owner.revoke(
                revoke_command(original, command_id="local-revoke"),
                expected_head=recovered.heads[0],
                deadline_at=deadline(),
            )
            fresh = owner.grant(
                grant_command(command_id="local-grant"),
                expected_head=control_head(revoked),
                deadline_at=deadline(),
            )
            assert owner.read_current(
                "synthetic-classifier",
                expected_role="classifier",
                deadline_at=deadline(),
            ).grant_ref == reference(
                fresh.publication.artifact, "fiscal-authority-record-v1"
            )
        finally:
            current_metadata.close()
