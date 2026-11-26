from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import test_fiscal_source_classification as classification_cases
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fundamental_service.fiscal_authority_contracts import (
    FiscalAuthorityIdentityV1,
    FiscalConfiguredAuthorityV1,
    FiscalGrantAuthorityCommandV1,
    FiscalRevokeAuthorityCommandV1,
)
from fundamental_service.fiscal_candidate_contracts import (
    FiscalPrepareCandidateCommandV1,
)
from fundamental_service.fiscal_display_admission import (
    fiscal_display_executable_digest,
)
from fundamental_service.fiscal_display_contracts import FiscalDisplayRequestV1
from fundamental_service.fiscal_display_runtime import (
    FiscalDisplayInstallationV1,
    FiscalDisplayOrderV1,
    FiscalDisplayRuntime,
    build_fiscal_display_reader,
)
from fundamental_service.fiscal_preparation_runtime import (
    FiscalPreparationDeploymentV1,
    FiscalPreparationInputs,
    build_fiscal_candidate_runtime,
)
from fundamental_service.fiscal_registry_runtime import (
    FiscalRegistryInstallationV1,
    FiscalRegistryOrderV1,
    FiscalRegistryRuntime,
    fiscal_registry_executable_digest,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from test_fiscal_admission_authority import public_key, reference
from test_fiscal_candidate_preparation import key_file
from test_fiscal_projection_builder import _case, assert_frozen_candidate_projection

environment = classification_cases.environment


def deadline():
    return datetime.now(UTC) + timedelta(seconds=60)


@dataclass
class DisplayEnvironment:
    env: object
    runtime: FiscalDisplayRuntime
    order: FiscalDisplayOrderV1
    candidate: object
    inputs: FiscalPreparationInputs
    candidate_config: FiscalPreparationDeploymentV1
    candidate_builder: object
    registry: FiscalRegistryRuntime
    registry_order: FiscalRegistryOrderV1

    def write(self, order):
        target = self.runtime.installation.orders_directory / (order.order_id + ".json")
        target.write_bytes(canonical_bytes(order))
        target.chmod(0o600)


@pytest.fixture
def protected_deployment_root():
    with TemporaryDirectory(prefix=".issue495-display-", dir=Path.home()) as directory:
        root = Path(directory)
        root.chmod(0o700)
        yield root


@pytest.fixture
def display(environment, tmp_path, protected_deployment_root):
    env = environment
    source_builder, discovery_ref, _, _, _ = _case(
        tmp_path / "synthetic-retained-source",
        "aapl-historical",
        artifact_type=lambda _: env.store,
    )
    configuration = env.authorities._configured()
    display_key = Ed25519PrivateKey.generate()
    identity = FiscalAuthorityIdentityV1(
        authority_id="ephemeral-display",
        principal_id="machine:ephemeral-display",
        principal_kind="machine",
        role="release_approver",
        public_key_ed25519_base64=public_key(display_key),
    )
    provisioning = reference(
        env.store.put_with_receipt("ephemeral-display-provisioning", identity).artifact,
        "fiscal-authority-provisioning-v1",
    )
    configuration = configuration.model_copy(
        update={
            "authorities": (
                *configuration.authorities,
                FiscalConfiguredAuthorityV1(
                    identity=identity, provisioning_ref=provisioning
                ),
            )
        }
    )
    roster = protected_deployment_root / "roster.json"
    roster.write_bytes(canonical_bytes(configuration))
    roster.chmod(0o600)
    registry_orders = protected_deployment_root / "registry-orders"
    registry_orders.mkdir(mode=0o700)
    root = configuration.roots[0].identity
    registry = FiscalRegistryRuntime(
        installation=FiscalRegistryInstallationV1(
            audience="ephemeral-display-registry",
            root_id=root.root_id,
            workload_uid=os.getuid(),
            deployment_uid=os.getuid(),
            database_role="fundamental",
            deployment_file=roster,
            orders_directory=registry_orders,
            private_key_file=key_file(
                protected_deployment_root / "registry.pem",
                env.authorities._signer.private_key,
            ),
            executable_digest=fiscal_registry_executable_digest(),
        ),
        artifacts=env.store,
        metadata=env.metadata,
    )
    now = datetime.now(UTC)
    order = FiscalRegistryOrderV1(
        order_id="display-grant",
        audience=registry._installation.audience,
        root_id=root.root_id,
        deployment_digest=sha256_digest(configuration),
        executable_digest=fiscal_registry_executable_digest(),
        issuance=env.history.read_epoch(deadline_at=deadline()).issuance_context,
        command=FiscalGrantAuthorityCommandV1(
            command_id="grant-display",
            authority_id=identity.authority_id,
            expires_at=now + timedelta(hours=1),
        ),
        expected_head=None,
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(minutes=30),
    )
    (registry_orders / "display-grant.json").write_bytes(canonical_bytes(order))
    registry.apply("display-grant", deadline_at=deadline())
    previous = env.authorities.read_current(
        "synthetic-source_preparer",
        expected_role="source_preparer",
        deadline_at=deadline(),
    )
    revoke_preparer = order.model_copy(
        update={
            "order_id": "candidate-revoke",
            "command": FiscalRevokeAuthorityCommandV1(
                command_id="revoke-synthetic-candidate-grant",
                authority_id="synthetic-source_preparer",
                grant_ref=previous.grant_ref,
                reason="replace fixture grant through production registry",
            ),
            "expected_head": next(
                head for head in previous.history_heads if head.stream_kind == "control"
            ),
        }
    )
    (registry_orders / "candidate-revoke.json").write_bytes(
        canonical_bytes(revoke_preparer)
    )
    registry.apply("candidate-revoke", deadline_at=deadline())
    revoked_head = env.history.read(
        ("control:fiscal-authority:synthetic-source_preparer",), deadline_at=deadline()
    ).heads[0]
    preparer_order = order.model_copy(
        update={
            "order_id": "candidate-grant",
            "command": FiscalGrantAuthorityCommandV1(
                command_id="production-candidate-grant",
                authority_id="synthetic-source_preparer",
                expires_at=now + timedelta(hours=1),
            ),
            "expected_head": revoked_head,
        }
    )
    (registry_orders / "candidate-grant.json").write_bytes(
        canonical_bytes(preparer_order)
    )
    registry.apply("candidate-grant", deadline_at=deadline())
    trust = protected_deployment_root / "mapping.json"
    trust.write_bytes(canonical_bytes(source_builder.mapping_approvals.trust_roots()))
    config = FiscalPreparationDeploymentV1(
        authority_deployment_file=roster,
        candidate_authority_id="synthetic-source_preparer",
        mapping_trust_roots_file=trust,
        candidate_private_key_file=key_file(
            protected_deployment_root / "candidate.pem", env.preparer_key
        ),
        mapping_private_key_file=key_file(
            protected_deployment_root / "mapping.pem",
            source_builder.mapping_approvals.private_key(),
        ),
    )
    inputs = FiscalPreparationInputs(
        env.store,
        source_builder.content,
        source_builder.discovery,
        source_builder.sources,
        source_builder.pin,
        None,
    )
    builder = build_fiscal_candidate_runtime(inputs, env.metadata, config, write=True)
    candidate = builder.prepare(
        FiscalPrepareCandidateCommandV1(
            command_id="display-test-candidate",
            discovery_ref=discovery_ref,
            security_id="AAPL",
            expires_at=now + timedelta(minutes=20),
        ),
        deadline_at=deadline(),
    )
    readonly_builder = build_fiscal_candidate_runtime(
        inputs,
        env.metadata,
        config.model_copy(
            update={
                "candidate_private_key_file": None,
                "mapping_private_key_file": None,
            }
        ),
        write=False,
    )
    orders = protected_deployment_root / "display-orders"
    orders.mkdir(mode=0o700)
    installation = FiscalDisplayInstallationV1(
        audience="ephemeral-display",
        authority_id=identity.authority_id,
        workload_uid=os.getuid(),
        deployment_uid=os.getuid(),
        database_role="fundamental",
        deployment_file=roster,
        orders_directory=orders,
        private_key_file=key_file(
            protected_deployment_root / "display.pem", display_key
        ),
        executable_digest=fiscal_display_executable_digest(),
        declared_source_revision=source_builder.pin.declared_source_revision,
        candidate_authority_id=config.candidate_authority_id,
        mapping_trust_roots_file=trust,
        mapping_trust_roots_sha256=hashlib.sha256(trust.read_bytes()).hexdigest(),
    )
    runtime = FiscalDisplayRuntime(
        installation=installation,
        candidates=readonly_builder,
        artifacts=env.store,
        metadata=env.metadata,
    )
    request = FiscalDisplayRequestV1(
        command_id="display-one",
        authority_id=identity.authority_id,
        candidate_ref=candidate.reference,
        expires_at=now + timedelta(minutes=10),
    )
    display_order = FiscalDisplayOrderV1(
        order_id="display-one",
        audience=installation.audience,
        deployment_digest=sha256_digest(configuration),
        executable_digest=fiscal_display_executable_digest(),
        issuance=order.issuance,
        request=request,
        expected_head=None,
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(minutes=15),
    )
    result = DisplayEnvironment(
        env, runtime, display_order, candidate, inputs, config, builder, registry, order
    )
    result.write(display_order)
    return result


def test_actual_registry_candidate_display_current_retry_and_revoke(display):
    first = display.runtime.apply(display.order.order_id, deadline_at=deadline())
    assert first.publication.wrote
    assert_frozen_candidate_projection(first.candidate, "aapl-historical")
    assert first.decision.body.review.execution.principal_kind == "machine"
    assert (
        first.decision.body.review.execution.key_id
        != first.candidate.preparation.key_id
    )
    again = display.runtime.apply(display.order.order_id, deadline_at=deadline())
    assert not again.publication.wrote
    assert canonical_bytes(again.decision) == canonical_bytes(first.decision)
    reader = build_fiscal_display_reader(
        candidates=display.runtime.candidates,
        deployment_file=display.runtime.installation.deployment_file,
        deployment_uid=os.getuid(),
        mapping_trust_roots_file=display.candidate_config.mapping_trust_roots_file,
        artifacts=display.env.store,
        metadata=display.env.metadata,
    )
    loaded = reader.read_current(
        first.reference, first.candidate.reference, deadline_at=deadline()
    )
    assert loaded.reference == first.reference
    authority_for_signature = reader.authorities.read_current(
        display.order.request.authority_id,
        expected_role="release_approver",
        deadline_at=deadline(),
    )
    with pytest.raises(SnapshotError, match="signature"):
        reader._verify(
            first.decision.model_copy(update={"signature": "0" * 128}),
            first.candidate,
            authority_for_signature,
            deadline(),
        )
    authority = reader.authorities.read_current(
        display.order.request.authority_id,
        expected_role="release_approver",
        deadline_at=deadline(),
    )
    revoke = display.registry_order.model_copy(
        update={
            "order_id": "display-revoke",
            "command": FiscalRevokeAuthorityCommandV1(
                command_id="revoke-display",
                authority_id=display.order.request.authority_id,
                grant_ref=authority.grant_ref,
                reason="ephemeral test revoke",
            ),
            "expected_head": next(
                head
                for head in authority.history_heads
                if head.stream_kind == "control"
            ),
        }
    )
    (
        display.registry._installation.orders_directory / "display-revoke.json"
    ).write_bytes(canonical_bytes(revoke))
    display.registry.apply("display-revoke", deadline_at=deadline())
    with pytest.raises(SnapshotError):
        reader.read_current(
            first.reference, first.candidate.reference, deadline_at=deadline()
        )
    assert display.env.store.read(first.reference.artifact_id) == canonical_bytes(
        first.decision
    )


def test_refs_only_scope_and_changed_command_refuse(display):
    from pydantic import ValidationError

    for key in (
        "rows",
        "formula",
        "approved",
        "principal_id",
        "key_id",
        "execution_id",
        "now",
        "content",
    ):
        with pytest.raises(ValidationError):
            FiscalDisplayRequestV1.model_validate(
                {**display.order.request.model_dump(), key: "caller-claim"}
            )
    first = display.runtime.apply(display.order.order_id, deadline_at=deadline())
    altered = display.order.model_copy(
        update={
            "request": display.order.request.model_copy(
                update={
                    "expires_at": display.order.request.expires_at
                    + timedelta(seconds=1)
                }
            )
        }
    )
    display.write(altered)
    with pytest.raises(SnapshotError) as failure:
        display.runtime.apply(altered.order_id, deadline_at=deadline())
    assert failure.value.code == "FISCAL_DISPLAY_COMMAND_REUSED"
    assert display.env.store.read(first.reference.artifact_id) == canonical_bytes(
        first.decision
    )


@pytest.mark.parametrize(
    "cut", ["review", "signing", "signed", "checkpoint", "control"]
)
def test_durable_cuts_retry_exact_bytes_and_unknown_sign_refuses(
    display, monkeypatch, cut
):
    put = display.env.store.put_with_receipt
    checkpoint = display.runtime.history.checkpoint
    append = display.runtime.history.append_once
    crashed = False

    def publish(identity, *args, **kwargs):
        nonlocal crashed
        result = put(identity, *args, **kwargs)
        prefix = {
            "review": "fiscal-display-review-v1:",
            "signing": "fiscal-display-signing-v1:",
            "signed": "fiscal-display-decision-v1:",
        }.get(cut)
        if prefix and identity.startswith(prefix) and not crashed:
            crashed = True
            raise RuntimeError("synthetic process loss after durable bytes")
        return result

    def history_cut(original, stage, *args, **kwargs):
        nonlocal crashed
        result = original(*args, **kwargs)
        if cut == stage and not crashed:
            crashed = True
            raise RuntimeError("synthetic process loss after durable history")
        return result

    monkeypatch.setattr(display.env.store, "put_with_receipt", publish)
    monkeypatch.setattr(
        display.runtime.history,
        "checkpoint",
        lambda *a, **kw: history_cut(checkpoint, "checkpoint", *a, **kw),
    )
    monkeypatch.setattr(
        display.runtime.history,
        "append_once",
        lambda *a, **kw: history_cut(append, "control", *a, **kw),
    )
    with pytest.raises(RuntimeError):
        display.runtime.apply(display.order.order_id, deadline_at=deadline())
    assert crashed
    monkeypatch.setattr(display.env.store, "put_with_receipt", put)
    monkeypatch.setattr(display.runtime.history, "checkpoint", checkpoint)
    monkeypatch.setattr(display.runtime.history, "append_once", append)
    identity = display.order.request.artifact_id("fiscal-display-decision-v1")
    original = (
        display.env.store.read(identity)
        if cut in {"signed", "checkpoint", "control"}
        else None
    )
    if cut == "signing":
        with pytest.raises(SnapshotError) as failure:
            display.runtime.apply(display.order.order_id, deadline_at=deadline())
        assert failure.value.code == "FISCAL_DISPLAY_SIGNING_OUTCOME_UNAVAILABLE"
    else:
        resumed = display.runtime.apply(display.order.order_id, deadline_at=deadline())
        if original:
            assert canonical_bytes(resumed.decision) == original
        assert (
            resumed.decision.body.signed_at
            < resumed.decision.body.command.request.expires_at
        )


def test_read_only_exact_current_metadata_race_and_final_expiry(display, monkeypatch):
    from test_fiscal_admission_authority import change_status

    first = display.runtime.apply(display.order.order_id, deadline_at=deadline())
    reader = build_fiscal_display_reader(
        candidates=display.runtime.candidates,
        deployment_file=display.runtime.installation.deployment_file,
        deployment_uid=os.getuid(),
        mapping_trust_roots_file=display.candidate_config.mapping_trust_roots_file,
        artifacts=display.env.store,
        metadata=display.env.metadata,
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("current display read attempted publication")

    monkeypatch.setattr(display.env.store, "put_with_receipt", forbidden)
    monkeypatch.setattr(display.env.store, "put_bytes_with_receipt", forbidden)
    assert not hasattr(reader.history, "checkpoint")
    assert reader._authorize is None
    assert (
        reader.read_current(
            first.reference, first.candidate.reference, deadline_at=deadline()
        ).reference
        == first.reference
    )
    with pytest.raises(SnapshotError):
        reader.read_current(
            first.reference,
            first.candidate.reference.model_copy(update={"content_hash": "f" * 64}),
            deadline_at=deadline(),
        )
    original_finish = reader.history.finish_observation

    def cross_expiry(*args, **kwargs):
        result = original_finish(*args, **kwargs)
        reader.clock = lambda: display.order.request.expires_at
        return result

    monkeypatch.setattr(reader.history, "finish_observation", cross_expiry)
    with pytest.raises(SnapshotError, match="expired"):
        reader.read_current(
            first.reference,
            first.candidate.reference,
            deadline_at=datetime.now(UTC) + timedelta(hours=1),
        )
    reader.clock = lambda: datetime.now(UTC)
    last_source = first.candidate.content.source_uses[
        -1
    ].scope.source_validation_ref.artifact_id

    def race(*args, **kwargs):
        change_status(display.env, last_source, "invalidated")
        return original_finish(*args, **kwargs)

    monkeypatch.setattr(reader.history, "finish_observation", race)
    with pytest.raises(SnapshotError):
        reader.read_current(
            first.reference, first.candidate.reference, deadline_at=deadline()
        )
    assert display.env.store.read(first.reference.artifact_id) == canonical_bytes(
        first.decision
    )


def test_review_checks_known_semantic_contracts_and_all_actor_activities(display):
    from dataclasses import replace

    from fundamental_service.fiscal_candidate_contracts import (
        ClassifiedSourceForCandidateV1,
        VerifiedClassifiedCandidateSource,
        VerifiedFiscalActivity,
    )
    from fundamental_service.fiscal_display_admission import FiscalDisplayAdmission
    from fundamental_service.fiscal_display_contracts import (
        FiscalDisplayReviewExecutionV1,
    )
    from fundamental_service.fiscal_statement_contracts import FiscalInputEdgeV1

    reader = build_fiscal_display_reader(
        candidates=display.runtime.candidates,
        deployment_file=display.runtime.installation.deployment_file,
        deployment_uid=os.getuid(),
        mapping_trust_roots_file=display.candidate_config.mapping_trust_roots_file,
        artifacts=display.env.store,
        metadata=display.env.metadata,
    )
    candidate = display.candidate
    node = next(
        node for node in candidate.projection.nodes if node.availability == "derived"
    )
    changes = (
        {"formula": "unreviewed-formula"},
        {"input_edges": (FiscalInputEdgeV1(input_id="unknown", coefficient=1),)},
        {"available_at": candidate.content.cutoff_at + timedelta(days=1)},
        {"availability": "unavailable", "value": node.value},
        {"executable_digest": "f" * 64},
    )
    for change in changes:
        changed = node.model_copy(update=change)
        projection = candidate.projection.model_copy(
            update={
                "quarter_nodes": tuple(
                    changed if item.node_id == node.node_id else item
                    for item in candidate.projection.quarter_nodes
                ),
                "ttm_nodes": tuple(
                    changed if item.node_id == node.node_id else item
                    for item in candidate.projection.ttm_nodes
                ),
            }
        )
        with pytest.raises(SnapshotError):
            reader._inspect(replace(candidate, projection=projection), deadline())
    now = datetime.now(UTC)
    actor = FiscalDisplayReviewExecutionV1(
        authority_id="display",
        grant_ref=candidate.preparation.grant_ref,
        principal_id="machine:independent",
        key_id="f" * 64,
        execution_id="display-job:" + "a" * 32,
        issuance=candidate.candidate.body.issuance,
        started_at=now,
        completed_at=now,
    )
    for field, value in [
        ("principal_id", candidate.preparation.principal_id),
        ("key_id", candidate.preparation.key_id),
    ]:
        with pytest.raises(SnapshotError):
            FiscalDisplayAdmission._independent(
                candidate, actor.model_copy(update={field: value})
            )
    activity = VerifiedFiscalActivity(
        "source_classification",
        "a",
        actor.principal_id,
        None,
        "e" * 64,
        None,
        ("last-source-job",),
        (),
    )
    fake_use = ClassifiedSourceForCandidateV1.model_construct(
        scope=candidate.content.source_uses[-1].scope,
        classification_refs=(candidate.reference,),
    )
    last = VerifiedClassifiedCandidateSource(fake_use, (activity,), (), (), ())
    with pytest.raises(SnapshotError):
        FiscalDisplayAdmission._independent(
            replace(candidate, source_evidence=(*candidate.source_evidence, last)),
            actor,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("audience", "wrong"),
        ("executable_digest", "f" * 64),
        ("deployment_digest", "e" * 64),
        ("valid_until", datetime.now(UTC) - timedelta(seconds=1)),
    ],
)
def test_protected_order_binding_refuses_before_review(display, field, value):
    changed = display.order.model_copy(update={field: value})
    display.write(changed)
    with pytest.raises(SnapshotError):
        display.runtime.apply(changed.order_id, deadline_at=deadline())
    with pytest.raises(SnapshotError) as missing:
        display.env.store.get(changed.request.artifact_id("fiscal-display-review-v1"))
    assert missing.value.code == "ARTIFACT_NOT_FOUND"


def test_installed_candidate_configuration_and_mapping_custody(display, monkeypatch):
    from fundamental_service.fiscal_display_runtime import (
        require_candidate_configuration,
    )

    installation = display.runtime.installation
    monkeypatch.setenv(
        "FUNDAMENTAL_FISCAL_AUTHORITY_DEPLOYMENT_FILE",
        str(installation.deployment_file),
    )
    monkeypatch.setenv(
        "FUNDAMENTAL_FISCAL_CANDIDATE_AUTHORITY_ID", installation.candidate_authority_id
    )
    monkeypatch.setenv(
        "FUNDAMENTAL_DATA_RELEASE_TRUST_ROOTS_FILE",
        str(installation.mapping_trust_roots_file),
    )
    require_candidate_configuration(installation)
    monkeypatch.setenv("FUNDAMENTAL_FISCAL_CANDIDATE_AUTHORITY_ID", "other-candidate")
    with pytest.raises(SnapshotError, match="selectors"):
        require_candidate_configuration(installation)
    monkeypatch.setenv(
        "FUNDAMENTAL_FISCAL_CANDIDATE_AUTHORITY_ID", installation.candidate_authority_id
    )
    installation.mapping_trust_roots_file.write_bytes(b"{}")
    with pytest.raises(SnapshotError, match="mapping trust"):
        require_candidate_configuration(installation)
    with pytest.raises(SnapshotError):
        display.runtime.apply(display.order.order_id, deadline_at=deadline())


def test_select_only_current_reader_without_any_signing_keys(
    display, tmp_path, monkeypatch
):
    from dataclasses import replace

    from fundamental_service.metadata import (
        PostgresArtifactStore,
        PostgresContentStore,
        PostgresMetadataStore,
    )
    from sqlalchemy import text
    from test_fiscal_candidate_read_runtime import select_only_role
    from test_fiscal_projection_builder import SyntheticRetainedSourcePort

    first = display.runtime.apply(display.order.order_id, deadline_at=deadline())
    for key in (
        display.runtime.installation.private_key_file,
        display.candidate_config.candidate_private_key_file,
        display.candidate_config.mapping_private_key_file,
        display.registry._installation.private_key_file,
    ):
        key.unlink()
    with select_only_role(display.env.metadata, display.env.database_url) as reader_url:
        metadata = PostgresMetadataStore(reader_url, auto_migrate=False)

        def forbidden(*args, **kwargs):
            raise AssertionError(
                "SELECT-only reader attempted migration or registration repair"
            )

        monkeypatch.setattr(metadata, "_apply_migration", forbidden)
        monkeypatch.setattr(metadata, "register_content", forbidden)
        monkeypatch.setattr(metadata, "publish_artifact", forbidden)
        try:
            metadata.start_read_only()
            store = PostgresArtifactStore(
                metadata,
                PostgresContentStore(tmp_path / "pg-content", metadata, read_only=True),
                read_only=True,
            )
            inputs = replace(
                display.inputs,
                artifacts=store,
                sources=SyntheticRetainedSourcePort(
                    display.inputs.sources.evidence, store
                ),
            )
            config = display.candidate_config.model_copy(
                update={
                    "candidate_private_key_file": None,
                    "mapping_private_key_file": None,
                }
            )
            candidates = build_fiscal_candidate_runtime(
                inputs, metadata, config, write=False
            )
            reader = build_fiscal_display_reader(
                candidates=candidates,
                deployment_file=display.runtime.installation.deployment_file,
                deployment_uid=os.getuid(),
                mapping_trust_roots_file=config.mapping_trust_roots_file,
                artifacts=store,
                metadata=metadata,
            )
            assert (
                reader.read_current(
                    first.reference, first.candidate.reference, deadline_at=deadline()
                ).reference
                == first.reference
            )

            async def privileges(connection):
                return tuple(
                    (
                        await connection.execute(
                            text(
                                "SELECT has_table_privilege(current_user,'fundamental.artifact_references','INSERT'),has_schema_privilege(current_user,'fundamental','CREATE'),has_database_privilege(current_user,current_database(),'CREATE')"
                            )
                        )
                    ).one()
                )

            assert metadata.run_fiscal_admission_history(privileges) == (
                False,
                False,
                False,
            )
        finally:
            metadata.close()


def test_old_signed_orphan_order_refuses_after_actual_restore(
    display, tmp_path, monkeypatch
):
    import asyncio

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
    from test_fiscal_admission_history import _temporary_database
    from test_fiscal_history_recovery import target_pin

    put = display.env.store.put_with_receipt

    def stop_after_signed(identity, *args, **kwargs):
        result = put(identity, *args, **kwargs)
        if identity.startswith("fiscal-display-decision-v1:"):
            raise RuntimeError("retained signed orphan before control")
        return result

    monkeypatch.setattr(display.env.store, "put_with_receipt", stop_after_signed)
    with pytest.raises(RuntimeError):
        display.runtime.apply(display.order.order_id, deadline_at=deadline())
    monkeypatch.setattr(display.env.store, "put_with_receipt", put)
    old_bytes = display.env.store.read(
        display.order.request.artifact_id("fiscal-display-decision-v1")
    )
    receipt = asyncio.run(
        export_backup(
            display.env.database_url,
            tmp_path / "pg-content",
            tmp_path / "backups",
            source_revision="a" * 40,
        )
    )
    bundle = tmp_path / "backups" / receipt.manifest_digest
    manifest = _verify_bundle(bundle, receipt.manifest_digest)
    with _temporary_database(os.environ["FUNDAMENTAL_TEST_DATABASE_URL"]) as target:
        with target_pin(target, manifest, tmp_path / "restore-pin.json") as pin:
            asyncio.run(
                restore_backup(
                    target,
                    tmp_path / "restored-content",
                    bundle,
                    manifest_digest=manifest.digest,
                    authorization_path=pin,
                )
            )
        metadata = PostgresMetadataStore(target, auto_migrate=False)
        try:
            metadata.start_read_only()
            store = PostgresArtifactStore(
                metadata, PostgresContentStore(tmp_path / "restored-content", metadata)
            )
            runtime = FiscalDisplayRuntime(
                installation=display.runtime.installation,
                candidates=display.runtime.candidates,
                artifacts=store,
                metadata=metadata,
            )
            with pytest.raises(SnapshotError):
                runtime.apply(display.order.order_id, deadline_at=deadline())
            assert (
                store.read(
                    display.order.request.artifact_id("fiscal-display-decision-v1")
                )
                == old_bytes
            )
        finally:
            metadata.close()


def test_wrong_control_head_refuses_before_review(display):
    changed = display.order.model_copy(
        update={"expected_head": display.candidate.history_heads[0]}
    )
    display.write(changed)
    with pytest.raises(SnapshotError, match="head"):
        display.runtime.apply(changed.order_id, deadline_at=deadline())
    with pytest.raises(SnapshotError) as missing:
        display.env.store.get(changed.request.artifact_id("fiscal-display-review-v1"))
    assert missing.value.code == "ARTIFACT_NOT_FOUND"


def test_control_commit_before_seal_is_read_only_refusal_and_writer_exact_resume(
    display, monkeypatch
):
    from fundamental_service.fiscal_admission_history import (
        PostgresFiscalAdmissionHistory,
    )

    original = PostgresFiscalAdmissionHistory.seal_pending
    stopped = False

    def stop(self, streams, *, deadline_at):
        nonlocal stopped
        if not stopped and any(
            stream.startswith("control:display-decision:") for stream in streams
        ):
            stopped = True
            raise RuntimeError("synthetic exit after control commit before seal")
        return original(self, streams, deadline_at=deadline_at)

    monkeypatch.setattr(PostgresFiscalAdmissionHistory, "seal_pending", stop)
    with pytest.raises(RuntimeError):
        display.runtime.apply(display.order.order_id, deadline_at=deadline())
    assert stopped
    identity = display.order.request.artifact_id("fiscal-display-decision-v1")
    record = display.env.store.get(identity)
    ref = reference(record, "fiscal-display-decision-v1")
    signed_bytes = display.env.store.read(identity)
    reader = build_fiscal_display_reader(
        candidates=display.runtime.candidates,
        deployment_file=display.runtime.installation.deployment_file,
        deployment_uid=os.getuid(),
        mapping_trust_roots_file=display.candidate_config.mapping_trust_roots_file,
        artifacts=display.env.store,
        metadata=display.env.metadata,
    )
    with pytest.raises(SnapshotError):
        reader.read_current(ref, display.candidate.reference, deadline_at=deadline())
    monkeypatch.setattr(PostgresFiscalAdmissionHistory, "seal_pending", original)
    resumed = display.runtime.apply(display.order.order_id, deadline_at=deadline())
    assert not resumed.publication.wrote
    assert canonical_bytes(resumed.decision) == signed_bytes
