from __future__ import annotations

from datetime import timedelta

import pytest
import test_fiscal_source_classification as classification_cases

from fundamental_service.fiscal_authority_contracts import (
    FiscalRevokeAuthorityCommandV1,
)
from fundamental_service.fiscal_classification_contracts import (
    FiscalClassifierReviewExecutionV1,
)
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import SnapshotError
from test_fiscal_admission_authority import change_status, reference
from test_fiscal_source_classification import (
    deadline,
    publish_classification,
    retained,
)

environment = classification_cases.environment


def forbid_writes(*args, **kwargs):
    raise AssertionError("current classification read must not publish or seal")


@pytest.mark.parametrize(
    "evidence",
    [
        "classification",
        "review",
        "review-execution",
        "preparer-execution",
        "witness",
        "classifier-grant",
        "preparer-grant",
    ],
)
def test_current_read_refuses_invalidated_dependency_without_writing(
    environment, monkeypatch, evidence
):
    env = environment
    result, classification_ref = publish_classification(env)
    signed = result.signed_classification
    ref = {
        "classification": classification_ref,
        "review": env.command.review_ref,
        "review-execution": signed.reviewer.execution_ref,
        "preparer-execution": env.command.preparer_execution_ref,
        "witness": env.command.witness_ref,
        "classifier-grant": signed.authority_grant_ref,
        "preparer-grant": reference(
            env.grants["source_preparer"].publication.artifact,
            "fiscal-authority-record-v1",
        ),
    }[evidence]
    change_status(env, ref.artifact_id, "invalidated")
    monkeypatch.setattr(env.store, "put_with_receipt", forbid_writes)
    monkeypatch.setattr(env.store, "put_bytes_with_receipt", forbid_writes)
    monkeypatch.setattr(env.signer, "sign", forbid_writes)
    for operation in ("checkpoint", "append_once", "seal_pending"):
        monkeypatch.setattr(env.history, operation, forbid_writes)
    with pytest.raises(SnapshotError) as failure:
        env.owner.require_candidate_source(
            env.source.scope, (classification_ref,), deadline_at=deadline()
        )
    assert failure.value.code in {
        "FISCAL_CLASSIFICATION_INVALID",
        "FISCAL_VALIDATION_INVALID",
        "FISCAL_AUTHORITY_INVALID",
    }
    assert env.store.get(classification_ref.artifact_id).content_hash == (
        classification_ref.content_hash
    )
    assert env.signer.sign_calls == 1


@pytest.mark.parametrize("phase", ["before-classification", "after-classification"])
def test_preparer_revocation_prevents_classification_or_current_candidate(
    environment, phase
):
    env = environment
    published = publish_classification(env) if phase == "after-classification" else None
    grant = env.grants["source_preparer"]
    identity = grant.signed_record.record.identity
    env.authorities.revoke(
        FiscalRevokeAuthorityCommandV1(
            command_id="synthetic-revoke-preparer",
            authority_id=identity.authority_id,
            grant_ref=reference(
                grant.publication.artifact, "fiscal-authority-record-v1"
            ),
            reason="Synthetic preparer revocation boundary",
        ),
        expected_head=next(
            head for head in grant.history_heads if head.stream_kind == "control"
        ),
        deadline_at=deadline(),
    )
    with pytest.raises(SnapshotError) as failure:
        if published is None:
            env.owner.record_classification(
                env.command, expected_head=None, deadline_at=deadline()
            )
        else:
            env.owner.require_candidate_source(
                env.source.scope, (published[1],), deadline_at=deadline()
            )
    assert failure.value.code == "FISCAL_AUTHORITY_REFUSED"
    assert env.signer.sign_calls == (0 if published is None else 1)
    if published is not None:
        assert env.store.read(published[1].artifact_id) == canonical_bytes(
            published[0].signed_classification
        )


@pytest.mark.parametrize("expired", ["classification", "witness"])
def test_current_read_refuses_exact_expiry_boundary(environment, expired):
    env = environment
    if expired == "witness":
        env.command = env.command.model_copy(
            update={"expires_at": env.source.witness.expires_at + timedelta(minutes=5)}
        )
    result, classification_ref = publish_classification(env)
    now = (
        env.command.expires_at
        if expired == "classification"
        else env.source.witness.expires_at
    )
    if expired == "witness":
        assert now < env.command.expires_at
    env.owner.clock = lambda: now
    with pytest.raises(SnapshotError) as failure:
        env.owner.require_candidate_source(
            env.source.scope,
            (classification_ref,),
            deadline_at=now + timedelta(minutes=1),
        )
    assert failure.value.code == "FISCAL_CLASSIFICATION_INVALID"
    assert env.signer.sign_calls == 1
    assert env.store.read(classification_ref.artifact_id) == canonical_bytes(
        result.signed_classification
    )


@pytest.mark.parametrize("focus_execution", ["result_ref", "delivery_ref"])
def test_classifier_cannot_reuse_actual_focus_execution(
    environment, monkeypatch, focus_execution
):
    env = environment
    authenticate = env.signer.authenticate
    reused_id = getattr(
        env.source.witness.witness.actions[0], focus_execution
    ).artifact_id

    def reused(command, review, *, issuance, deadline_at):
        actor = authenticate(
            command, review, issuance=issuance, deadline_at=deadline_at
        )
        execution = FiscalClassifierReviewExecutionV1.model_validate_json(
            env.store.read(actor.execution_ref.artifact_id)
        ).model_copy(update={"execution_id": reused_id})
        execution_ref = retained(
            env.store,
            "synthetic-reused-focus-execution",
            execution,
            "fiscal-classifier-review-execution-v1",
        )
        return actor.model_copy(update={"execution_ref": execution_ref})

    monkeypatch.setattr(env.signer, "authenticate", reused)
    with pytest.raises(SnapshotError) as failure:
        env.owner.record_classification(
            env.command, expected_head=None, deadline_at=deadline()
        )
    assert failure.value.code == "FISCAL_CLASSIFICATION_INVALID"
    assert env.signer.sign_calls == 0
    with pytest.raises(SnapshotError) as absent:
        env.store.get(env.command.artifact_id)
    assert absent.value.code == "ARTIFACT_NOT_FOUND"
