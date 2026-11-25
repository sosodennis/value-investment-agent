from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import test_fiscal_admission_authority as authority_cases
import test_fiscal_source_classification as classification_cases
from pydantic import ValidationError

from fundamental_service.fiscal_authority_contracts import FiscalRegistryExecutionV1
from fundamental_service.fiscal_classification_contracts import (
    FiscalClassifierReviewExecutionV1,
    FiscalRecordClassificationCommandV1,
    SignedFiscalSourceClassificationV1,
    SignedFiscalSourcePreparationExecutionV1,
)
from fundamental_service.history_recovery_contracts import FiscalIssuanceContextV1
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import SnapshotError
from test_fiscal_admission_authority import deadline

environment = classification_cases.environment
authority_environment = authority_cases.environment
database_url = authority_cases.database_url
metadata = authority_cases.metadata
artifacts = authority_cases.artifacts


def test_invocation_and_signed_executions_bind_the_trusted_epoch(
    environment, monkeypatch
):
    env = environment
    expected = env.history.read_epoch(deadline_at=deadline()).issuance_context
    authenticate = env.signer.authenticate
    invoked = []

    def observe(command, review, *, issuance, deadline_at):
        assert issuance == expected
        assert (
            issuance == env.history.read_epoch(deadline_at=deadline_at).issuance_context
        )
        invoked.append(issuance)
        return authenticate(command, review, issuance=issuance, deadline_at=deadline_at)

    monkeypatch.setattr(env.signer, "authenticate", observe)
    published, _ = classification_cases.publish_classification(env)
    signed = published.signed_classification
    review_execution = FiscalClassifierReviewExecutionV1.model_validate_json(
        env.store.read(signed.reviewer.execution_ref.artifact_id)
    )
    preparation = SignedFiscalSourcePreparationExecutionV1.model_validate_json(
        env.store.read(env.command.preparer_execution_ref.artifact_id)
    )
    assert invoked == [expected]
    assert (
        signed.issuance
        == review_execution.issuance
        == preparation.execution.issuance
        == expected
    )
    for value in (signed, review_execution, preparation.execution):
        with pytest.raises(ValidationError, match="issuance"):
            type(value).model_validate(value.model_dump(exclude={"issuance"}))
    with pytest.raises(ValidationError, match="issuance"):
        FiscalRecordClassificationCommandV1.model_validate(
            {**env.command.model_dump(), "issuance": expected.model_dump()}
        )


@pytest.mark.parametrize("execution_kind", ["preparation", "review"])
def test_current_classifier_refuses_another_execution_origin_before_signing(
    environment, execution_kind
):
    env = environment
    wrong = FiscalIssuanceContextV1(origin_id=str(uuid4()))
    if execution_kind == "review":
        env.signer.execution_update = lambda execution: execution.model_copy(
            update={"issuance": wrong}
        )
    else:
        previous = SignedFiscalSourcePreparationExecutionV1.model_validate_json(
            env.store.read(env.command.preparer_execution_ref.artifact_id)
        )
        changed = previous.model_copy(
            update={
                "execution": previous.execution.model_copy(update={"issuance": wrong})
            }
        )
        changed = changed.model_copy(
            update={"signature": env.preparer_key.sign(changed.signing_bytes()).hex()}
        )
        execution_ref = classification_cases.retained(
            env.store,
            "synthetic-wrong-origin-preparation",
            changed,
            "fiscal-source-preparation-execution-v1",
        )
        env.command = env.command.model_copy(
            update={"preparer_execution_ref": execution_ref}
        )
    with pytest.raises(SnapshotError) as failure:
        env.owner.record_classification(
            env.command, expected_head=None, deadline_at=deadline()
        )
    assert failure.value.code == "FISCAL_CLASSIFICATION_INVALID"
    assert env.signer.sign_calls == 0
    with pytest.raises(SnapshotError) as absent:
        env.store.get(env.command.artifact_id)
    assert absent.value.code == "ARTIFACT_NOT_FOUND"


@pytest.mark.parametrize("operation", ["record", "read"])
def test_classification_rechecks_epoch_after_the_final_history_check(
    environment, monkeypatch, operation
):
    env = environment
    result, ref = classification_cases.publish_classification(env)
    raw = env.store.read(ref.artifact_id)
    original_heads = env.history.require_heads
    original_epoch = env.history.read_epoch
    crossed = False

    def cross(*args, **kwargs):
        nonlocal crossed
        original_heads(*args, **kwargs)
        if any(
            head.subject_id.startswith("fiscal-classification:") for head in args[0]
        ):
            crossed = True

    def epoch(*, deadline_at):
        value = original_epoch(deadline_at=deadline_at)
        return (
            value.model_copy(update={"local_origin_id": str(uuid4())})
            if crossed
            else value
        )

    monkeypatch.setattr(env.history, "require_heads", cross)
    monkeypatch.setattr(env.history, "read_epoch", epoch)
    with pytest.raises(SnapshotError, match="epoch changed"):
        if operation == "record":
            env.owner.record_classification(
                env.command, expected_head=None, deadline_at=deadline()
            )
        else:
            env.owner.require_candidate_source(
                env.source.scope, (ref,), deadline_at=deadline()
            )
    assert (
        env.store.read(ref.artifact_id)
        == raw
        == canonical_bytes(result.signed_classification)
    )
    assert env.signer.sign_calls == 1


def test_authority_rejects_another_execution_origin_before_signing(
    authority_environment,
):
    env = authority_environment

    def other_origin(operator):
        execution = FiscalRegistryExecutionV1.model_validate_json(
            env.store.read(operator.execution_ref.artifact_id)
        ).model_copy(
            update={"issuance": FiscalIssuanceContextV1(origin_id=str(uuid4()))}
        )
        record = env.store.put_with_receipt(
            "synthetic-other-epoch-execution", execution
        ).artifact
        return operator.model_copy(
            update={
                "execution_ref": authority_cases.reference(
                    record, "fiscal-registry-execution-v1"
                )
            }
        )

    env.signer.on_authenticate = other_origin
    with pytest.raises(SnapshotError, match="execution"):
        env.owner.grant(
            authority_cases.grant_command(), expected_head=None, deadline_at=deadline()
        )
    assert env.signer.sign_calls == 0


@pytest.mark.parametrize("reverse", [False, True])
def test_durable_classification_cannot_mix_execution_and_signed_origins(
    environment, reverse
):
    env = environment
    epoch = env.history.read_epoch(deadline_at=deadline()).issuance_context
    other = FiscalIssuanceContextV1(origin_id=str(uuid4()))
    actor = env.signer.authenticate(
        env.command,
        env.review,
        issuance=other if reverse else epoch,
        deadline_at=deadline(),
    )
    grant = env.grants["classifier"]
    signed = SignedFiscalSourceClassificationV1(
        command=env.command,
        review=env.review,
        reviewer=actor,
        authority_grant_ref=authority_cases.reference(
            grant.publication.artifact, "fiscal-authority-record-v1"
        ),
        issuance=epoch if reverse else other,
        signed_at=datetime.now(UTC),
        signature="0" * 128,
    )
    signed = signed.model_copy(
        update={"signature": env.signer.key.sign(signed.signing_bytes()).hex()}
    )
    env.store.put_with_receipt(
        signed.artifact_id, signed, env.owner._dependencies(signed)
    )
    raw = env.store.read(signed.artifact_id)
    with pytest.raises(SnapshotError) as failure:
        env.owner.record_classification(
            env.command, expected_head=None, deadline_at=deadline()
        )
    assert failure.value.code == "FISCAL_CLASSIFICATION_INVALID"
    assert env.signer.sign_calls == 0
    assert env.store.read(signed.artifact_id) == raw


def test_classification_signing_crash_retries_a_real_execution_without_relabelling(
    environment, monkeypatch
):
    env = environment
    authenticate = env.signer.authenticate
    executions = []

    def observed(command, review, *, issuance, deadline_at):
        actor = authenticate(
            command, review, issuance=issuance, deadline_at=deadline_at
        )
        executions.append(
            (actor.execution_ref, env.store.read(actor.execution_ref.artifact_id))
        )
        return actor

    monkeypatch.setattr(env.signer, "authenticate", observed)
    env.signer.on_sign = lambda: (_ for _ in ()).throw(
        RuntimeError("synthetic signing interruption")
    )
    with pytest.raises(RuntimeError, match="signing interruption"):
        env.owner.record_classification(
            env.command, expected_head=None, deadline_at=deadline()
        )
    with pytest.raises(SnapshotError) as absent:
        env.store.get(env.command.artifact_id)
    assert absent.value.code == "ARTIFACT_NOT_FOUND"
    env.signer.on_sign = lambda: None
    result, ref = classification_cases.publish_classification(env)
    assert len(executions) == 2 and executions[0][0] != executions[1][0]
    assert all(
        env.store.read(identity.artifact_id) == raw for identity, raw in executions
    )
    assert result.signed_classification.reviewer.execution_ref == executions[1][0]
    assert (
        env.owner.require_candidate_source(
            env.source.scope, (ref,), deadline_at=deadline()
        ).scope
        == env.source.scope
    )
    assert env.signer.sign_calls == 2
