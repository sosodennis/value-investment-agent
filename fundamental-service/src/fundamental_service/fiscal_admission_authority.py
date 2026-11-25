from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Literal, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .command_artifacts import EvidenceArtifactStore
from .data_releases import ArtifactRefV1
from .fiscal_admission_history import (
    FiscalAdmissionHistoryPort,
    FiscalCommitReceiptV1,
    FiscalControlBindingV1,
    FiscalHistoryEntryV1,
    FiscalHistoryHeadV1,
)
from .fiscal_authority_contracts import (
    CurrentFiscalAuthorityV1,
    FiscalAuthorityCommandV1,
    FiscalAuthorityDeploymentV1,
    FiscalAuthorityGrantV1,
    FiscalAuthorityPublicationV1,
    FiscalAuthorityRevocationV1,
    FiscalAuthorityRole,
    FiscalConfiguredAuthorityV1,
    FiscalConfiguredRegistryRootV1,
    FiscalGrantAuthorityCommandV1,
    FiscalRegistryExecutionV1,
    FiscalRegistryOperatorV1,
    FiscalRevokeAuthorityCommandV1,
    HistoricalFiscalAuthorityExplanationV1,
    SignedFiscalAuthorityRecordV1,
    fiscal_authority_command_artifact_id,
    fiscal_authority_command_digest,
)
from .metadata import metadata_operation_budget
from .replay import ArtifactPublicationV1, ArtifactRecordV1
from .serialization import canonical_bytes
from .snapshots import SnapshotError

_RECORD_ROLE = "fiscal-authority-record-v1"
_MAX_GRANT_AGE = timedelta(days=30)


class FiscalRegistrySignerPort(Protocol):
    def authenticate(
        self, command: FiscalAuthorityCommandV1, *, deadline_at: datetime
    ) -> FiscalRegistryOperatorV1: ...

    def sign(
        self,
        message: bytes,
        *,
        operator: FiscalRegistryOperatorV1,
        deadline_at: datetime,
    ) -> str: ...


def _ref(record: ArtifactRecordV1) -> ArtifactRefV1:
    return ArtifactRefV1(
        role=_RECORD_ROLE,
        artifact_id=record.artifact_id,
        content_hash=record.content_hash,
        media_type=record.media_type,
    )


def _invalid(message: str) -> SnapshotError:
    return SnapshotError("FISCAL_AUTHORITY_INVALID", message)


def _refused(message: str) -> SnapshotError:
    return SnapshotError("FISCAL_AUTHORITY_REFUSED", message)


class _AuthorityRead:
    def __init__(
        self,
        artifacts: EvidenceArtifactStore,
        budget: Callable[[], float],
        *,
        historical: bool = False,
    ) -> None:
        self._artifacts = artifacts
        self._budget = budget
        self.historical = historical
        self.records: dict[str, ArtifactRecordV1] = {}
        self.visible_after: datetime | None = None

    def get(self, identity: str) -> ArtifactRecordV1:
        self._budget()
        record = self._artifacts.get(identity)
        self._budget()
        if (
            record.artifact_id != identity
            or not self.historical
            and (record.status != "valid" or record.retention != "evidence")
        ):
            raise _invalid("authority requires retained evidence metadata")
        previous = self.records.setdefault(identity, record)
        if record != previous:
            raise _invalid("authority evidence metadata changed")
        return record

    def read(self, ref: ArtifactRefV1) -> bytes:
        record = self.get(ref.artifact_id)
        if (
            record.content_hash != ref.content_hash
            or record.media_type != ref.media_type
        ):
            raise _invalid("authority evidence reference differs")
        raw = self._artifacts.read(ref.artifact_id)
        self._budget()
        if hashlib.sha256(raw).hexdigest() != ref.content_hash:
            raise _invalid("authority evidence bytes differ")
        return raw

    def expect(self, ref: ArtifactRefV1, value: object) -> None:
        if ref.media_type != "application/json" or self.read(ref) != canonical_bytes(
            value
        ):
            raise _invalid("authority evidence does not match its typed record")

    def check_current(self) -> None:
        for identity, expected in self.records.items():
            self._budget()
            if self._artifacts.get(identity) != expected:
                raise _invalid("authority evidence metadata changed")
        self._budget()

    def observe_commits(self, entries: tuple[FiscalHistoryEntryV1, ...]) -> None:
        for entry in entries:
            bound = entry.commit_bound
            if not isinstance(bound, FiscalCommitReceiptV1):
                raise _refused("current authority requires committed sealed history")
            self.visible_after = (
                bound.visible_by
                if self.visible_after is None
                else max(self.visible_after, bound.visible_by)
            )

    def require_visible_at(self, now: datetime) -> None:
        if self.visible_after is None:
            raise _refused("current authority requires committed sealed history")
        if now <= self.visible_after:
            raise _invalid("authority observation clock precedes proven visibility")


@dataclass(frozen=True)
class _AuthorityState:
    grant_ref: ArtifactRefV1
    signed_grant: SignedFiscalAuthorityRecordV1
    grant: FiscalAuthorityGrantV1
    revocation_ref: ArtifactRefV1 | None
    heads: tuple[FiscalHistoryHeadV1, ...]


class FiscalAuthorityOwner:
    def __init__(
        self,
        *,
        artifacts: EvidenceArtifactStore,
        history: FiscalAdmissionHistoryPort | None,
        deployment: Callable[[], FiscalAuthorityDeploymentV1],
        signer: FiscalRegistrySignerPort | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._artifacts = artifacts
        self._history = history
        self._deployment = deployment
        self._signer = signer
        self._clock = clock

    def _now(self) -> datetime:
        now = self._clock()
        if now.utcoffset() is None:
            raise _invalid("authority clock must be timezone aware")
        return now

    @staticmethod
    def _expired() -> SnapshotError:
        return SnapshotError(
            "REQUEST_DEADLINE_EXCEEDED",
            "fiscal authority deadline expired",
            retryable=True,
        )

    def _budget(self, deadline_at: datetime) -> float:
        now = self._now()
        if deadline_at.utcoffset() is None or deadline_at <= now:
            raise self._expired()
        return (deadline_at - now).total_seconds()

    def _configured(self) -> FiscalAuthorityDeploymentV1:
        try:
            return FiscalAuthorityDeploymentV1.model_validate_json(
                canonical_bytes(self._deployment())
            )
        except ValueError as error:
            raise _invalid("authority deployment configuration is invalid") from error

    def _history_owner(self) -> FiscalAdmissionHistoryPort:
        if self._history is None:
            raise SnapshotError(
                "FISCAL_AUTHORITY_HISTORY_UNCONFIGURED",
                "authority requires a trusted admission history adapter",
            )
        return self._history

    @staticmethod
    def _stream(authority_id: str) -> str:
        return "control:fiscal-authority:" + authority_id

    @staticmethod
    def _root(
        configuration: FiscalAuthorityDeploymentV1, issuer: FiscalRegistryOperatorV1
    ) -> FiscalConfiguredRegistryRootV1:
        root = next(
            (r for r in configuration.roots if r.identity.root_id == issuer.root_id),
            None,
        )
        if root is None or (
            root.identity.principal_id != issuer.principal_id
            or root.identity.principal_kind != issuer.principal_kind
            or root.identity.key_id != issuer.key_id
        ):
            raise _refused("registry issuer is not a configured trust root")
        if root.evidence_ref.role != "fiscal-registry-root-v1":
            raise _invalid("registry root evidence has a different role")
        return root

    @staticmethod
    def _target(
        configuration: FiscalAuthorityDeploymentV1, authority_id: str
    ) -> FiscalConfiguredAuthorityV1:
        result = next(
            (
                a
                for a in configuration.authorities
                if a.identity.authority_id == authority_id
            ),
            None,
        )
        if result is None:
            raise _refused("authority is not present in the deployment roster")
        if result.provisioning_ref.role != "fiscal-authority-provisioning-v1":
            raise _invalid("authority provisioning evidence has a different role")
        return result

    @staticmethod
    def _require_root_time(root: FiscalConfiguredRegistryRootV1, at: datetime) -> None:
        if not root.identity.valid_from <= at < root.identity.valid_until:
            raise _refused("registry root is outside its authorized time window")

    def _authenticate(
        self,
        command: FiscalAuthorityCommandV1,
        configuration: FiscalAuthorityDeploymentV1,
        reader: _AuthorityRead,
        deadline_at: datetime,
    ) -> tuple[FiscalRegistryOperatorV1, FiscalConfiguredRegistryRootV1]:
        if self._signer is None:
            raise _refused("registry signing capability is not configured")
        issuer = self._signer.authenticate(command, deadline_at=deadline_at)
        self._budget(deadline_at)
        root = self._root(configuration, issuer)
        self._require_root_time(root, self._now())
        reader.expect(root.evidence_ref, root.identity)
        self._execution(issuer, command, reader, self._now())
        return issuer, root

    @staticmethod
    def _execution(
        issuer: FiscalRegistryOperatorV1,
        command: FiscalAuthorityCommandV1,
        reader: _AuthorityRead,
        signed_at: datetime,
    ) -> None:
        if issuer.execution_ref.role != "fiscal-registry-execution-v1":
            raise _invalid("registry execution evidence has a different role")
        try:
            execution = FiscalRegistryExecutionV1.model_validate_json(
                reader.read(issuer.execution_ref)
            )
        except ValueError as error:
            raise _invalid("registry execution evidence is invalid") from error
        reader.expect(issuer.execution_ref, execution)
        if (
            execution.root_id != issuer.root_id
            or execution.principal_id != issuer.principal_id
            or execution.principal_kind != issuer.principal_kind
            or execution.key_id != issuer.key_id
            or execution.operation != command.kind
            or execution.command_digest != fiscal_authority_command_digest(command)
            or execution.started_at > signed_at
        ):
            raise _invalid("registry execution does not authenticate this command")

    @staticmethod
    def _dependencies(signed: SignedFiscalAuthorityRecordV1) -> tuple[str, ...]:
        values = {
            signed.root_evidence_ref.content_hash,
            signed.issuer.execution_ref.content_hash,
            signed.issuer.key_id,
        }
        record = signed.record
        if isinstance(record, FiscalAuthorityGrantV1):
            values.update(
                (record.provisioning_ref.content_hash, record.identity.key_id)
            )
        else:
            values.add(record.command.grant_ref.content_hash)
        return tuple(sorted(values))

    def _verify(
        self,
        signed: SignedFiscalAuthorityRecordV1,
        ref: ArtifactRefV1,
        configuration: FiscalAuthorityDeploymentV1,
        reader: _AuthorityRead,
    ) -> None:
        root = self._root(configuration, signed.issuer)
        if (
            signed.root_evidence_ref != root.evidence_ref
            or ref.artifact_id != signed.artifact_id
        ):
            raise _invalid("authority signing root or command identity differs")
        reader.expect(root.evidence_ref, root.identity)
        self._execution(signed.issuer, signed.record.command, reader, signed.signed_at)
        self._verify_signature(signed, root)
        if isinstance(signed.record, FiscalAuthorityGrantV1):
            if (
                signed.record.provisioning_ref.role
                != "fiscal-authority-provisioning-v1"
            ):
                raise _invalid("authority provisioning evidence has a different role")
            reader.expect(signed.record.provisioning_ref, signed.record.identity)
            if signed.record.valid_until > min(
                root.identity.valid_until, signed.record.valid_from + _MAX_GRANT_AGE
            ):
                raise _invalid("authority grant exceeds its permitted time window")
        if reader.get(ref.artifact_id).dependency_hashes != self._dependencies(signed):
            raise _invalid("authority dependency metadata differs")

    @classmethod
    def _verify_signature(
        cls,
        signed: SignedFiscalAuthorityRecordV1,
        root: FiscalConfiguredRegistryRootV1,
    ) -> None:
        cls._require_root_time(root, signed.signed_at)
        try:
            Ed25519PublicKey.from_public_bytes(
                base64.b64decode(root.identity.public_key_ed25519_base64, validate=True)
            ).verify(bytes.fromhex(signed.signature), signed.signing_bytes())
        except (InvalidSignature, ValueError) as error:
            raise _invalid("authority record signature is invalid") from error

    def _load(
        self,
        ref: ArtifactRefV1,
        configuration: FiscalAuthorityDeploymentV1,
        reader: _AuthorityRead,
    ) -> SignedFiscalAuthorityRecordV1:
        if ref.role != _RECORD_ROLE or ref.media_type != "application/json":
            raise _invalid("authority control requires a typed JSON record")
        raw = reader.read(ref)
        try:
            signed = SignedFiscalAuthorityRecordV1.model_validate_json(raw)
        except ValueError as error:
            raise _invalid("authority record failed typed decoding") from error
        if canonical_bytes(signed) != raw:
            raise _invalid("authority record bytes are not canonical")
        self._verify(signed, ref, configuration, reader)
        return signed

    def _state(
        self,
        authority_id: str,
        configuration: FiscalAuthorityDeploymentV1,
        reader: _AuthorityRead,
        deadline_at: datetime,
        *,
        at: datetime | None = None,
    ) -> _AuthorityState:
        history = self._history_owner()
        state_reader = _AuthorityRead(
            self._artifacts,
            partial(self._budget, deadline_at),
            historical=reader.historical,
        )
        stream = self._stream(authority_id)
        control = history.read((stream,), deadline_at=deadline_at)
        if at is None:
            reader.observe_commits(control.entries)
            entries = control.entries
        else:
            entries = control.prefix_as_of(stream, at=at)
        grant: FiscalAuthorityGrantV1 | None = None
        signed_grant: SignedFiscalAuthorityRecordV1 | None = None
        grant_ref: ArtifactRefV1 | None = None
        revoked: ArtifactRefV1 | None = None
        for entry in entries:
            body = entry.event.body
            if not isinstance(body, FiscalControlBindingV1):
                raise _invalid("authority stream contains non-control evidence")
            signed = self._load(body.payload_ref, configuration, state_reader)
            record = signed.record
            if (
                record.command.authority_id != authority_id
                or body.command_digest != signed.command_digest
                or entry.event.recorded_at < signed.signed_at
                or body.action
                != (
                    "authority_granted"
                    if record.kind == "grant"
                    else "authority_revoked"
                )
            ):
                raise _invalid("authority control event differs from its signed record")
            if isinstance(record, FiscalAuthorityGrantV1):
                if (
                    grant is not None
                    and revoked is None
                    and record.valid_from < grant.valid_until
                ):
                    raise _invalid(
                        "authority history contains overlapping active grants"
                    )
                grant, signed_grant, grant_ref, revoked = (
                    record,
                    signed,
                    body.payload_ref,
                    None,
                )
            else:
                if (
                    grant_ref is None
                    or record.command.grant_ref != grant_ref
                    or revoked is not None
                ):
                    raise _invalid(
                        "authority revocation does not name the active grant"
                    )
                revoked = body.payload_ref
        if grant is None or grant_ref is None or signed_grant is None:
            raise _refused("authority history contains no grant")
        evidence = history.read(
            tuple("evidence:" + identity for identity in state_reader.records),
            deadline_at=deadline_at,
        )
        if at is None:
            reader.observe_commits(evidence.entries)
        else:
            for identity, current in state_reader.records.items():
                historical = evidence.evidence_as_of(identity, at=at)
                if historical is None or (
                    historical.content_hash != current.content_hash
                    or historical.media_type != current.media_type
                    or historical.dependency_hashes != current.dependency_hashes
                    or historical.status != "valid"
                    or historical.retention != "evidence"
                ):
                    raise _invalid(
                        "authority evidence was not valid at the requested time"
                    )
        for identity, artifact_record in state_reader.records.items():
            if reader.records.setdefault(identity, artifact_record) != artifact_record:
                raise _invalid("authority evidence metadata changed")
        return _AuthorityState(
            grant_ref, signed_grant, grant, revoked, control.heads + evidence.heads
        )

    def _finish(
        self,
        configuration: FiscalAuthorityDeploymentV1,
        reader: _AuthorityRead,
        heads: tuple[FiscalHistoryHeadV1, ...],
        deadline_at: datetime,
    ) -> None:
        reader.check_current()
        self._history_owner().require_heads(heads, deadline_at=deadline_at)
        if self._configured() != configuration:
            raise _refused("authority deployment configuration changed")
        reader.check_current()
        self._budget(deadline_at)

    def _live_time(
        self,
        root: FiscalConfiguredRegistryRootV1,
        deadline_at: datetime,
        reader: _AuthorityRead,
        grant: FiscalAuthorityGrantV1 | None = None,
    ) -> datetime:
        now = self._now()
        if deadline_at.utcoffset() is None or now >= deadline_at:
            raise self._expired()
        self._require_root_time(root, now)
        if grant is not None and not grant.valid_from <= now < grant.valid_until:
            raise _refused("authority grant is outside its valid time window")
        reader.require_visible_at(now)
        return now

    def read_current(
        self,
        authority_id: str,
        *,
        expected_role: FiscalAuthorityRole,
        deadline_at: datetime,
    ) -> CurrentFiscalAuthorityV1:
        """Return current authority only after source, head, root and expiry checks."""
        with metadata_operation_budget(
            partial(self._budget, deadline_at), self._expired
        ):
            self._budget(deadline_at)
            configuration = self._configured()
            reader = _AuthorityRead(self._artifacts, partial(self._budget, deadline_at))
            state = self._state(authority_id, configuration, reader, deadline_at)
            target = self._target(configuration, authority_id)
            if (
                state.grant.identity != target.identity
                or state.grant.provisioning_ref != target.provisioning_ref
            ):
                raise _refused("current grant differs from the deployment roster")
            if (
                state.grant.identity.role != expected_role
                or state.revocation_ref is not None
            ):
                raise _refused("authority role is different or its grant was revoked")
            self._finish(configuration, reader, state.heads, deadline_at)
            now = self._live_time(
                self._root(configuration, state.signed_grant.issuer),
                deadline_at,
                reader,
                state.grant,
            )
            return CurrentFiscalAuthorityV1(
                grant_ref=state.grant_ref,
                grant=state.grant,
                history_heads=state.heads,
                observed_at=now,
            )

    def replay_authority(
        self, authority_id: str, *, at: datetime, deadline_at: datetime
    ) -> HistoricalFiscalAuthorityExplanationV1:
        with metadata_operation_budget(
            partial(self._budget, deadline_at), self._expired
        ):
            self._budget(deadline_at)
            if at.utcoffset() is None:
                raise _invalid("authority audit time must be timezone aware")
            configuration = self._configured()
            reader = _AuthorityRead(
                self._artifacts, partial(self._budget, deadline_at), historical=True
            )
            state = self._state(authority_id, configuration, reader, deadline_at, at=at)
            status: Literal["active", "revoked", "expired", "not_yet_valid"] = (
                "revoked"
                if state.revocation_ref is not None
                else "not_yet_valid"
                if at < state.grant.valid_from
                else "expired"
                if at >= state.grant.valid_until
                else "active"
            )
            self._finish(configuration, reader, state.heads, deadline_at)
            return HistoricalFiscalAuthorityExplanationV1(
                authority_id=authority_id,
                at=at,
                state=status,
                grant_ref=state.grant_ref,
                grant=state.grant,
                revocation_ref=state.revocation_ref,
                history_heads=state.heads,
            )

    def _existing(
        self,
        command: FiscalAuthorityCommandV1,
        issuer: FiscalRegistryOperatorV1,
        configuration: FiscalAuthorityDeploymentV1,
        reader: _AuthorityRead,
    ) -> tuple[SignedFiscalAuthorityRecordV1, ArtifactPublicationV1] | None:
        try:
            record = self._artifacts.get(fiscal_authority_command_artifact_id(command))
        except SnapshotError as error:
            if error.code != "ARTIFACT_NOT_FOUND":
                raise
            return None
        signed = self._load(_ref(record), configuration, reader)
        if signed.record.command != command or (
            signed.issuer.root_id != issuer.root_id
            or signed.issuer.principal_id != issuer.principal_id
            or signed.issuer.principal_kind != issuer.principal_kind
            or signed.issuer.key_id != issuer.key_id
        ):
            raise SnapshotError(
                "FISCAL_AUTHORITY_COMMAND_REUSED",
                "authority command identity is immutable",
            )
        return signed, ArtifactPublicationV1(artifact=record, wrote=False)

    def _publish(
        self,
        record: FiscalAuthorityGrantV1 | FiscalAuthorityRevocationV1,
        issuer: FiscalRegistryOperatorV1,
        root: FiscalConfiguredRegistryRootV1,
        reader: _AuthorityRead,
        deadline_at: datetime,
    ) -> tuple[SignedFiscalAuthorityRecordV1, ArtifactPublicationV1]:
        signed_at = (
            record.valid_from
            if isinstance(record, FiscalAuthorityGrantV1)
            else record.revoked_at
        )
        unsigned = SignedFiscalAuthorityRecordV1(
            record=record,
            issuer=issuer,
            root_evidence_ref=root.evidence_ref,
            signed_at=signed_at,
            signature="0" * 128,
        )
        if self._signer is None:
            raise _refused("registry signing capability is not configured")
        signature = self._signer.sign(
            unsigned.signing_bytes(), operator=issuer, deadline_at=deadline_at
        )
        self._budget(deadline_at)
        signed = unsigned.model_copy(update={"signature": signature})
        try:
            signed = SignedFiscalAuthorityRecordV1.model_validate_json(
                canonical_bytes(signed)
            )
        except ValueError as error:
            raise _invalid("registry signature response is invalid") from error
        self._verify_signature(signed, root)
        reader.check_current()
        publication = self._artifacts.put_bytes_with_receipt(
            signed.artifact_id,
            canonical_bytes(signed),
            self._dependencies(signed),
            media_type="application/json",
            publication_budget=partial(self._budget, deadline_at),
        )
        self._verify(signed, _ref(publication.artifact), self._configured(), reader)
        return signed, publication

    def _append(
        self,
        signed: SignedFiscalAuthorityRecordV1,
        publication: ArtifactPublicationV1,
        reader: _AuthorityRead,
        expected_head: FiscalHistoryHeadV1 | None,
        deadline_at: datetime,
    ) -> tuple[FiscalHistoryHeadV1, ...]:
        history = self._history_owner()
        reader.get(signed.artifact_id)
        checkpoint = history.checkpoint(
            tuple(reader.records.values()), deadline_at=deadline_at
        )
        reader.observe_commits(checkpoint.entries)
        appended = history.append_once(
            "fiscal-authority:" + signed.record.command.authority_id,
            FiscalControlBindingV1(
                action="authority_granted"
                if signed.record.kind == "grant"
                else "authority_revoked",
                payload_ref=_ref(publication.artifact),
                command_digest=signed.command_digest,
            ),
            expected_head=expected_head,
            deadline_at=deadline_at,
        )
        reader.observe_commits((appended.entry,))
        return checkpoint.heads

    @staticmethod
    def _merge_heads(
        first: tuple[FiscalHistoryHeadV1, ...],
        second: tuple[FiscalHistoryHeadV1, ...],
    ) -> tuple[FiscalHistoryHeadV1, ...]:
        heads = {head.stream_id: head for head in first}
        for head in second:
            if heads.setdefault(head.stream_id, head) != head:
                raise _invalid("authority evidence history changed")
        return tuple(heads[key] for key in sorted(heads))

    def grant(
        self,
        command: FiscalGrantAuthorityCommandV1,
        *,
        expected_head: FiscalHistoryHeadV1 | None,
        deadline_at: datetime,
    ) -> FiscalAuthorityPublicationV1:
        with metadata_operation_budget(
            partial(self._budget, deadline_at), self._expired
        ):
            self._budget(deadline_at)
            self._history_owner()
            configuration = self._configured()
            reader = _AuthorityRead(self._artifacts, partial(self._budget, deadline_at))
            target = self._target(configuration, command.authority_id)
            issuer, root = self._authenticate(
                command, configuration, reader, deadline_at
            )
            existing = self._existing(command, issuer, configuration, reader)
            if existing is None:
                if expected_head is not None:
                    state = self._state(
                        command.authority_id, configuration, reader, deadline_at
                    )
                    if (
                        state.revocation_ref is None
                        and state.grant.valid_until > self._now()
                    ):
                        raise _refused("authority already has an active grant")
                now = self._now()
                if (
                    not now
                    < command.expires_at
                    <= min(now + _MAX_GRANT_AGE, root.identity.valid_until)
                ):
                    raise _refused(
                        "authority expiry is outside the permitted grant window"
                    )
                reader.expect(target.provisioning_ref, target.identity)
                signed, publication = self._publish(
                    FiscalAuthorityGrantV1(
                        command=command,
                        identity=target.identity,
                        provisioning_ref=target.provisioning_ref,
                        valid_from=now,
                        valid_until=command.expires_at,
                    ),
                    issuer,
                    root,
                    reader,
                    deadline_at,
                )
            else:
                signed, publication = existing
            evidence_heads = self._append(
                signed, publication, reader, expected_head, deadline_at
            )
            current = self.read_current(
                command.authority_id,
                expected_role=target.identity.role,
                deadline_at=deadline_at,
            )
            if current.grant_ref != _ref(publication.artifact):
                raise _refused("authority command is no longer the current grant")
            heads = self._merge_heads(evidence_heads, current.history_heads)
            self._finish(configuration, reader, heads, deadline_at)
            self._live_time(root, deadline_at, reader, current.grant)
            return FiscalAuthorityPublicationV1(
                signed_record=signed,
                publication=publication,
                history_heads=heads,
            )

    def revoke(
        self,
        command: FiscalRevokeAuthorityCommandV1,
        *,
        expected_head: FiscalHistoryHeadV1,
        deadline_at: datetime,
    ) -> FiscalAuthorityPublicationV1:
        with metadata_operation_budget(
            partial(self._budget, deadline_at), self._expired
        ):
            self._budget(deadline_at)
            self._history_owner()
            configuration = self._configured()
            reader = _AuthorityRead(self._artifacts, partial(self._budget, deadline_at))
            issuer, root = self._authenticate(
                command, configuration, reader, deadline_at
            )
            existing = self._existing(command, issuer, configuration, reader)
            if existing is None:
                state = self._state(
                    command.authority_id, configuration, reader, deadline_at
                )
                if (
                    state.grant_ref != command.grant_ref
                    or state.revocation_ref is not None
                ):
                    raise _refused(
                        "revocation does not name an unrevoked current grant"
                    )
                signed, publication = self._publish(
                    FiscalAuthorityRevocationV1(
                        command=command, revoked_at=self._now()
                    ),
                    issuer,
                    root,
                    reader,
                    deadline_at,
                )
            else:
                signed, publication = existing
            evidence_heads = self._append(
                signed, publication, reader, expected_head, deadline_at
            )
            state = self._state(
                command.authority_id, configuration, reader, deadline_at
            )
            if state.revocation_ref != _ref(publication.artifact):
                raise _refused("authority command is no longer its current revocation")
            heads = self._merge_heads(evidence_heads, state.heads)
            self._finish(configuration, reader, heads, deadline_at)
            self._live_time(root, deadline_at, reader)
            return FiscalAuthorityPublicationV1(
                signed_record=signed, publication=publication, history_heads=heads
            )
