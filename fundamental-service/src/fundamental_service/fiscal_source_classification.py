from __future__ import annotations

import os
from asyncio import current_task
from threading import get_ident
from contextvars import ContextVar

import base64
from copy import deepcopy
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import partial
from typing import Literal, Protocol
from pydantic import TypeAdapter

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .artifact_evidence import read_retained_artifact
from .command_artifacts import EvidenceArtifactStore
from .data_releases import ArtifactRefV1, DataReleaseError
from .fiscal_admission_authority import FiscalAuthorityOwner
from .fiscal_admission_history import (
    FiscalAdmissionHistoryPort,
    FiscalAdmissionHistoryReaderPort,
    FiscalCommitReceiptV1,
    FiscalControlBindingV1,
    FiscalHistoryHeadV1,
    FiscalHistoryReadV1,
)
from .fiscal_authority_contracts import CurrentFiscalAuthorityV1
from .history_recovery_contracts import FiscalHistoryEpochV1, FiscalIssuanceContextV1
from .fiscal_candidate_contracts import (
    ClassifiedSourceForCandidateV1,
    VerifiedClassifiedCandidateSource,
    VerifiedFiscalActivity,
    FiscalSourceUseScopeV1,
    CorrectnessOwner,
)
from .fiscal_classification_contracts import (
    FiscalSourcePreparationExecutionV1,
    FiscalClassificationPublicationV1,
    FiscalClassifierActorV1,
    FiscalClassifierReviewExecutionV1,
    FiscalRecordClassificationCommandV1,
    FiscalSourceAccountingReviewV1,
    SignedFiscalSourceClassificationV1,
    SignedFiscalSourcePreparationExecutionV1,
    FiscalRecordClassificationCommandV2,
    SignedFiscalSourceClassificationV2,
    FiscalClassificationPublicationV2,
)
from .fiscal_classification_review import verify_fiscal_source_review
from .fiscal_classification_source import (
    FiscalClassificationSource,
    FiscalClassificationSourcePort,
    FiscalClassificationSourceReadPort,
)
from .fiscal_source_closure import (
    FiscalArtifactRead,
    FiscalArtifactReadSet,
    FiscalSourceContentReadSet,
)
from .fiscal_validation_contracts import FiscalRetainedInputBindingV1
from .metadata import metadata_operation_budget
from .replay import (
    ArtifactPublicationDeadlineExceeded,
    ArtifactPublicationV1,
    ArtifactRecordV1,
)
from .serialization import canonical_bytes
from .snapshots import SnapshotError
from .fiscal_source_preparation import (
    FiscalSourceProducerEvidenceVerifier,
    read_source_preparation,
)
from .fiscal_source_producer_contracts import (
    FiscalClassifierReviewExecutionV2,
    SignedFiscalSourcePreparationExecutionV2,
)

ClassificationCommand = (
    FiscalRecordClassificationCommandV1 | FiscalRecordClassificationCommandV2
)
SignedClassification = (
    SignedFiscalSourceClassificationV1 | SignedFiscalSourceClassificationV2
)

_ROLE = "fiscal-source-classification-v1"
_V2_ROLE = "fiscal-source-classification-v2"


class FiscalClassifierSignerPort(Protocol):
    def authenticate(
        self,
        command: ClassificationCommand,
        review: FiscalSourceAccountingReviewV1,
        *,
        issuance: FiscalIssuanceContextV1,
        deadline_at: datetime,
    ) -> FiscalClassifierActorV1: ...

    def sign(
        self, message: bytes, *, actor: FiscalClassifierActorV1, deadline_at: datetime
    ) -> str: ...


class FiscalClassifierRecoveryPort(Protocol):
    def restore(
        self,
        command: ClassificationCommand,
        *,
        actor: FiscalClassifierActorV1,
        issuance: FiscalIssuanceContextV1,
        deadline_at: datetime,
    ) -> SignedClassification | None: ...


def _invalid(message: str) -> SnapshotError:
    return SnapshotError("FISCAL_CLASSIFICATION_INVALID", message)


def _ref(record: ArtifactRecordV1) -> ArtifactRefV1:
    return ArtifactRefV1(
        role=_V2_ROLE if record.artifact_id.startswith(_V2_ROLE + ":") else _ROLE,
        artifact_id=record.artifact_id,
        content_hash=record.content_hash,
        media_type=record.media_type,
    )


def _signature(
    message: bytes, signature: str, authority: CurrentFiscalAuthorityV1
) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(
            base64.b64decode(
                authority.grant.identity.public_key_ed25519_base64, validate=True
            )
        ).verify(bytes.fromhex(signature), message)
    except (ValueError, InvalidSignature) as error:
        raise _invalid("classification or preparation signature is invalid") from error


class _AdmissionSourceRead:
    def __init__(self, deadline_at: datetime) -> None:
        self.deadline_at = deadline_at
        self.inputs: bytes | None = None
        self.owner: FiscalClassificationSourcePort | None = None
        self.derivation: FiscalClassificationSourceReadPort | None = None


class _ClassificationRead:
    def __init__(self, reader: FiscalArtifactRead) -> None:
        self.reader = reader
        self.pure_reader = reader.for_consumer()
        self.heads: dict[str, FiscalHistoryHeadV1] = {}
        self.visible_after: datetime | None = None
        self.authorities: dict[str, CurrentFiscalAuthorityV1] = {}
        self.epoch: FiscalHistoryEpochV1 | None = None
        self.activities: tuple[VerifiedFiscalActivity, ...] = ()
        self.accreditation: ArtifactRefV1 | None = None
        self.source_admission: _AdmissionSourceRead | None = None

    def verify_review(
        self,
        source: FiscalClassificationSource,
        review: FiscalSourceAccountingReviewV1,
        check_deadline: Callable[[], float],
    ) -> None:
        verify_fiscal_source_review(source, review, check_deadline=check_deadline)

    def observe_source(
        self,
        owner: FiscalClassificationSourcePort,
        command: ClassificationCommand,
        *,
        reader: FiscalArtifactRead,
        check_deadline: Callable[[], float],
        deadline_at: datetime,
    ) -> FiscalClassificationSourceReadPort:
        return owner.observe(
            command.source_validation_ref,
            command.witness_ref,
            command.security_id,
            reader=reader,
            check_deadline=check_deadline,
            deadline_at=deadline_at,
        )

    def verify_producer(
        self,
        owner: FiscalSourceProducerEvidenceVerifier,
        command: FiscalRecordClassificationCommandV2,
        source: FiscalClassificationSource,
        review: FiscalSourceAccountingReviewV1,
        proof: FiscalClassifierReviewExecutionV2,
        preparation: SignedFiscalSourcePreparationExecutionV2,
        *,
        reader: FiscalArtifactRead,
        check_deadline: Callable[[], float],
        now: datetime,
    ) -> tuple[FiscalClassifierReviewExecutionV1, FiscalSourcePreparationExecutionV1]:
        return owner.verify(
            command,
            source,
            review,
            proof,
            preparation,
            reader=reader,
            check_deadline=check_deadline,
            now=now,
        )

    def observe(self, history: FiscalHistoryReadV1) -> None:
        if self.epoch is not None and self.epoch != history.epoch:
            raise _invalid("classification recovery epoch changed during verification")
        self.epoch = history.epoch
        for entry in history.entries:
            if not isinstance(entry.commit_bound, FiscalCommitReceiptV1):
                raise _invalid(
                    "classification requires sealed evidence and control history"
                )
            upper = entry.commit_bound.visible_by
            self.visible_after = (
                max(upper, self.visible_after) if self.visible_after else upper
            )
        for head in history.heads:
            if self.heads.setdefault(head.stream_id, head) != head:
                raise _invalid("classification history changed during verification")


_CLASSIFICATION_READS: ContextVar[tuple[object, ...]] = ContextVar(
    "fiscal_classification_reads", default=()
)


class _PreparedClassificationRead(_ClassificationRead):
    def __init__(
        self,
        reader: FiscalArtifactRead,
        scope: FiscalSourceUseScopeV1,
        binding: FiscalRetainedInputBindingV1,
    ) -> None:
        super().__init__(reader)
        self.scope, self.binding = scope, binding

    def verify_review(
        self,
        source: FiscalClassificationSource,
        review: FiscalSourceAccountingReviewV1,
        check_deadline: Callable[[], float],
    ) -> None:
        check_deadline()
        if review.scope != self.scope or source.scope != self.scope:
            raise _invalid(
                "current accounting review differs from trusted source scope"
            )

    def observe_source(
        self,
        owner: FiscalClassificationSourcePort,
        command: ClassificationCommand,
        *,
        reader: FiscalArtifactRead,
        check_deadline: Callable[[], float],
        deadline_at: datetime,
    ) -> FiscalClassificationSourceReadPort:
        return owner._observe_current(
            self.scope,
            self.binding,
            command.security_id,
            reader=reader,
            check_deadline=check_deadline,
            deadline_at=deadline_at,
        )

    def verify_producer(
        self,
        owner: FiscalSourceProducerEvidenceVerifier,
        command: FiscalRecordClassificationCommandV2,
        source: FiscalClassificationSource,
        review: FiscalSourceAccountingReviewV1,
        proof: FiscalClassifierReviewExecutionV2,
        preparation: SignedFiscalSourcePreparationExecutionV2,
        *,
        reader: FiscalArtifactRead,
        check_deadline: Callable[[], float],
        now: datetime,
    ) -> tuple[FiscalClassifierReviewExecutionV1, FiscalSourcePreparationExecutionV1]:
        return owner.verify_current(
            command,
            source,
            review,
            proof,
            preparation,
            reader=reader,
            check_deadline=check_deadline,
            now=now,
        )


def _classification_actor() -> tuple[object, ...]:
    try:
        task: object | None = current_task()
    except RuntimeError:
        task = None
    return (
        os.getpid(),
        get_ident(),
        task,
        os.getuid(),
        os.geteuid(),
        os.getgid(),
        os.getegid(),
        tuple(sorted(os.getgroups())),
    )


class FiscalClassifiedSourceRead:
    def __init__(
        self,
        owner: FiscalSourceClassificationOwner,
        scope: FiscalSourceUseScopeV1,
        classification_refs: tuple[ArtifactRefV1, ...],
        signed: SignedClassification,
        state: _ClassificationRead,
        deadline_at: datetime,
        actor: tuple[object, ...],
    ) -> None:
        self._owner, self._scope, self._refs = (
            owner,
            deepcopy(scope),
            deepcopy(classification_refs),
        )
        self._signed, self._state, self._deadline_at = signed, state, deadline_at
        self._owners = (
            owner.artifacts,
            owner.history,
            owner.authorities,
            owner.sources,
            owner.producer_evidence,
            owner.clock,
            owner.require_production_evidence,
        )
        self._actor = actor
        self._closed = False

    def close(self) -> None:
        self._closed = True
        self._state.source_admission = None

    @property
    def artifact_readset(self) -> FiscalArtifactReadSet:
        return self._state.reader.readset

    @property
    def content_readsets(self) -> tuple[FiscalSourceContentReadSet, ...]:
        admission = self._state.source_admission
        if admission is None or admission.derivation is None:
            raise _invalid("classification has no actual source readset")
        return admission.derivation.content_readsets

    @property
    def correctness_inputs(
        self,
    ) -> tuple[tuple[CorrectnessOwner, ArtifactRefV1, tuple[object, ...]], ...]:
        admission = self._state.source_admission
        if admission is None or admission.derivation is None:
            raise _invalid("classification correctness has no actual source consumer")
        signed, source = self._signed, admission.derivation
        return (
            ("witness", signed.command.witness_ref, source.witness_input_footprint),
            (
                "classification_resolver",
                signed.command.source_validation_ref,
                source.input_footprint,
            ),
            ("classification", self._refs[0], self._state.pure_reader.input_footprint),
            (
                "accounting",
                signed.command.review_ref,
                self._state.pure_reader.input_footprint,
            ),
        )

    def current(self) -> VerifiedClassifiedCandidateSource:
        if self._closed:
            raise _invalid("classification observation is closed")
        owner = self._owner
        if (
            self._actor != _classification_actor()
            or self not in _CLASSIFICATION_READS.get()
        ):
            self.close()
            raise _invalid("classification observation belongs to another execution")
        try:
            if self._owners != (
                owner.artifacts,
                owner.history,
                owner.authorities,
                owner.sources,
                owner.producer_evidence,
                owner.clock,
                owner.require_production_evidence,
            ):
                raise _invalid("classification configured owner changed")
            return self._current()
        except BaseException:
            self.close()
            raise

    def _current(self) -> VerifiedClassifiedCandidateSource:
        owner, signed, state, deadline_at = (
            self._owner,
            self._signed,
            self._state,
            self._deadline_at,
        )
        scope, classification_refs = self._scope, self._refs
        owner._finish(signed, state, deadline_at)
        for authority in state.authorities.values():
            for head in authority.history_heads:
                if head.stream_kind == "evidence":
                    state.reader.get(head.subject_id)
        source = owner._source(signed.command, state, deadline_at)
        owner._finish(signed, state, deadline_at)
        return deepcopy(
            VerifiedClassifiedCandidateSource(
                source_use=ClassifiedSourceForCandidateV1(
                    scope=scope, classification_refs=classification_refs
                ),
                activities=state.activities,
                consumed_metadata=tuple(
                    record for _, record in state.reader.records if record is not None
                ),
                history_heads=tuple(state.heads.values())
                + tuple(
                    head
                    for authority in state.authorities.values()
                    for head in authority.history_heads
                ),
                expires_at=(
                    signed.command.expires_at,
                    source.witness.expires_at,
                )
                + tuple(
                    authority.grant.valid_until
                    for authority in state.authorities.values()
                ),
            )
        )


class FiscalSourceClassificationOwner:
    def __init__(
        self,
        *,
        artifacts: EvidenceArtifactStore,
        history: FiscalAdmissionHistoryReaderPort | None,
        authorities: FiscalAuthorityOwner,
        sources: FiscalClassificationSourcePort | None,
        signer: FiscalClassifierSignerPort | None = None,
        recovery: FiscalClassifierRecoveryPort | None = None,
        producer_evidence: FiscalSourceProducerEvidenceVerifier | None = None,
        require_production_evidence: bool = False,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.artifacts = artifacts
        self.history = history
        self.authorities = authorities
        self.sources = sources
        self.signer = signer
        self.recovery = recovery
        self.producer_evidence = producer_evidence
        self.require_production_evidence = require_production_evidence
        self.clock = clock

    @staticmethod
    def _expired() -> SnapshotError:
        return SnapshotError(
            "REQUEST_DEADLINE_EXCEEDED",
            "fiscal classification deadline expired",
            retryable=True,
        )

    def _now(self) -> datetime:
        now = self.clock()
        if now.utcoffset() is None:
            raise _invalid("classification clock must be timezone aware")
        return now

    def _budget(self, deadline_at: datetime) -> float:
        now = self._now()
        if deadline_at.utcoffset() is None or now >= deadline_at:
            raise self._expired()
        return (deadline_at - now).total_seconds()

    def _history(self) -> FiscalAdmissionHistoryReaderPort:
        if self.history is None:
            raise SnapshotError(
                "FISCAL_CLASSIFICATION_HISTORY_UNCONFIGURED",
                "classification requires a trusted history owner",
            )
        return self.history

    @staticmethod
    def _subject(command: ClassificationCommand) -> str:
        return "fiscal-classification:" + command.artifact_id

    def _authority(
        self,
        identity: str,
        role: Literal["classifier", "source_preparer"],
        state: _ClassificationRead,
        deadline_at: datetime,
    ) -> CurrentFiscalAuthorityV1:
        if role == "classifier":
            current = self.authorities.read_current(
                identity,
                expected_role="classifier",
                deadline_at=deadline_at,
                consumed_by=state.reader,
            )
        else:
            current = self.authorities.read_current(
                identity,
                expected_role="source_preparer",
                deadline_at=deadline_at,
                consumed_by=state.reader,
            )
        previous = state.authorities.setdefault(identity, current)
        if (
            previous.grant_ref != current.grant_ref
            or previous.grant != current.grant
            or previous.history_heads != current.history_heads
        ):
            raise _invalid("classification authority changed during verification")
        if state.epoch is None:
            state.observe(
                self._history().read(
                    tuple(
                        head.stream_id
                        for head in current.history_heads
                        if head.stream_kind == "control"
                    ),
                    deadline_at=deadline_at,
                )
            )
        return current

    def _source(
        self,
        command: ClassificationCommand,
        state: _ClassificationRead,
        deadline_at: datetime,
    ) -> FiscalClassificationSource:
        if self.sources is None:
            raise SnapshotError(
                "FISCAL_CLASSIFICATION_SOURCE_UNCONFIGURED",
                "classification requires a trusted source scope resolver",
            )
        admission = state.source_admission
        if admission is None:
            source = self.sources.resolve(
                command.source_validation_ref,
                command.witness_ref,
                command.security_id,
                reader=state.reader,
                check_deadline=partial(self._budget, deadline_at),
                deadline_at=deadline_at,
            )
        else:
            if deadline_at != admission.deadline_at:
                raise _invalid("classification admission deadline changed")
            inputs = canonical_bytes(
                (
                    command.source_validation_ref,
                    command.witness_ref,
                    command.security_id,
                )
            )
            if admission.derivation is None:
                admission.inputs = inputs
                admission.owner = self.sources
                admission.derivation = state.observe_source(
                    self.sources,
                    command,
                    reader=state.reader,
                    check_deadline=partial(self._budget, admission.deadline_at),
                    deadline_at=admission.deadline_at,
                )
            else:
                if inputs != admission.inputs or self.sources is not admission.owner:
                    raise _invalid("classification admission source inputs changed")
                admission.derivation.check_current()
            source = admission.derivation.source
        self._budget(deadline_at)
        if (
            source.scope.source_validation_ref != command.source_validation_ref
            or source.scope.witness_ref != command.witness_ref
        ):
            raise _invalid("source resolver returned a different source or witness")
        return source

    @staticmethod
    def _json(ref: ArtifactRefV1, role: str, state: _ClassificationRead) -> bytes:
        if ref.role != role or ref.media_type != "application/json":
            raise _invalid("classification evidence reference has a different role")
        return read_retained_artifact(state.pure_reader, ref)

    def _review(
        self,
        command: ClassificationCommand,
        source: FiscalClassificationSource,
        state: _ClassificationRead,
        deadline_at: datetime,
    ) -> FiscalSourceAccountingReviewV1:
        raw = self._json(
            command.review_ref, "fiscal-source-accounting-review-v1", state
        )
        review = FiscalSourceAccountingReviewV1.model_validate_json(raw)
        if canonical_bytes(review) != raw:
            raise _invalid("review bytes are not canonical")
        state.verify_review(source, review, partial(self._budget, deadline_at))
        return review

    def _execution(
        self,
        command: ClassificationCommand,
        review: FiscalSourceAccountingReviewV1,
        actor: FiscalClassifierActorV1,
        signed_at: datetime,
        issuance: FiscalIssuanceContextV1,
        authority: CurrentFiscalAuthorityV1,
        source: FiscalClassificationSource,
        state: _ClassificationRead,
        deadline_at: datetime,
    ) -> None:
        identity = authority.grant.identity
        v2 = isinstance(command, FiscalRecordClassificationCommandV2)
        raw = self._json(
            actor.execution_ref,
            "fiscal-classifier-review-execution-v2"
            if v2
            else "fiscal-classifier-review-execution-v1",
            state,
        )
        proof = (
            FiscalClassifierReviewExecutionV2.model_validate_json(raw) if v2 else None
        )
        execution = (
            proof.execution
            if proof
            else FiscalClassifierReviewExecutionV1.model_validate_json(raw)
        )
        if (
            canonical_bytes(proof or execution) != raw
            or actor.authority_id != identity.authority_id
            or actor.principal_id != identity.principal_id
            or actor.principal_kind != identity.principal_kind
            or actor.key_id != identity.key_id
            or execution.authority_id != actor.authority_id
            or execution.principal_id != actor.principal_id
            or execution.principal_kind != actor.principal_kind
            or execution.key_id != actor.key_id
            or execution.command_digest != command.command_digest
            or execution.scope_digest != review.scope.scope_digest
            or execution.review_ref != command.review_ref
            or execution.issuance != issuance
            or execution.completed_at > signed_at
            or execution.started_at < authority.grant.valid_from
        ):
            raise _invalid(
                "review execution does not authenticate the exact command and reviewer"
            )
        signed_preparation: (
            SignedFiscalSourcePreparationExecutionV1
            | SignedFiscalSourcePreparationExecutionV2
        )
        if isinstance(command, FiscalRecordClassificationCommandV2):
            if self.producer_evidence is None or proof is None:
                raise _invalid(
                    "V2 classification requires trusted producer policy verification"
                )
            signed_preparation_v2 = read_source_preparation(
                state.pure_reader, command.preparer_execution_ref
            )
            execution, preparation = state.verify_producer(
                self.producer_evidence,
                command,
                source,
                review,
                proof,
                signed_preparation_v2,
                reader=state.pure_reader,
                check_deadline=partial(self._budget, deadline_at),
                now=self._now(),
            )
            if (
                state.accreditation is not None
                and state.accreditation != proof.accreditation_ref
            ):
                raise _invalid("accounting accreditation changed during observation")
            state.accreditation = proof.accreditation_ref
            signed_preparation = signed_preparation_v2
            if proof.classifier_grant_ref != authority.grant_ref:
                raise _invalid("classifier policy job grant differs")
            raw_preparation = self._json(
                command.preparer_execution_ref,
                "fiscal-source-preparation-execution-v2",
                state,
            )
        else:
            raw_preparation = self._json(
                command.preparer_execution_ref,
                "fiscal-source-preparation-execution-v1",
                state,
            )
            signed_preparation_v1 = (
                SignedFiscalSourcePreparationExecutionV1.model_validate_json(
                    raw_preparation
                )
            )
            preparation = signed_preparation_v1.execution
            signed_preparation = signed_preparation_v1
        preparer = self._authority(
            preparation.authority_id, "source_preparer", state, deadline_at
        )
        preparer_identity = preparer.grant.identity
        if (
            canonical_bytes(signed_preparation) != raw_preparation
            or preparation.source_validation_ref != review.scope.source_validation_ref
            or preparation.source_binding_digest != review.scope.source_binding_digest
            or preparation.runtime != review.scope.runtime
            or preparation.authority_grant_ref != preparer.grant_ref
            or preparation.issuance != issuance
            or preparation.principal_id != preparer_identity.principal_id
            or preparation.principal_kind != preparer_identity.principal_kind
            or preparation.key_id != preparer_identity.key_id
            or not preparer.grant.valid_from
            <= preparation.started_at
            <= preparation.completed_at
            < preparer.grant.valid_until
            or preparation.completed_at > execution.started_at
        ):
            raise _invalid(
                "source preparation does not bind an authenticated source execution"
            )
        _signature(
            signed_preparation.signing_bytes(), signed_preparation.signature, preparer
        )
        witness = source.witness
        principals = (
            preparation.principal_id,
            witness.principal_id,
            actor.principal_id,
        )
        keys = (preparation.key_id, witness.key_id, actor.key_id)
        focus_executions = {
            ref.artifact_id
            for action in witness.witness.actions
            for ref in (action.result_ref, action.delivery_ref)
        }
        if (
            len(set(principals)) != 3
            or len(set(keys)) != 3
            or preparation.execution_id == execution.execution_id
            or preparation.execution_id in focus_executions
            or execution.execution_id in focus_executions
            or command.preparer_execution_ref.artifact_id
            == actor.execution_ref.artifact_id
        ):
            raise _invalid(
                "source preparation, focus validation and classification are not independent"
            )
        state.activities = (
            VerifiedFiscalActivity(
                "source_preparation",
                preparation.authority_id,
                preparation.principal_id,
                preparation.principal_kind,
                preparation.key_id,
                preparer.grant_ref,
                (preparation.execution_id,),
                (command.preparer_execution_ref,),
            ),
            VerifiedFiscalActivity(
                "focus_validation",
                witness.authority_id,
                witness.principal_id,
                None,
                witness.key_id,
                None,
                tuple(sorted(focus_executions)),
                (command.witness_ref,),
            ),
            VerifiedFiscalActivity(
                "source_classification",
                actor.authority_id,
                actor.principal_id,
                actor.principal_kind,
                actor.key_id,
                authority.grant_ref,
                (execution.execution_id,),
                (actor.execution_ref,),
            ),
        )
        if state.epoch is None:
            raise _invalid("classification recovery epoch is unavailable")
        try:
            state.epoch.require_current_issuance(issuance)
            state.epoch.require_current_activity(
                signed_at,
                execution.started_at,
                execution.completed_at,
                preparation.started_at,
                preparation.completed_at,
            )
        except ValueError as error:
            raise _invalid(
                "recovered classification requires fresh issuance and executions"
            ) from error

    @staticmethod
    def _dependencies(signed: SignedClassification) -> tuple[str, ...]:
        command = signed.command
        return tuple(
            sorted(
                {
                    command.source_validation_ref.content_hash,
                    command.witness_ref.content_hash,
                    command.review_ref.content_hash,
                    command.preparer_execution_ref.content_hash,
                    signed.reviewer.execution_ref.content_hash,
                    signed.authority_grant_ref.content_hash,
                    signed.reviewer.key_id,
                    signed.review.scope.scope_digest,
                }
            )
        )

    def _verify(
        self,
        signed: SignedClassification,
        state: _ClassificationRead,
        deadline_at: datetime,
    ) -> None:
        command = signed.command
        source = self._source(command, state, deadline_at)
        review = self._review(command, source, state, deadline_at)
        authority = self._authority(
            command.authority_id, "classifier", state, deadline_at
        )
        if (
            signed.review != review
            or signed.authority_grant_ref != authority.grant_ref
            or not authority.grant.valid_from
            <= signed.signed_at
            < command.expires_at
            <= authority.grant.valid_until
        ):
            raise _invalid(
                "classification differs from review, source, authority or expiry"
            )
        self._execution(
            command,
            review,
            signed.reviewer,
            signed.signed_at,
            signed.issuance,
            authority,
            source,
            state,
            deadline_at,
        )
        _signature(signed.signing_bytes(), signed.signature, authority)
        self._budget(deadline_at)

    def _load(
        self, ref: ArtifactRefV1, state: _ClassificationRead, deadline_at: datetime
    ) -> SignedClassification:
        if ref.role not in {_ROLE, _V2_ROLE}:
            raise _invalid("classification reference version is unsupported")
        raw = self._json(ref, ref.role, state)
        signed = TypeAdapter(SignedClassification).validate_json(raw)
        if (isinstance(signed, SignedFiscalSourceClassificationV2)) != (
            ref.role == _V2_ROLE
        ):
            raise _invalid("classification reference and protocol versions differ")
        if self.require_production_evidence and not isinstance(
            signed, SignedFiscalSourceClassificationV2
        ):
            raise _invalid("production current admission requires V2 producer evidence")
        if (
            canonical_bytes(signed) != raw
            or signed.artifact_id != ref.artifact_id
            or state.reader.get(ref.artifact_id).dependency_hashes
            != self._dependencies(signed)
        ):
            raise _invalid(
                "classification artifact identity or dependency metadata differs"
            )
        self._verify(signed, state, deadline_at)
        return signed

    def _history_state(
        self,
        signed: SignedClassification,
        ref: ArtifactRefV1,
        state: _ClassificationRead,
        deadline_at: datetime,
    ) -> None:
        history = self._history()
        control = history.read(
            ("control:" + self._subject(signed.command),), deadline_at=deadline_at
        )
        if len(control.entries) != 1:
            raise _invalid("classification has no unique committed control record")
        entry = control.entries[0]
        if (
            entry.event.body
            != FiscalControlBindingV1(
                action="classification_recorded",
                payload_ref=ref,
                command_digest=signed.command.command_digest,
            )
            or entry.event.recorded_at < signed.signed_at
            or entry.event.origin_id != signed.issuance.origin_id
        ):
            raise _invalid("classification control event differs from signed evidence")
        try:
            control.require_current_epoch((entry,))
        except SnapshotError as error:
            raise _invalid(
                "recovered classification requires fresh local control evidence"
            ) from error
        state.observe(control)
        records = tuple(
            record for _, record in state.reader.records if record is not None
        )
        evidence = history.read(
            tuple("evidence:" + record.artifact_id for record in records),
            deadline_at=deadline_at,
        )
        selected_entries = []
        for record in records:
            entries = [
                entry
                for entry in evidence.entries
                if entry.event.subject_id == record.artifact_id
            ]
            if not entries or getattr(entries[-1].event.body, "record", None) != record:
                raise _invalid(
                    "consumed classification evidence lacks its current checkpoint"
                )
            selected_entries.append(entries[-1])
        try:
            evidence.require_current_epoch(tuple(selected_entries))
        except SnapshotError as error:
            raise _invalid(
                "classification requires fresh local evidence observations"
            ) from error
        state.observe(evidence)

    def _require_current_epoch(
        self,
        signed: SignedClassification,
        state: _ClassificationRead,
        deadline_at: datetime,
    ) -> None:
        epoch = self._history().read_epoch(deadline_at=deadline_at)
        if state.epoch is not None and epoch != state.epoch:
            raise _invalid("classification recovery epoch changed during verification")
        try:
            epoch.require_current_issuance(signed.issuance)
        except ValueError as error:
            raise _invalid(
                "recovered classification requires fresh local issuance"
            ) from error

    def _finish(
        self,
        signed: SignedClassification,
        state: _ClassificationRead,
        deadline_at: datetime,
    ) -> None:
        records_before = state.reader.records
        source = self._source(signed.command, state, deadline_at)
        if source.scope != signed.review.scope:
            raise _invalid("classification source changed during verification")
        if state.reader.records != records_before:
            raise _invalid("classification consumed evidence changed before return")
        observed: list[datetime] = []
        for identity, previous in state.authorities.items():
            current = self.authorities.read_current(
                identity,
                expected_role=previous.grant.identity.role,
                deadline_at=deadline_at,
                consumed_by=state.reader,
            )
            if (
                current.grant_ref != previous.grant_ref
                or current.grant != previous.grant
                or current.history_heads != previous.history_heads
            ):
                raise _invalid("classification authority changed before return")
            observed.append(current.observed_at)
        state.reader.check_bodies()
        heads = dict(state.heads)
        for authority in state.authorities.values():
            for head in authority.history_heads:
                if heads.setdefault(head.stream_id, head) != head:
                    raise _invalid("classification and authority history heads differ")
        self._history().require_heads(tuple(heads.values()), deadline_at=deadline_at)
        self._require_current_epoch(signed, state, deadline_at)
        state.reader.check_current()
        if isinstance(signed, SignedFiscalSourceClassificationV2):
            if state.epoch is None:
                raise _invalid("classification observation has no recovery epoch")
            whole_observation = self._history().finish_observation(
                tuple(
                    record for _, record in state.reader.records if record is not None
                ),
                tuple(heads.values()),
                state.epoch,
                deadline_at=deadline_at,
            )
            if any(
                not isinstance(entry.commit_bound, FiscalCommitReceiptV1)
                for entry in whole_observation.entries
            ):
                raise _invalid("classification observation is not sealed")
            if self._now() < whole_observation.observed_through:
                raise _invalid("classification clock precedes whole observation")
        now = self._now()
        if state.accreditation is not None and (
            self.producer_evidence is None
            or self.producer_evidence.accreditation() != state.accreditation
        ):
            raise _invalid("accounting accreditation changed before return")
        if state.accreditation is not None:
            if self.producer_evidence is None:
                raise _invalid("accounting accreditation verifier is unavailable")
            self.producer_evidence.require_current(
                state.accreditation,
                signed.command.expires_at,
                reader=state.reader,
                check_deadline=partial(self._budget, deadline_at),
                now=now,
            )
        state.reader.check_bodies()
        now = self._now()
        if now >= deadline_at:
            raise self._expired()
        if now >= signed.command.expires_at or now >= source.witness.expires_at:
            raise _invalid("classification or witness expired before return")
        if any(
            not authority.grant.valid_from <= now < authority.grant.valid_until
            for authority in state.authorities.values()
        ):
            raise _invalid("classification authority expired before return")
        if (state.visible_after is not None and now <= state.visible_after) or any(
            now < at for at in observed
        ):
            raise _invalid("classification clock does not follow sealed visibility")

    def record_classification(
        self,
        command: ClassificationCommand,
        *,
        expected_head: FiscalHistoryHeadV1 | None,
        deadline_at: datetime,
    ) -> FiscalClassificationPublicationV1 | FiscalClassificationPublicationV2:
        with metadata_operation_budget(
            partial(self._budget, deadline_at), self._expired
        ):
            try:
                self._budget(deadline_at)
                self._history()
                command = TypeAdapter(ClassificationCommand).validate_json(
                    canonical_bytes(command)
                )
                if self.require_production_evidence and not isinstance(
                    command, FiscalRecordClassificationCommandV2
                ):
                    raise _invalid(
                        "production classification requires V2 producer evidence"
                    )
                state = _ClassificationRead(
                    FiscalArtifactRead(
                        self.artifacts, partial(self._budget, deadline_at)
                    )
                )
                existing = state.reader.current(command.artifact_id)
                if existing is None:
                    if self.signer is None:
                        raise SnapshotError(
                            "FISCAL_CLASSIFIER_UNCONFIGURED",
                            "classification signing capability is not configured",
                        )
                    source = self._source(command, state, deadline_at)
                    review = self._review(command, source, state, deadline_at)
                    issuance = (
                        self._history()
                        .read_epoch(deadline_at=deadline_at)
                        .issuance_context
                    )
                    actor = self.signer.authenticate(
                        command, review, issuance=issuance, deadline_at=deadline_at
                    )
                    self._budget(deadline_at)
                    authority = self._authority(
                        command.authority_id, "classifier", state, deadline_at
                    )
                    restored = (
                        self.recovery.restore(
                            command,
                            actor=actor,
                            issuance=issuance,
                            deadline_at=deadline_at,
                        )
                        if self.recovery is not None
                        else None
                    )
                    unsigned = restored or TypeAdapter(
                        SignedClassification
                    ).validate_json(
                        canonical_bytes(
                            {
                                "protocol": "fundamental.signed-fiscal-source-classification.v2"
                                if isinstance(
                                    command, FiscalRecordClassificationCommandV2
                                )
                                else "fundamental.signed-fiscal-source-classification.v1",
                                "command": command,
                                "review": review,
                                "reviewer": actor,
                                "authority_grant_ref": authority.grant_ref,
                                "issuance": issuance,
                                "signed_at": self._now(),
                                "signature": "0" * 128,
                            }
                        )
                    )
                    self._execution(
                        command,
                        review,
                        actor,
                        unsigned.signed_at,
                        issuance,
                        authority,
                        source,
                        state,
                        deadline_at,
                    )
                    if command.expires_at > authority.grant.valid_until:
                        raise _invalid(
                            "classification expiry exceeds its authority grant"
                        )
                    if restored is not None:
                        if (
                            restored.command != command
                            or restored.reviewer != actor
                            or restored.issuance != issuance
                            or restored.review != review
                            or restored.authority_grant_ref != authority.grant_ref
                        ):
                            raise _invalid(
                                "classification recovery differs from exact invocation"
                            )
                        signature = restored.signature
                    else:
                        signature = self.signer.sign(
                            unsigned.signing_bytes(),
                            actor=actor,
                            deadline_at=deadline_at,
                        )
                    self._budget(deadline_at)
                    signed = TypeAdapter(SignedClassification).validate_json(
                        canonical_bytes(
                            unsigned.model_copy(update={"signature": signature})
                        )
                    )
                    self._verify(signed, state, deadline_at)
                    state.reader.check_current()
                    publication = self.artifacts.put_bytes_with_receipt(
                        signed.artifact_id,
                        canonical_bytes(signed),
                        self._dependencies(signed),
                        media_type="application/json",
                        publication_budget=partial(self._budget, deadline_at),
                    )
                else:
                    ref = _ref(existing)
                    signed = self._load(ref, state, deadline_at)
                    if signed.command != command:
                        raise SnapshotError(
                            "FISCAL_CLASSIFICATION_COMMAND_REUSED",
                            "classification command identity is immutable",
                        )
                    publication = ArtifactPublicationV1(artifact=existing, wrote=False)
                state.reader.get(command.artifact_id)
                history = self._history()
                if not isinstance(history, FiscalAdmissionHistoryPort):
                    raise _invalid(
                        "classification history write capability is not configured"
                    )
                self._require_current_epoch(signed, state, deadline_at)
                history.checkpoint(
                    tuple(
                        record
                        for _, record in state.reader.records
                        if record is not None
                    ),
                    deadline_at=deadline_at,
                )
                self._require_current_epoch(signed, state, deadline_at)
                history.append_once(
                    self._subject(command),
                    FiscalControlBindingV1(
                        action="classification_recorded",
                        payload_ref=_ref(publication.artifact),
                        command_digest=command.command_digest,
                    ),
                    expected_head=expected_head,
                    deadline_at=deadline_at,
                )
                signed = self._load(_ref(publication.artifact), state, deadline_at)
                self._history_state(
                    signed, _ref(publication.artifact), state, deadline_at
                )
                self._finish(signed, state, deadline_at)
                if isinstance(signed, SignedFiscalSourceClassificationV2):
                    return FiscalClassificationPublicationV2(
                        signed_classification=signed,
                        publication=publication,
                        history_heads=tuple(state.heads.values()),
                    )
                return FiscalClassificationPublicationV1(
                    signed_classification=signed,
                    publication=publication,
                    history_heads=tuple(state.heads.values()),
                )
            except ArtifactPublicationDeadlineExceeded as error:
                raise self._expired() from error
            except (ValueError, DataReleaseError) as error:
                raise _invalid(
                    "classification failed typed evidence verification"
                ) from error

    @contextmanager
    def open_candidate_source(
        self,
        scope: FiscalSourceUseScopeV1,
        classification_refs: tuple[ArtifactRefV1, ...],
        *,
        deadline_at: datetime,
    ) -> Iterator[FiscalClassifiedSourceRead]:
        actor = _classification_actor()
        with metadata_operation_budget(
            partial(self._budget, deadline_at), self._expired
        ):
            read: FiscalClassifiedSourceRead | None = None
            try:
                self._budget(deadline_at)
                if len(classification_refs) != 1:
                    raise _invalid(
                        "this profile requires one exact source classification"
                    )
                state = _ClassificationRead(
                    FiscalArtifactRead(
                        self.artifacts, partial(self._budget, deadline_at)
                    )
                )
                ref = classification_refs[0]
                state.source_admission = _AdmissionSourceRead(deadline_at)
                signed = self._load(ref, state, deadline_at)
                if signed.review.scope != scope:
                    raise _invalid(
                        "classification does not authorize the exact candidate source scope"
                    )
                self._history_state(signed, ref, state, deadline_at)
                read = FiscalClassifiedSourceRead(
                    self, scope, classification_refs, signed, state, deadline_at, actor
                )
                token = _CLASSIFICATION_READS.set((*_CLASSIFICATION_READS.get(), read))
                try:
                    yield read
                finally:
                    _CLASSIFICATION_READS.reset(token)
            except (ValueError, DataReleaseError) as error:
                raise _invalid(
                    "classification failed typed evidence verification"
                ) from error
            finally:
                if read is not None:
                    read.close()

    @contextmanager
    def _open_current_source(
        self,
        scope: FiscalSourceUseScopeV1,
        classification_refs: tuple[ArtifactRefV1, ...],
        binding: FiscalRetainedInputBindingV1,
        *,
        deadline_at: datetime,
    ) -> Iterator[FiscalClassifiedSourceRead]:
        actor = _classification_actor()
        with metadata_operation_budget(
            partial(self._budget, deadline_at), self._expired
        ):
            read: FiscalClassifiedSourceRead | None = None
            try:
                self._budget(deadline_at)
                if len(classification_refs) != 1:
                    raise _invalid(
                        "this profile requires one exact source classification"
                    )
                state = _PreparedClassificationRead(
                    FiscalArtifactRead(
                        self.artifacts, partial(self._budget, deadline_at)
                    ),
                    scope,
                    binding,
                )
                ref = classification_refs[0]
                state.source_admission = _AdmissionSourceRead(deadline_at)
                signed = self._load(ref, state, deadline_at)
                if signed.review.scope != scope:
                    raise _invalid(
                        "classification does not authorize the exact candidate source scope"
                    )
                self._history_state(signed, ref, state, deadline_at)
                read = FiscalClassifiedSourceRead(
                    self, scope, classification_refs, signed, state, deadline_at, actor
                )
                token = _CLASSIFICATION_READS.set((*_CLASSIFICATION_READS.get(), read))
                try:
                    yield read
                finally:
                    _CLASSIFICATION_READS.reset(token)
            except (ValueError, DataReleaseError) as error:
                raise _invalid(
                    "classification failed typed evidence verification"
                ) from error
            finally:
                if read is not None:
                    read.close()

    def require_candidate_source(
        self,
        scope: FiscalSourceUseScopeV1,
        classification_refs: tuple[ArtifactRefV1, ...],
        *,
        deadline_at: datetime,
    ) -> VerifiedClassifiedCandidateSource:
        with self.open_candidate_source(
            scope, classification_refs, deadline_at=deadline_at
        ) as read:
            return read.current()
