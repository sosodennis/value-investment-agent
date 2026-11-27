from __future__ import annotations

import base64
import hashlib
import os
from asyncio import current_task
from collections.abc import Callable
from contextlib import AbstractContextManager, ExitStack, nullcontext
from contextvars import ContextVar, Token
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from threading import get_ident
from types import TracebackType
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import ConfigDict

from .artifact_evidence import read_retained_artifact
from .command_artifacts import EvidenceArtifactStore
from .contracts import StrictModel
from .data_releases import ArtifactRefV1
from .fiscal_admission_authority import FiscalAuthorityOwner
from .fiscal_admission_history import (
    FiscalAdmissionHistoryPort,
    FiscalAdmissionHistoryReaderPort,
    FiscalCommitReceiptV1,
    FiscalControlBindingV1,
    FiscalHistoryHeadV1,
)
from .fiscal_authority_contracts import CurrentFiscalAuthorityV1
from .fiscal_candidate_contracts import (
    FiscalCandidateBodyV3,
    FiscalCandidateContentV2,
    FiscalCandidatePreparationExecutionV2,
    FiscalPrepareCandidateCommandV2,
    FiscalSourceDocumentObservation,
    FiscalStatementCandidateV3,
    VerifiedClassifiedCandidateSource,
    VerifiedFiscalActivity,
    VerifiedFiscalCandidateSource,
    _TrustedCandidateCorrectness,
)
from .fiscal_source_closure import (
    FiscalArtifactRead,
    FiscalArtifactReadSet,
    FiscalSourceContentReadSet,
    fiscal_closure_read_operation,
)
from .fiscal_statement_contracts import FiscalProjectionResultV1
from .fiscal_statement_mapping import (
    fiscal_display_profile_digest,
    fiscal_mapping_policy_digest,
    fiscal_projection_executable_digest,
)
from .fiscal_statement_policy import fiscal_statement_policy
from .fiscal_validation_contracts import FiscalValidationPinV1
from .metadata import metadata_operation_budget
from .parser_action_identity import (
    _CurrentParserResourceOperation,
    _ParserResourceOperation,
    _ResourceCompletion,
)
from .replay import (
    ArtifactPublicationDeadlineExceeded,
    ArtifactPublicationV1,
    ArtifactRecordV1,
)
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError

if TYPE_CHECKING:
    from .fiscal_projection_builder import (
        FiscalCandidateMaterialization,
        FiscalProjectionBuilder,
        _MaterializationRead,
    )

_ROLE = "fiscal-statement-candidate-v3"
_INTENT = "fiscal-candidate-intent-v2"
_SIGNING = "fiscal-candidate-signing-intent-v2"


def fiscal_preparation_executable_digest() -> str:
    root = Path(__file__).parent
    return sha256_digest(
        {
            name: hashlib.sha256(root.joinpath(name).read_bytes()).hexdigest()
            for name in (
                "fiscal_candidate_preparation.py",
                "fiscal_preparation_runtime.py",
                "fiscal_projection_builder.py",
                "fiscal_candidate_contracts.py",
                "fiscal_source_classification.py",
                "fiscal_admission_history.py",
            )
        }
    )


class FiscalCandidateIntentV2(StrictModel):
    model_config = ConfigDict(frozen=True)
    protocol: Literal["fundamental.fiscal-candidate-intent.v2"] = (
        "fundamental.fiscal-candidate-intent.v2"
    )
    command: FiscalPrepareCandidateCommandV2
    authority_id: str
    materialization: FiscalValidationPinV1
    mapping_policy_digest: str
    display_profile_digest: str
    projection_policy_digest: str
    executable_digest: str
    preparation_executable_digest: str


class FiscalCandidateSigningIntentV2(StrictModel):
    model_config = ConfigDict(frozen=True)
    protocol: Literal["fundamental.fiscal-candidate-signing-intent.v2"] = (
        "fundamental.fiscal-candidate-signing-intent.v2"
    )
    intent_ref: ArtifactRefV1
    body: FiscalCandidateBodyV3


@dataclass(frozen=True)
class CurrentFiscalCandidate:
    reference: ArtifactRefV1
    candidate: FiscalStatementCandidateV3
    projection: FiscalProjectionResultV1
    preparation: VerifiedFiscalActivity
    source_evidence: tuple[VerifiedFiscalCandidateSource, ...]
    candidate_publication: ArtifactPublicationV1
    consumed_metadata: tuple[ArtifactRecordV1, ...]
    history_heads: tuple[FiscalHistoryHeadV1, ...]
    observed_at: datetime
    source_documents: tuple[FiscalSourceDocumentObservation, ...]
    artifact_readset: FiscalArtifactReadSet
    content_readsets: tuple[FiscalSourceContentReadSet, ...]

    @property
    def content(self) -> FiscalCandidateContentV2:
        return self.candidate.body.content


def _invalid(message: str) -> SnapshotError:
    return SnapshotError("FISCAL_CANDIDATE_INVALID", message)


def _ref(record: ArtifactRecordV1, role: str) -> ArtifactRefV1:
    return ArtifactRefV1(
        role=role,
        artifact_id=record.artifact_id,
        content_hash=record.content_hash,
        media_type=record.media_type,
    )


def _no_read_cut() -> None:
    pass


def _unretained_read_operation() -> AbstractContextManager[Callable[[], None]]:
    return nullcontext(_no_read_cut)


class FiscalCandidatePreparation:
    def __init__(
        self,
        *,
        builder: FiscalProjectionBuilder,
        artifacts: EvidenceArtifactStore,
        read_artifacts: EvidenceArtifactStore,
        history: FiscalAdmissionHistoryReaderPort,
        authorities: FiscalAuthorityOwner,
        authority_id: str,
        capture_lock: Callable[[str, datetime], AbstractContextManager[None]]
        | None = None,
        private_key: Callable[[], Ed25519PrivateKey] | None = None,
        configuration_digest: Callable[[], str],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        read_operation: Callable[
            [], AbstractContextManager[Callable[[], None]]
        ] = _unretained_read_operation,
    ) -> None:
        self._builder = builder
        self._read_artifacts = read_artifacts
        self.artifacts, self.history, self.authorities = artifacts, history, authorities
        self.authority_id, self.clock = authority_id, clock
        self._configuration_digest = configuration_digest
        self._capture_lock, self._private_key = capture_lock, private_key
        self.read_operation = read_operation

    def current_configuration_digest(self) -> str:
        return self._configuration_digest()

    @staticmethod
    def _expired() -> SnapshotError:
        return SnapshotError(
            "REQUEST_DEADLINE_EXCEEDED", "candidate deadline expired", retryable=True
        )

    def _now(self) -> datetime:
        now = self.clock()
        if now.utcoffset() is None:
            raise _invalid("candidate clock must be timezone aware")
        return now

    def _budget(self, deadline_at: datetime) -> float:
        now = self._now()
        if deadline_at.utcoffset() is None or now >= deadline_at:
            raise self._expired()
        return (deadline_at - now).total_seconds()

    def _intent(
        self, builder: FiscalProjectionBuilder, command: FiscalPrepareCandidateCommandV2
    ) -> FiscalCandidateIntentV2:
        return FiscalCandidateIntentV2(
            command=command,
            authority_id=self.authority_id,
            materialization=builder.pin,
            mapping_policy_digest=fiscal_mapping_policy_digest(),
            display_profile_digest=fiscal_display_profile_digest(),
            projection_policy_digest=fiscal_statement_policy().digest,
            executable_digest=fiscal_projection_executable_digest(),
            preparation_executable_digest=fiscal_preparation_executable_digest(),
        )

    def _retain(
        self,
        identity: str,
        value: object,
        dependencies: tuple[str, ...],
        budget: Callable[[], float],
    ) -> ArtifactPublicationV1:
        return self.artifacts.put_with_receipt(
            identity, value, tuple(sorted(set(dependencies))), publication_budget=budget
        )

    def _load(
        self, reader: FiscalArtifactRead, reference: ArtifactRefV1
    ) -> FiscalStatementCandidateV3:
        raw = read_retained_artifact(reader, reference)
        signed = FiscalStatementCandidateV3.model_validate_json(raw)
        if (
            reference.role != _ROLE
            or reference.artifact_id != signed.artifact_id
            or canonical_bytes(signed) != raw
        ):
            raise _invalid("candidate reference or canonical bytes differ")
        return signed

    def _authority(
        self,
        signed: FiscalStatementCandidateV3,
        deadline_at: datetime,
        consumed_by: FiscalArtifactRead | None = None,
    ) -> CurrentFiscalAuthorityV1:
        body, execution = signed.body, signed.body.preparation
        authority = self.authorities.read_current(
            execution.authority_id,
            expected_role="source_preparer",
            deadline_at=deadline_at,
            consumed_by=consumed_by,
        )
        identity = authority.grant.identity
        if (
            signed.body.correctness.closure_contract_digest
            != self._builder.closure_contract_digest()
            or execution.closure_contract_digest
            != self._builder.closure_contract_digest()
            or execution.preparation_executable_digest
            != fiscal_preparation_executable_digest()
            or execution.authority_id != self.authority_id
            or execution.grant_ref != authority.grant_ref
            or identity.principal_kind != "machine"
            or execution.principal_id != identity.principal_id
            or execution.key_id != identity.key_id
            or not authority.grant.valid_from
            <= execution.started_at
            <= execution.completed_at
            <= body.signed_at
            < body.command.expires_at
            <= authority.grant.valid_until
        ):
            raise _invalid(
                "candidate preparation differs from its current machine grant"
            )
        try:
            Ed25519PublicKey.from_public_bytes(
                base64.b64decode(identity.public_key_ed25519_base64, validate=True)
            ).verify(bytes.fromhex(signed.signature), signed.signing_bytes())
        except (InvalidSignature, ValueError) as error:
            raise _invalid("candidate preparation signature is invalid") from error
        return authority

    @staticmethod
    def _dependencies(
        intent: FiscalCandidateIntentV2, marker: FiscalCandidateSigningIntentV2
    ) -> tuple[str, ...]:
        body = marker.body
        return tuple(
            sorted(
                {
                    sha256_digest(intent),
                    sha256_digest(marker),
                    body.content.content_digest,
                    body.preparation.grant_ref.content_hash,
                    *body.content.dependency_hashes,
                }
            )
        )

    def _finish(
        self,
        builder: FiscalProjectionBuilder,
        signed: FiscalStatementCandidateV3,
        publication: ArtifactPublicationV1,
        materialized: FiscalCandidateMaterialization,
        *,
        resources: _ResourceCompletion,
        deadline_at: datetime,
        configuration_generation: str,
        seal_read_operation: Callable[[], None],
    ) -> CurrentFiscalCandidate:
        budget = partial(self._budget, deadline_at)
        if signed.body.correctness != materialized.correctness:
            raise _invalid(
                "candidate correctness differs from actual current owner closure"
            )
        reader = FiscalArtifactRead(self._read_artifacts, budget)
        reader.enroll(materialized.artifact_readset)
        for record in materialized.consumed_metadata:
            reader.expect(record.artifact_id, record)
        reference = _ref(publication.artifact, _ROLE)
        if self._load(reader, reference) != signed:
            raise _invalid("candidate changed before completion")
        intent = self._intent(builder, signed.body.command)
        marker = FiscalCandidateSigningIntentV2(
            intent_ref=_ref(
                reader.get(signed.body.command.artifact_id(_INTENT)), _INTENT
            ),
            body=signed.body,
        )
        for role, value in ((_INTENT, intent), (_SIGNING, marker)):
            if read_retained_artifact(
                reader, _ref(reader.get(signed.body.command.artifact_id(role)), role)
            ) != canonical_bytes(value):
                raise _invalid(
                    "candidate durable intent differs from the fixed signed body"
                )
        if publication.artifact.dependency_hashes != self._dependencies(intent, marker):
            raise _invalid("candidate dependency metadata differs")
        authority = self._authority(signed, deadline_at, reader)
        heads = {head.stream_id: head for head in authority.history_heads}
        expiries = [signed.body.command.expires_at, authority.grant.valid_until]
        for proof in materialized.source_evidence:
            if isinstance(proof, VerifiedClassifiedCandidateSource):
                expiries.extend(proof.expires_at)
                for record in proof.consumed_metadata:
                    reader.expect(record.artifact_id, record)
                for head in proof.history_heads:
                    if heads.setdefault(head.stream_id, head) != head:
                        raise _invalid(
                            "candidate dependencies have conflicting history heads"
                        )
        for head in authority.history_heads:
            if head.stream_kind == "evidence":
                reader.get(head.subject_id)
        epoch = self.history.read_epoch(deadline_at=deadline_at)
        try:
            epoch.require_current_issuance(signed.body.issuance)
            epoch.require_current_activity(
                signed.body.preparation.started_at,
                signed.body.preparation.completed_at,
                signed.body.signed_at,
            )
        except ValueError as error:
            raise _invalid(
                "candidate requires a genuine current-epoch invocation"
            ) from error
        control = self.history.read(
            ("control:candidate-preparation:" + signed.body.command.locator_digest,),
            deadline_at=deadline_at,
        )
        expected = FiscalControlBindingV1(
            action="candidate_prepared",
            payload_ref=reference,
            command_digest=signed.body.command.command_digest,
        )
        if (
            len(control.entries) != 1
            or control.entries[0].event.body != expected
            or control.entries[0].event.origin_id != signed.body.issuance.origin_id
            or control.entries[0].event.recorded_at < signed.body.signed_at
        ):
            raise _invalid("candidate has no exact selected preparation control")
        control.require_current_epoch(control.entries)
        heads.update({head.stream_id: head for head in control.heads})
        resources.seal()
        for readset in materialized.content_readsets:
            readset.check_current(budget)
        reader.check_bodies()
        reader.check_current()
        final_authority = self._authority(signed, deadline_at, reader)
        if (
            final_authority.grant_ref != authority.grant_ref
            or final_authority.grant != authority.grant
            or final_authority.history_heads != authority.history_heads
        ):
            raise _invalid("candidate grant changed before whole observation")
        reader.check_bodies()
        records = tuple(record for _, record in reader.records if record is not None)
        seal_read_operation()
        observed = self.history.finish_observation(
            records, tuple(heads.values()), epoch, deadline_at=deadline_at
        )
        if self._configuration_digest() != configuration_generation:
            raise _invalid(
                "candidate deployment configuration changed during whole observation"
            )
        if self._intent(builder, signed.body.command) != intent:
            raise _invalid("candidate build or policy changed before return")
        now = self._now()
        if any(now >= expiry for expiry in expiries):
            raise _invalid("candidate or dependency expired before return")
        if any(
            not isinstance(entry.commit_bound, FiscalCommitReceiptV1)
            or now <= entry.commit_bound.visible_by
            for entry in observed.entries
        ):
            raise _invalid("candidate clock does not follow sealed visibility")
        if now < observed.observed_through or now < authority.observed_at:
            raise _invalid("candidate clock precedes trusted observation")
        budget()
        execution = signed.body.preparation
        return CurrentFiscalCandidate(
            reference,
            signed,
            materialized.projection,
            VerifiedFiscalActivity(
                "candidate_preparation",
                execution.authority_id,
                execution.principal_id,
                execution.principal_kind,
                execution.key_id,
                execution.grant_ref,
                (execution.execution_id,),
                (reference,),
            ),
            materialized.source_evidence,
            publication,
            records,
            observed.heads,
            now,
            materialized.source_documents,
            reader.readset,
            materialized.content_readsets,
        )

    def open_candidate(
        self, reference: ArtifactRefV1, *, deadline_at: datetime
    ) -> FiscalCandidateOperation:
        return FiscalCandidateOperation(self, reference, deadline_at)

    def _open_display_candidate(
        self, reference: ArtifactRefV1, *, deadline_at: datetime
    ) -> _FiscalCandidateSession:
        return _FiscalCandidateSession(self, reference, deadline_at)

    def verify_candidate(
        self, reference: ArtifactRefV1, *, deadline_at: datetime
    ) -> CurrentFiscalCandidate:
        operation = self.open_candidate(reference, deadline_at=deadline_at)
        with operation:
            pass
        return operation.completed

    def replay_candidate(
        self, reference: ArtifactRefV1, *, deadline_at: datetime
    ) -> CurrentFiscalCandidate:
        operation = _FiscalCandidateReplayOperation(self, reference, deadline_at)
        with operation:
            pass
        return operation.completed

    def prepare(
        self, command: FiscalPrepareCandidateCommandV2, *, deadline_at: datetime
    ) -> CurrentFiscalCandidate:
        with metadata_operation_budget(
            partial(self._budget, deadline_at), self._expired
        ):
            try:
                if self._capture_lock is None or self._private_key is None:
                    raise SnapshotError(
                        "FISCAL_CANDIDATE_PREPARATION_UNCONFIGURED",
                        "candidate write capability is not configured",
                    )
                command = FiscalPrepareCandidateCommandV2.model_validate_json(
                    canonical_bytes(command)
                )
                with (
                    fiscal_closure_read_operation(),
                    self._capture_lock(
                        sha256_digest(("fiscal-candidate", command.command_id)),
                        deadline_at,
                    ),
                    _ParserResourceOperation(
                        partial(self._budget, deadline_at)
                    ) as resources,
                    ExitStack() as materializations,
                ):
                    return self._prepare_locked(
                        self._builder,
                        command,
                        deadline_at,
                        resources=resources,
                        materializations=materializations,
                    )
            except ArtifactPublicationDeadlineExceeded as error:
                raise self._expired() from error
            except ValueError as error:
                raise _invalid(
                    "candidate failed typed evidence verification"
                ) from error

    def _prepare_locked(
        self,
        builder: FiscalProjectionBuilder,
        command: FiscalPrepareCandidateCommandV2,
        deadline_at: datetime,
        *,
        resources: _ParserResourceOperation,
        materializations: ExitStack,
    ) -> CurrentFiscalCandidate:
        budget = partial(self._budget, deadline_at)
        configuration_generation = self._configuration_digest()
        if self._now() >= command.expires_at:
            raise _invalid("candidate command is already expired")
        reader = FiscalArtifactRead(self._read_artifacts, budget)
        intent = self._intent(builder, command)
        previous = reader.current(command.artifact_id(_INTENT))
        reader.expect(command.artifact_id(_INTENT), previous)
        if previous is not None and reader.read(
            previous.artifact_id
        ) != canonical_bytes(intent):
            raise SnapshotError(
                "FISCAL_CANDIDATE_COMMAND_REUSED",
                "candidate command intent is immutable",
            )
        intent_publication = self._retain(
            command.artifact_id(_INTENT),
            intent,
            (command.discovery_ref.content_hash,),
            budget,
        )
        if previous is None:
            reader.accept_own_publication(intent_publication, canonical_bytes(intent))
        existing = reader.current(command.artifact_id(_ROLE))
        marker = reader.current(command.artifact_id(_SIGNING))
        reader.expect(command.artifact_id(_ROLE), existing)
        reader.expect(command.artifact_id(_SIGNING), marker)
        materialization: _MaterializationRead
        if existing is not None:
            signed = self._load(reader, _ref(existing, _ROLE))
            if signed.body.command != command:
                raise SnapshotError(
                    "FISCAL_CANDIDATE_COMMAND_REUSED",
                    "candidate command identity is immutable",
                )
            self._authority(signed, deadline_at)
            materialization = materializations.enter_context(
                builder._open_current_materialization(
                    _TrustedCandidateCorrectness(signed, materializations),
                    deadline_at=deadline_at,
                )
            )
            materialized = materialization.current()
            if materialized.content != signed.body.content:
                raise _invalid(
                    "candidate does not reproduce from its complete current source closure"
                )
            publication = ArtifactPublicationV1(artifact=existing, wrote=False)
        else:
            if marker is not None:
                raise SnapshotError(
                    "FISCAL_CANDIDATE_SIGNING_OUTCOME_UNAVAILABLE",
                    "signing started but no durable signed outcome is provable",
                )
            authority = self.authorities.read_current(
                self.authority_id,
                expected_role="source_preparer",
                deadline_at=deadline_at,
            )
            identity = authority.grant.identity
            if identity.principal_kind != "machine":
                raise _invalid(
                    "automatic candidate preparation requires a machine principal"
                )
            if self._private_key is None:
                raise _invalid("candidate signing capability disappeared")
            key = self._private_key()
            if key.public_key().public_bytes_raw() != base64.b64decode(
                identity.public_key_ed25519_base64, validate=True
            ):
                raise _invalid(
                    "candidate deployment key differs from the current grant"
                )
            epoch = self.history.read_epoch(deadline_at=deadline_at)
            issuance = epoch.issuance_context
            started_at = self._now()
            execution_id = "candidate-job:" + uuid4().hex
            materialization = materializations.enter_context(
                builder._open_materialization(
                    command.discovery_ref,
                    security_id=command.security_id,
                    classification_bindings=command.classification_bindings,
                    deadline_at=deadline_at,
                    publish=True,
                )
            )
            materialized = materialization.current()
            derived = materializations.enter_context(
                builder._derive_current_materialization(
                    materialized.content, deadline_at=deadline_at
                )
            )
            independently_read = derived.current()
            if (
                independently_read.content != materialized.content
                or independently_read.projection != materialized.projection
                or independently_read.correctness != materialized.correctness
            ):
                raise _invalid(
                    "full actual consumption differs from independently derived typed closure"
                )
            materialization = derived
            materialized = independently_read
            completed_at = self._now()
            current = self.authorities.read_current(
                self.authority_id,
                expected_role="source_preparer",
                deadline_at=deadline_at,
            )
            if (
                current.grant != authority.grant
                or current.grant_ref != authority.grant_ref
                or current.history_heads != authority.history_heads
                or self.history.read_epoch(deadline_at=deadline_at) != epoch
            ):
                raise _invalid(
                    "candidate authority or epoch changed during actual invocation"
                )
            epoch.require_current_activity(started_at, completed_at)
            if (
                not authority.grant.valid_from
                <= started_at
                <= completed_at
                < command.expires_at
                <= authority.grant.valid_until
            ):
                raise _invalid("candidate expiry or execution exceeds its grant")
            for record in materialized.consumed_metadata:
                reader.expect(record.artifact_id, record)
            reader.check_current()
            body = FiscalCandidateBodyV3(
                command=command,
                content=materialized.content,
                correctness=materialized.correctness,
                preparation=FiscalCandidatePreparationExecutionV2(
                    authority_id=self.authority_id,
                    grant_ref=authority.grant_ref,
                    principal_id=identity.principal_id,
                    key_id=identity.key_id,
                    execution_id=execution_id,
                    issuance=issuance,
                    command_digest=command.command_digest,
                    content_digest=materialized.content.content_digest,
                    correctness_digest=sha256_digest(materialized.correctness),
                    closure_contract_digest=materialized.correctness.closure_contract_digest,
                    preparation_executable_digest=fiscal_preparation_executable_digest(),
                    started_at=started_at,
                    completed_at=completed_at,
                ),
                issuance=issuance,
                signed_at=self._now(),
            )
            signing = FiscalCandidateSigningIntentV2(
                intent_ref=_ref(intent_publication.artifact, _INTENT), body=body
            )
            signing_publication = self._retain(
                command.artifact_id(_SIGNING),
                signing,
                (sha256_digest(intent), body.content.content_digest),
                budget,
            )
            if not signing_publication.wrote:
                raise SnapshotError(
                    "FISCAL_CANDIDATE_SIGNING_OUTCOME_UNAVAILABLE",
                    "only the first live invocation may sign its frozen body",
                )
            reader.accept_own_publication(signing_publication, canonical_bytes(signing))
            budget()
            signed = FiscalStatementCandidateV3(
                body=body, signature=key.sign(canonical_bytes(body)).hex()
            )
            budget()
            publication = self._retain(
                signed.artifact_id, signed, self._dependencies(intent, signing), budget
            )
            reader.accept_own_publication(publication, canonical_bytes(signed))
            self._authority(signed, deadline_at)
        epoch = self.history.read_epoch(deadline_at=deadline_at)
        epoch.require_current_issuance(signed.body.issuance)
        records = {
            record.artifact_id: record for record in materialized.consumed_metadata
        }
        for role in (_INTENT, _SIGNING, _ROLE):
            record = self._read_artifacts.get(command.artifact_id(role))
            records[record.artifact_id] = record
        authority = self._authority(signed, deadline_at)
        for head in authority.history_heads:
            if head.stream_kind == "evidence":
                records[head.subject_id] = self._read_artifacts.get(head.subject_id)
        if not isinstance(self.history, FiscalAdmissionHistoryPort):
            raise _invalid("candidate history write capability is not configured")
        values = tuple(sorted(records.values(), key=lambda record: record.artifact_id))
        for start in range(0, len(values), 256):
            self.history.checkpoint(
                values[start : start + 256], deadline_at=deadline_at
            )
        self.history.append_once(
            "candidate-preparation:" + command.locator_digest,
            FiscalControlBindingV1(
                action="candidate_prepared",
                payload_ref=_ref(publication.artifact, _ROLE),
                command_digest=command.command_digest,
            ),
            expected_head=None,
            deadline_at=deadline_at,
        )
        materialized = materialization.current()
        materializations.close()
        return self._finish(
            builder,
            signed,
            publication,
            materialized,
            resources=resources.completion(terminal=True),
            deadline_at=deadline_at,
            configuration_generation=configuration_generation,
            seal_read_operation=_no_read_cut,
        )


class FiscalCandidateRead(Protocol):
    def current(self) -> CurrentFiscalCandidate: ...


_CANDIDATE_OPERATION: ContextVar[_FiscalCandidateSession | None] = ContextVar(
    "fiscal_candidate_operation", default=None
)


def _candidate_actor() -> tuple[object, ...]:
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


class _FiscalCandidateSession:
    def __init__(
        self,
        owner: FiscalCandidatePreparation,
        reference: ArtifactRefV1,
        deadline_at: datetime,
    ) -> None:
        self._owner, self._reference, self._deadline_at = (
            owner,
            deepcopy(reference),
            deadline_at,
        )
        self._phase: Literal["new", "open", "completed", "failed"] = "new"
        self._scope, self._children = ExitStack(), ExitStack()
        self._token: Token[_FiscalCandidateSession | None] | None = None
        self._result: CurrentFiscalCandidate | None = None
        self._materialization: _MaterializationRead | None = None
        self._resources: _ParserResourceOperation | None = None
        self._signed: FiscalStatementCandidateV3 | None = None
        self._publication: ArtifactPublicationV1 | None = None
        self._generation = ""
        self._actor = _candidate_actor()
        self._owners = (
            owner._builder,
            owner.artifacts,
            owner._read_artifacts,
            owner.history,
            owner.authorities,
            owner.authority_id,
            owner._configuration_digest,
            owner.clock,
            owner.read_operation,
        )

    def _require(self) -> None:
        owner = self._owner
        if (
            self._phase != "open"
            or _CANDIDATE_OPERATION.get() is not self
            or self._actor != _candidate_actor()
        ):
            raise _invalid(
                "candidate observation is closed or belongs to another execution"
            )
        if self._owners != (
            owner._builder,
            owner.artifacts,
            owner._read_artifacts,
            owner.history,
            owner.authorities,
            owner.authority_id,
            owner._configuration_digest,
            owner.clock,
            owner.read_operation,
        ):
            raise _invalid("candidate configured owner changed")

    def _require_new(self) -> None:
        if self._phase != "new" or self._actor != _candidate_actor():
            raise _invalid("candidate observation cannot reopen or change execution")

    def _open(self) -> None:
        self._require_new()
        self._phase = "open"
        self._token = _CANDIDATE_OPERATION.set(self)
        owner = self._owner
        self._scope.enter_context(fiscal_closure_read_operation())
        self._scope.enter_context(
            metadata_operation_budget(
                partial(owner._budget, self._deadline_at), owner._expired
            )
        )
        self._resources = self._scope.enter_context(self._resource_operation())

    def _resource_operation(self) -> _ParserResourceOperation:
        return _CurrentParserResourceOperation(
            partial(self._owner._budget, self._deadline_at), self._require
        )

    def _open_materialization(
        self, trusted: _TrustedCandidateCorrectness
    ) -> AbstractContextManager[_MaterializationRead]:
        return self._owner._builder._open_current_materialization(
            trusted, deadline_at=self._deadline_at
        )

    def _current(self, *, terminal: bool) -> CurrentFiscalCandidate:
        first = self._phase == "new"
        if first:
            self._open()
        self._require()
        if self._resources is None:
            raise _invalid("candidate observation has no resource owner")
        owner = self._owner
        with (
            self._resources.current_cut(terminal=terminal) as resource_completion,
            owner.read_operation() as seal_read_operation,
        ):
            if first:
                self._generation = owner.current_configuration_digest()
                reader = FiscalArtifactRead(
                    owner._read_artifacts, partial(owner._budget, self._deadline_at)
                )
                self._signed = owner._load(reader, self._reference)
                owner._authority(self._signed, self._deadline_at)
                self._materialization = self._children.enter_context(
                    self._open_materialization(
                        _TrustedCandidateCorrectness(self._signed, self)
                    )
                )
                self._publication = ArtifactPublicationV1(
                    artifact=reader.get(self._reference.artifact_id), wrote=False
                )
            return self._current_in_scope(
                terminal=terminal,
                seal_read_operation=seal_read_operation,
                resource_completion=resource_completion,
            )

    def _current_in_scope(
        self,
        *,
        terminal: bool,
        seal_read_operation: Callable[[], None],
        resource_completion: _ResourceCompletion,
    ) -> CurrentFiscalCandidate:
        self._require()
        if (
            self._materialization is None
            or self._signed is None
            or self._publication is None
            or self._resources is None
        ):
            raise _invalid("candidate observation has no complete first proof")
        materialized = self._materialization.current()
        if materialized.content != self._signed.body.content:
            raise _invalid(
                "candidate does not reproduce from its complete current source closure"
            )
        if terminal:
            self._children.close()
        return self._owner._finish(
            self._owner._builder,
            self._signed,
            self._publication,
            materialized,
            resources=resource_completion,
            deadline_at=self._deadline_at,
            configuration_generation=self._generation,
            seal_read_operation=seal_read_operation,
        )

    def sample(self) -> CurrentFiscalCandidate:
        if self._actor != _candidate_actor():
            raise _invalid("candidate observation belongs to another execution")
        try:
            return deepcopy(self._current(terminal=False))
        except BaseException as error:
            self.abort(error)
            if isinstance(error, ValueError):
                raise _invalid(
                    "candidate failed typed evidence verification"
                ) from error
            raise

    def abort(self, error: BaseException) -> None:
        if self._actor != _candidate_actor():
            raise _invalid("candidate observation belongs to another execution")
        self._phase = "failed"
        self._cleanup(type(error), error, error.__traceback__)

    def _cleanup(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        cleanup_error: BaseException | None = None
        try:
            for stack in (self._children, self._scope):
                try:
                    stack.__exit__(exc_type, exc, tb)
                except BaseException as error:
                    if exc is None and cleanup_error is None:
                        cleanup_error = error
        finally:
            if self._token is not None:
                _CANDIDATE_OPERATION.reset(self._token)
                self._token = None
            self._materialization = None
            self._signed = None
            self._publication = None
        if cleanup_error is not None:
            self._phase = "failed"
            raise cleanup_error

    def finish(self) -> CurrentFiscalCandidate:
        if self._actor != _candidate_actor():
            raise _invalid("candidate observation belongs to another execution")
        try:
            self._require()
            result = deepcopy(self._current(terminal=True))
            self._cleanup(None, None, None)
        except BaseException as error:
            self.abort(error)
            if isinstance(error, ValueError):
                raise _invalid(
                    "candidate failed typed evidence verification"
                ) from error
            raise
        self._result = result
        self._phase = "completed"
        return deepcopy(result)

    @property
    def completed(self) -> CurrentFiscalCandidate:
        if self._phase != "completed" or self._result is None:
            raise _invalid("candidate observation did not complete")
        return deepcopy(self._result)


class _FiscalCandidateReplaySession(_FiscalCandidateSession):
    def _resource_operation(self) -> _ParserResourceOperation:
        return _ParserResourceOperation(partial(self._owner._budget, self._deadline_at))

    def _open_materialization(
        self, trusted: _TrustedCandidateCorrectness
    ) -> AbstractContextManager[_MaterializationRead]:
        body = trusted.candidate.body
        return self._owner._builder._open_materialization(
            body.content.discovery_ref,
            security_id=body.command.security_id,
            classification_bindings=body.command.classification_bindings,
            deadline_at=self._deadline_at,
            publish=False,
            retained_mapping_refs=body.content.mapping_refs,
        )


class FiscalCandidateOperation(AbstractContextManager[FiscalCandidateRead]):
    def __init__(
        self,
        owner: FiscalCandidatePreparation,
        reference: ArtifactRefV1,
        deadline_at: datetime,
    ) -> None:
        self._session = _FiscalCandidateSession(owner, reference, deadline_at)

    def __enter__(self) -> FiscalCandidateRead:
        self._session._require_new()
        self._session.sample()
        return self

    def current(self) -> CurrentFiscalCandidate:
        self._session._require()
        return self._session.sample()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        if exc is None:
            self._session.finish()
        else:
            self._session.abort(exc)
        return False

    @property
    def completed(self) -> CurrentFiscalCandidate:
        return self._session.completed


class _FiscalCandidateReplayOperation(FiscalCandidateOperation):
    def __init__(
        self,
        owner: FiscalCandidatePreparation,
        reference: ArtifactRefV1,
        deadline_at: datetime,
    ) -> None:
        self._session = _FiscalCandidateReplaySession(owner, reference, deadline_at)
