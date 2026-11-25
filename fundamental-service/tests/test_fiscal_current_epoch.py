from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
import test_fiscal_admission_authority as authority_cases
import test_fiscal_source_classification as classification_cases

from fundamental_service.fiscal_admission_authority import FiscalAuthorityOwner
from fundamental_service.fiscal_admission_history import PostgresFiscalAdmissionHistory
from fundamental_service.fiscal_authority_contracts import (
    FiscalGrantAuthorityCommandV1,
    FiscalRevokeAuthorityCommandV1,
)
from fundamental_service.fiscal_classification_contracts import (
    FiscalSourcePreparationExecutionV1,
    SignedFiscalSourcePreparationExecutionV1,
)
from fundamental_service.fiscal_source_classification import (
    FiscalSourceClassificationOwner,
)
from fundamental_service.metadata import (
    PostgresArtifactStore,
    PostgresContentStore,
    PostgresMetadataStore,
)
from fundamental_service.persistence_recovery import (
    _verify_bundle,
    export_backup,
    restore_backup,
)
from fundamental_service.snapshots import SnapshotError
from test_fiscal_admission_authority import control_head, deadline, reference
from test_fiscal_admission_history import _temporary_database
from test_fiscal_history_recovery import target_pin


database_url = authority_cases.database_url
metadata = authority_cases.metadata
artifacts = authority_cases.artifacts
authority_environment = authority_cases.environment
classification_environment = classification_cases.environment


@contextmanager
def recovered(source_url, content_root, deployment, registry, tmp_path):
    directory = tmp_path.parent / ("current-epoch-" + uuid4().hex)
    directory.mkdir()
    exported = asyncio.run(
        export_backup(
            source_url, content_root, directory / "backups", source_revision="f" * 40
        )
    )
    bundle = directory / "backups" / exported.manifest_digest
    manifest = _verify_bundle(bundle, exported.manifest_digest)
    with _temporary_database(os.environ["FUNDAMENTAL_TEST_DATABASE_URL"]) as target:
        with target_pin(target, manifest, directory / "pin.json") as pin:
            receipt = asyncio.run(
                restore_backup(
                    target,
                    directory / "content",
                    bundle,
                    manifest_digest=manifest.digest,
                    authorization_path=pin,
                )
            )
        metadata = PostgresMetadataStore(target)
        metadata.start()
        try:
            store = PostgresArtifactStore(
                metadata, PostgresContentStore(directory / "content", metadata)
            )
            history = PostgresFiscalAdmissionHistory(metadata)
            signer = authority_cases.SyntheticRegistrySigner(
                store, registry.root, registry.private_key
            )
            authority = FiscalAuthorityOwner(
                artifacts=store,
                history=history,
                deployment=lambda: deployment,
                signer=signer,
            )
            yield SimpleNamespace(
                url=target,
                content=directory / "content",
                store=store,
                metadata=metadata,
                history=history,
                authorities=authority,
                registry=signer,
                receipt=receipt,
                manifest=manifest,
            )
        finally:
            metadata.close()


def regrant(target, prior):
    identity = prior.signed_record.record.identity
    head = target.history.read(
        ("control:fiscal-authority:" + identity.authority_id,), deadline_at=deadline()
    ).heads[0]
    revoked = target.authorities.revoke(
        FiscalRevokeAuthorityCommandV1(
            command_id="local-revoke-" + uuid4().hex,
            authority_id=identity.authority_id,
            grant_ref=reference(
                prior.publication.artifact, "fiscal-authority-record-v1"
            ),
            reason="Synthetic recovery revalidation",
        ),
        expected_head=head,
        deadline_at=deadline(),
    )
    return target.authorities.grant(
        FiscalGrantAuthorityCommandV1(
            command_id="local-grant-" + uuid4().hex,
            authority_id=identity.authority_id,
            expires_at=prior.signed_record.record.valid_until,
        ),
        expected_head=control_head(revoked),
        deadline_at=deadline(),
    )


def forbid_writes(*args, **kwargs):
    raise AssertionError("a pure current read must not publish or seal")


def test_bare_checkpoint_cannot_revive_imported_authority_and_multigeneration_keeps_audit(
    authority_environment, database_url, tmp_path, monkeypatch
):
    env = authority_environment
    first = env.owner.grant(
        authority_cases.grant_command(), expected_head=None, deadline_at=deadline()
    )
    at = datetime.now(UTC)
    stream = "control:fiscal-authority:synthetic-classifier"
    original = env.history.read((stream,), deadline_at=deadline())
    with recovered(
        database_url, tmp_path, env.configuration[0], env.signer, tmp_path
    ) as target:
        records = tuple(
            target.store.get(head.subject_id)
            for head in first.history_heads
            if head.stream_kind == "evidence"
        )
        observed = target.history.checkpoint(records, deadline_at=deadline())
        observed.require_current_epoch(
            tuple(
                {entry.event.subject_id: entry for entry in observed.entries}.values()
            )
        )
        with pytest.raises(SnapshotError, match="fresh local"):
            target.authorities.read_current(
                "synthetic-classifier",
                expected_role="classifier",
                deadline_at=deadline(),
            )
        fresh = regrant(target, first)
        before = target.history.read((stream,), deadline_at=deadline())
        with monkeypatch.context() as patch:
            for method in ("checkpoint", "seal_pending", "append_once"):
                patch.setattr(target.history, method, forbid_writes)
            patch.setattr(target.store, "put_bytes_with_receipt", forbid_writes)
            assert target.authorities.read_current(
                "synthetic-classifier",
                expected_role="classifier",
                deadline_at=deadline(),
            ).grant_ref == reference(
                fresh.publication.artifact, "fiscal-authority-record-v1"
            )
        after = target.history.read((stream,), deadline_at=deadline())
        assert after.entries == before.entries and after.heads == before.heads
        with recovered(
            target.url, target.content, env.configuration[0], target.registry, tmp_path
        ) as third:
            with pytest.raises(SnapshotError, match="fresh local"):
                third.authorities.read_current(
                    "synthetic-classifier",
                    expected_role="classifier",
                    deadline_at=deadline(),
                )
            history = third.history.read((stream,), deadline_at=deadline())
            assert len(history.epoch.cutovers) == 2
            assert history.entries[0].payload_bytes == original.entries[0].payload_bytes
            assert history.entries[0].commit_bound == original.entries[0].commit_bound
            assert (
                third.authorities.replay_authority(
                    "synthetic-classifier", at=at, deadline_at=deadline()
                ).state
                == "active"
            )
            for link in history.epoch.cutovers:
                with pytest.raises(
                    SnapshotError, match="recovery_gap|activation_visibility_ambiguous"
                ):
                    history.prefix_as_of(stream, at=link.activation.committed_at)


def test_prebackup_authority_orphan_cannot_gain_fresh_issuance_after_restore(
    authority_environment, database_url, tmp_path, monkeypatch
):
    env = authority_environment
    command = authority_cases.grant_command()
    with monkeypatch.context() as patch:
        patch.setattr(
            env.history,
            "append_once",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("synthetic pre-backup crash")
            ),
        )
        with pytest.raises(RuntimeError, match="pre-backup"):
            env.owner.grant(command, expected_head=None, deadline_at=deadline())
    artifact_id = authority_cases.fiscal_authority_command_artifact_id(command)
    original = env.store.read(artifact_id)
    with recovered(
        database_url, tmp_path, env.configuration[0], env.signer, tmp_path
    ) as target:
        with pytest.raises(SnapshotError) as failure:
            target.authorities.grant(
                command, expected_head=None, deadline_at=deadline()
            )
        assert failure.value.code == "FISCAL_AUTHORITY_REFUSED"
        assert target.registry.sign_calls == 0
        assert target.store.read(artifact_id) == original
        with pytest.raises(SnapshotError):
            target.history.read(
                ("control:fiscal-authority:synthetic-classifier",),
                deadline_at=deadline(),
            )


def fresh_classification(env, target, tmp_path, *, retained_source=False):
    grants = {role: regrant(target, grant) for role, grant in env.grants.items()}
    if retained_source:
        source, review = env.source, env.review
    else:
        source, review = classification_cases.synthetic_source(
            tmp_path / ("fresh-source-" + uuid4().hex), target.store, env.resolver.key
        )
    preparation = FiscalSourcePreparationExecutionV1(
        source_validation_ref=source.scope.source_validation_ref,
        source_binding_digest=source.scope.source_binding_digest,
        runtime=source.scope.runtime,
        authority_id="synthetic-source_preparer",
        authority_grant_ref=reference(
            grants["source_preparer"].publication.artifact, "fiscal-authority-record-v1"
        ),
        principal_id="machine:synthetic-source_preparer",
        principal_kind="machine",
        key_id=grants["source_preparer"].signed_record.record.identity.key_id,
        execution_id="fresh-preparation-" + uuid4().hex,
        issuance=target.history.read_epoch(deadline_at=deadline()).issuance_context,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    signed = SignedFiscalSourcePreparationExecutionV1(
        execution=preparation, signature="0" * 128
    )
    signed = signed.model_copy(
        update={"signature": env.preparer_key.sign(signed.signing_bytes()).hex()}
    )
    prep_ref = classification_cases.retained(
        target.store,
        preparation.execution_id,
        signed,
        "fiscal-source-preparation-execution-v1",
    )
    review_ref = classification_cases.retained(
        target.store,
        "fresh-review-" + uuid4().hex,
        review,
        "fiscal-source-accounting-review-v1",
    )
    command = env.command.model_copy(
        update={
            "command_id": "fresh-classification-" + uuid4().hex,
            "source_validation_ref": source.scope.source_validation_ref,
            "witness_ref": source.scope.witness_ref,
            "review_ref": review_ref,
            "preparer_execution_ref": prep_ref,
        }
    )
    signer = classification_cases.SyntheticClassifierSigner(
        target.store, env.signer.identity, env.signer.key
    )
    resolver = classification_cases.SyntheticSourceResolver(source, env.resolver.key)
    owner = FiscalSourceClassificationOwner(
        artifacts=target.store,
        history=target.history,
        authorities=target.authorities,
        sources=resolver,
        signer=signer,
    )
    return SimpleNamespace(
        command=command,
        source=source,
        signer=signer,
        resolver=resolver,
        owner=owner,
        grants=grants,
    )


@pytest.mark.parametrize("orphan", [False, True])
def test_recovered_classification_requires_fresh_grants_executions_and_command(
    classification_environment, tmp_path, monkeypatch, orphan
):
    env = classification_environment
    if orphan:
        with monkeypatch.context() as patch:
            patch.setattr(
                env.history,
                "append_once",
                lambda *args, **kwargs: (_ for _ in ()).throw(
                    RuntimeError("synthetic classification crash")
                ),
            )
            with pytest.raises(RuntimeError):
                env.owner.record_classification(
                    env.command, expected_head=None, deadline_at=deadline()
                )
        ref = reference(
            env.store.get(env.command.artifact_id), "fiscal-source-classification-v1"
        )
    else:
        _, ref = classification_cases.publish_classification(env)
    original = env.store.read(ref.artifact_id)
    deployment = env.authorities._deployment()
    with recovered(
        env.database_url,
        tmp_path / "pg-content",
        deployment,
        env.authorities._signer,
        tmp_path,
    ) as target:
        old_signer = classification_cases.SyntheticClassifierSigner(
            target.store, env.signer.identity, env.signer.key
        )
        old_resolver = classification_cases.SyntheticSourceResolver(
            env.source, env.resolver.key
        )
        old = FiscalSourceClassificationOwner(
            artifacts=target.store,
            history=target.history,
            authorities=target.authorities,
            sources=old_resolver,
            signer=old_signer,
        )
        with pytest.raises(SnapshotError):
            old.require_candidate_source(
                env.source.scope, (ref,), deadline_at=deadline()
            )
        target.history.checkpoint(
            tuple(
                target.store.get(head.subject_id)
                for head in env.history.read(
                    ("evidence:" + ref.artifact_id,), deadline_at=deadline()
                ).heads
            ),
            deadline_at=deadline(),
        )
        with pytest.raises(SnapshotError):
            old.require_candidate_source(
                env.source.scope, (ref,), deadline_at=deadline()
            )
        fresh = fresh_classification(env, target, tmp_path, retained_source=True)
        assert fresh.source.witness == env.source.witness
        assert fresh.source.witness.signed_at < target.receipt.activation.visible_by
        with pytest.raises(SnapshotError):
            old.record_classification(
                env.command, expected_head=None, deadline_at=deadline()
            )
        assert (
            old_signer.sign_calls == 0
            and target.store.read(ref.artifact_id) == original
        )
        result = fresh.owner.record_classification(
            fresh.command, expected_head=None, deadline_at=deadline()
        )
        fresh_ref = reference(
            result.publication.artifact, "fiscal-source-classification-v1"
        )
        with monkeypatch.context() as patch:
            for method in ("checkpoint", "append_once", "seal_pending"):
                patch.setattr(target.history, method, forbid_writes)
            patch.setattr(target.store, "put_bytes_with_receipt", forbid_writes)
            assert (
                fresh.owner.require_candidate_source(
                    fresh.source.scope, (fresh_ref,), deadline_at=deadline()
                ).source_use.scope
                == fresh.source.scope
            )
        assert target.store.read(ref.artifact_id) == original
        grant = fresh.grants["classifier"]
        target.authorities.revoke(
            FiscalRevokeAuthorityCommandV1(
                command_id="fresh-revoke-classifier",
                authority_id="synthetic-classifier",
                grant_ref=reference(
                    grant.publication.artifact, "fiscal-authority-record-v1"
                ),
                reason="Synthetic post-recovery revocation",
            ),
            expected_head=control_head(grant),
            deadline_at=deadline(),
        )
        with pytest.raises(SnapshotError):
            fresh.owner.require_candidate_source(
                fresh.source.scope, (fresh_ref,), deadline_at=deadline()
            )


def test_prebackup_future_claimed_authority_orphan_cannot_be_promoted(
    authority_environment, database_url, tmp_path, monkeypatch
):
    from datetime import timedelta
    from fundamental_service.fiscal_authority_contracts import FiscalRegistryExecutionV1

    env = authority_environment
    claimed_at = datetime.now(UTC) + timedelta(seconds=4)
    command = authority_cases.grant_command(command_id="future-claimed-orphan")

    def future_execution(issuer):
        execution = FiscalRegistryExecutionV1.model_validate_json(
            env.store.read(issuer.execution_ref.artifact_id)
        ).model_copy(update={"started_at": claimed_at})
        record = env.store.put_with_receipt(
            "synthetic-future-execution", execution
        ).artifact
        return issuer.model_copy(
            update={"execution_ref": reference(record, "fiscal-registry-execution-v1")}
        )

    env.signer.on_authenticate = future_execution
    future_owner = FiscalAuthorityOwner(
        artifacts=env.store,
        history=env.history,
        deployment=lambda: env.configuration[0],
        signer=env.signer,
        clock=lambda: claimed_at,
    )
    with monkeypatch.context() as patch:
        patch.setattr(
            env.history,
            "checkpoint",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("synthetic crash before checkpoint")
            ),
        )
        with pytest.raises(RuntimeError, match="before checkpoint"):
            future_owner.grant(command, expected_head=None, deadline_at=deadline())
    artifact_id = authority_cases.fiscal_authority_command_artifact_id(command)
    raw = env.store.read(artifact_id)
    with recovered(
        database_url, tmp_path, env.configuration[0], env.signer, tmp_path
    ) as target:
        assert target.manifest.history_frontier.covered_through < claimed_at
        assert target.receipt.activation.visible_by < claimed_at
        wait_seconds = (claimed_at - datetime.now(UTC)).total_seconds() + 0.03
        assert 0 < wait_seconds < 5
        asyncio.run(asyncio.sleep(wait_seconds))
        with pytest.raises(SnapshotError, match="fresh|recovered|issuance"):
            target.authorities.grant(
                command, expected_head=None, deadline_at=deadline()
            )
        assert target.store.read(artifact_id) == raw


def test_three_origins_preserve_classification_bytes_and_require_local_review(
    classification_environment, tmp_path
):
    env = classification_environment
    first, first_ref = classification_cases.publish_classification(env)
    first_raw = env.store.read(first_ref.artifact_id)
    deployment = env.authorities._deployment()
    with recovered(
        env.database_url,
        tmp_path / "pg-content",
        deployment,
        env.authorities._signer,
        tmp_path,
    ) as middle:
        second = fresh_classification(env, middle, tmp_path, retained_source=True)
        second_result = second.owner.record_classification(
            second.command, expected_head=None, deadline_at=deadline()
        )
        second_ref = reference(
            second_result.publication.artifact, "fiscal-source-classification-v1"
        )
        second_raw = middle.store.read(second_ref.artifact_id)
        with recovered(
            middle.url, middle.content, deployment, middle.registry, tmp_path
        ) as target:
            old_owner = FiscalSourceClassificationOwner(
                artifacts=target.store,
                history=target.history,
                authorities=target.authorities,
                sources=second.resolver,
            )
            for ref in (first_ref, second_ref):
                with pytest.raises(SnapshotError):
                    old_owner.require_candidate_source(
                        env.source.scope, (ref,), deadline_at=deadline()
                    )
            next_environment = SimpleNamespace(
                grants=second.grants,
                source=env.source,
                review=env.review,
                resolver=env.resolver,
                signer=env.signer,
                command=second.command,
                preparer_key=env.preparer_key,
            )
            fresh = fresh_classification(
                next_environment, target, tmp_path, retained_source=True
            )
            third = fresh.owner.record_classification(
                fresh.command, expected_head=None, deadline_at=deadline()
            )
            third_ref = reference(
                third.publication.artifact, "fiscal-source-classification-v1"
            )
            assert (
                fresh.owner.require_candidate_source(
                    env.source.scope, (third_ref,), deadline_at=deadline()
                ).source_use.scope
                == env.source.scope
            )
            assert len(target.history.read_epoch(deadline_at=deadline()).cutovers) == 2
            assert (
                first.signed_classification.issuance
                != second_result.signed_classification.issuance
            )
            assert (
                third.signed_classification.issuance
                != second_result.signed_classification.issuance
            )
            assert target.store.read(first_ref.artifact_id) == first_raw
            assert target.store.read(second_ref.artifact_id) == second_raw
            assert fresh.source.witness == env.source.witness


def test_execution_only_restore_requires_a_real_local_registry_invocation(
    authority_environment, database_url, tmp_path
):
    env = authority_environment
    command = authority_cases.grant_command(command_id="execution-only-crash")
    issuer = env.signer.authenticate(
        command,
        issuance=env.history.read_epoch(deadline_at=deadline()).issuance_context,
        deadline_at=deadline(),
    )
    original = env.store.read(issuer.execution_ref.artifact_id)
    with recovered(
        database_url, tmp_path, env.configuration[0], env.signer, tmp_path
    ) as target:
        target.registry.on_authenticate = lambda _local: issuer
        with pytest.raises(SnapshotError, match="execution"):
            target.authorities.grant(
                command, expected_head=None, deadline_at=deadline()
            )
        assert target.registry.sign_calls == 0
        assert target.store.read(issuer.execution_ref.artifact_id) == original
        target.registry.on_authenticate = lambda local: local
        fresh = target.authorities.grant(
            command, expected_head=None, deadline_at=deadline()
        )
        assert (
            fresh.signed_record.issuance
            == target.history.read_epoch(deadline_at=deadline()).issuance_context
        )
        assert target.authorities.read_current(
            "synthetic-classifier", expected_role="classifier", deadline_at=deadline()
        ).grant_ref == reference(
            fresh.publication.artifact, "fiscal-authority-record-v1"
        )
        assert target.store.read(issuer.execution_ref.artifact_id) == original


def test_reobservation_is_idempotent_preserves_ancestor_bytes_and_reexports(
    authority_environment, database_url, tmp_path
):
    from fundamental_service.fiscal_admission_history import (
        FiscalEvidenceReobservationV1,
    )

    env = authority_environment
    grant = env.owner.grant(
        authority_cases.grant_command(), expected_head=None, deadline_at=deadline()
    )
    artifact_id = grant.publication.artifact.artifact_id
    stream = "evidence:" + artifact_id
    original = env.history.read((stream,), deadline_at=deadline())
    with recovered(
        database_url, tmp_path, env.configuration[0], env.signer, tmp_path
    ) as target:
        record = target.store.get(artifact_id)
        observed = target.history.checkpoint((record,), deadline_at=deadline())
        assert len(observed.entries) == 2
        assert isinstance(
            observed.entries[-1].event.body, FiscalEvidenceReobservationV1
        )
        assert observed.entries[0] == original.entries[0]
        assert (
            target.history.checkpoint((record,), deadline_at=deadline()).entries
            == observed.entries
        )
        assert (
            observed.evidence_as_of(artifact_id, at=observed.observed_through) == record
        )
        with recovered(
            target.url, target.content, env.configuration[0], target.registry, tmp_path
        ) as third:
            third_record = third.store.get(artifact_id)
            final = third.history.checkpoint((third_record,), deadline_at=deadline())
            assert len(final.entries) == 3
            assert final.entries[:2] == observed.entries
            assert (
                final.entries[-1].event.body.recovery_operation_id
                == final.epoch.cutovers[-1].operation_id
            )
            assert (
                third.history.checkpoint(
                    (third_record,), deadline_at=deadline()
                ).entries
                == final.entries
            )


@pytest.mark.parametrize(
    "invalid",
    [
        "first",
        "absent_record",
        "changed_record",
        "same_origin",
        "wrong_operation",
        "no_cutover",
        "pending_activation",
        "recorded_equal_u",
        "commit_equal_u",
    ],
)
def test_reobservation_verifier_refuses_invalid_boundaries(
    authority_environment, database_url, tmp_path, invalid
):
    from fundamental_service.fiscal_admission_history import (
        verify_evidence_reobservation,
    )

    env = authority_environment
    grant = env.owner.grant(
        authority_cases.grant_command(), expected_head=None, deadline_at=deadline()
    )
    artifact_id = grant.publication.artifact.artifact_id
    with recovered(
        database_url, tmp_path, env.configuration[0], env.signer, tmp_path
    ) as target:
        record = target.store.get(artifact_id)
        observed = target.history.checkpoint((record,), deadline_at=deadline())
        previous, entry = observed.entries
        event, previous_event, previous_record = entry.event, previous.event, record
        epoch, committed_at = observed.epoch, entry.commit_bound.committed_at
        upper = epoch.cutovers[-1].activation.visible_by
        if invalid == "first":
            previous_event = None
        elif invalid == "absent_record":
            previous_record = None
        elif invalid == "changed_record":
            event = event.model_copy(
                update={
                    "body": event.body.model_copy(
                        update={
                            "record": record.model_copy(
                                update={"status": "invalidated"}
                            )
                        }
                    )
                }
            )
        elif invalid == "same_origin":
            previous_event = previous_event.model_copy(
                update={"origin_id": event.origin_id}
            )
        elif invalid == "wrong_operation":
            event = event.model_copy(
                update={
                    "body": event.body.model_copy(
                        update={"recovery_operation_id": "0" * 64}
                    )
                }
            )
        elif invalid == "no_cutover":
            epoch = epoch.model_copy(update={"cutovers": ()})
        elif invalid == "pending_activation":
            epoch = epoch.model_copy(
                update={
                    "cutovers": (
                        epoch.cutovers[-1].model_copy(update={"activation": None}),
                    )
                }
            )
        elif invalid == "recorded_equal_u":
            event = event.model_copy(update={"recorded_at": upper})
        else:
            committed_at = upper
        with pytest.raises(ValueError, match="reobservation"):
            verify_evidence_reobservation(
                event, previous_event, previous_record, epoch, committed_at
            )
