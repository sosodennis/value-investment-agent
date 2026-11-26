from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import partial
from typing import Annotated, Literal, Protocol, TypeVar, runtime_checkable

from pydantic import AwareDatetime, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection

from .contracts import StrictModel
from .data_releases import ArtifactRefV1
from .metadata import PostgresMetadataStore, metadata_operation_budget
from .history_recovery_contracts import FiscalHistoryCutoverV1, FiscalHistoryEpochV1
from .replay import ArtifactRecordV1
from .serialization import canonical_bytes
from .snapshots import SnapshotError

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Subject = Annotated[str, Field(min_length=1, max_length=1024)]
OriginId = Annotated[str, Field(pattern=r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")]
_T = TypeVar("_T")
_MAX_STREAMS = 256


class FiscalControlBindingV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["control"] = "control"
    action: Literal[
        "authority_granted",
        "authority_revoked",
        "classification_recorded",
        "candidate_prepared",
        "release_approved",
        "decision_revoked",
        "decision_superseded",
    ]
    payload_ref: ArtifactRefV1
    command_digest: Digest

    @model_validator(mode="after")
    def bounded_reference(self) -> FiscalControlBindingV1:
        ref = self.payload_ref
        if (
            len(ref.artifact_id) > 1024
            or len(ref.role) > 256
            or len(ref.media_type) > 256
        ):
            raise ValueError("control evidence reference exceeds its bounds")
        return self


class FiscalEvidenceCheckpointV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["evidence_checkpoint"] = "evidence_checkpoint"
    record: ArtifactRecordV1


class FiscalEvidenceTransitionV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["evidence_changed"] = "evidence_changed"
    previous_record: ArtifactRecordV1 | None
    record: ArtifactRecordV1 | None

    @model_validator(mode="after")
    def requires_change(self) -> FiscalEvidenceTransitionV1:
        if self.previous_record == self.record:
            raise ValueError("evidence transition must change its record")
        return self


class FiscalEvidenceReobservationV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["evidence_reobserved"] = "evidence_reobserved"
    record: ArtifactRecordV1
    recovery_operation_id: Digest


HistoryBody = Annotated[
    FiscalControlBindingV1
    | FiscalEvidenceCheckpointV1
    | FiscalEvidenceTransitionV1
    | FiscalEvidenceReobservationV1,
    Field(discriminator="kind"),
]


class FiscalHistoryHeadV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    stream_id: Subject
    stream_kind: Literal["control", "evidence"]
    subject_id: Subject
    sequence: int = Field(gt=0)
    event_digest: Digest
    recorded_at: AwareDatetime


class FiscalHistoryEventV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    protocol: Literal["fundamental.fiscal-history-event.v1"]
    hash_protocol: Literal["postgres-jsonb-text-sha256-v1"]
    stream_id: Subject
    stream_kind: Literal["control", "evidence"]
    subject_id: Subject
    sequence: int = Field(gt=0)
    previous_digest: Digest | None
    origin_id: OriginId
    writer_xid8: int = Field(gt=0, lt=2**64)
    recorded_at: AwareDatetime
    body: HistoryBody


class FiscalCommitReceiptV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["sealed"] = "sealed"
    origin_id: OriginId
    writer_xid8: int = Field(gt=0, lt=2**64)
    committed_at: AwareDatetime
    visible_by: AwareDatetime

    @model_validator(mode="after")
    def ordered_bounds(self) -> FiscalCommitReceiptV1:
        if self.committed_at > self.visible_by:
            raise ValueError("commit visibility clock reversed")
        return self


class FiscalCommitLowerV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["known"] = "known"
    committed_at: AwareDatetime


class FiscalCommitMissingV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["missing"] = "missing"
    reason: Literal[
        "uncommitted", "tracking_disabled", "unsafe_xid", "commit_log_missing"
    ]


class FiscalCommitPendingV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["pending"] = "pending"
    lower_bound: Annotated[
        FiscalCommitLowerV1 | FiscalCommitMissingV1, Field(discriminator="kind")
    ]


CommitBound = Annotated[
    FiscalCommitReceiptV1 | FiscalCommitPendingV1, Field(discriminator="kind")
]


class FiscalHistoryEntryV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    event: FiscalHistoryEventV1
    event_digest: Digest
    payload_bytes: bytes
    commit_bound: CommitBound


def verify_evidence_reobservation(
    event: FiscalHistoryEventV1,
    previous_event: FiscalHistoryEventV1 | None,
    previous_record: ArtifactRecordV1 | None,
    epoch: FiscalHistoryEpochV1,
    committed_at: datetime | None,
) -> None:
    body = event.body
    if not isinstance(body, FiscalEvidenceReobservationV1):
        raise ValueError("event is not an evidence reobservation")
    cutover = next(
        (
            link
            for link in epoch.cutovers
            if link.operation_id == body.recovery_operation_id
        ),
        None,
    )
    if (
        previous_event is None
        or previous_record is None
        or body.record != previous_record
        or cutover is None
        or cutover.target_origin_id != event.origin_id
        or previous_event.origin_id == event.origin_id
        or cutover.activation is None
        or event.recorded_at <= cutover.activation.visible_by
        or committed_at is not None
        and committed_at <= cutover.activation.visible_by
    ):
        raise ValueError(
            "evidence reobservation does not follow its recovery activation"
        )


class FiscalHistoryReadV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    heads: tuple[FiscalHistoryHeadV1, ...]
    entries: tuple[FiscalHistoryEntryV1, ...]
    observed_through: AwareDatetime
    epoch: FiscalHistoryEpochV1

    def require_current_epoch(self, entries: tuple[FiscalHistoryEntryV1, ...]) -> None:
        if not entries:
            raise _unavailable("current authority requires explicit control evidence")
        local_entries = {entry.event_digest: entry for entry in self.entries}
        activation = self.epoch.cutovers[-1].activation if self.epoch.cutovers else None
        if self.epoch.cutovers and activation is None:
            raise _unavailable("history recovery activation is pending")
        for entry in entries:
            bound = entry.commit_bound
            if (
                local_entries.get(entry.event_digest) != entry
                or entry.event.origin_id != self.epoch.local_origin_id
                or not isinstance(bound, FiscalCommitReceiptV1)
                or activation is not None
                and bound.committed_at <= activation.visible_by
            ):
                raise _unavailable(
                    "recovered authority requires fresh local control evidence"
                )

    def prefix_as_of(
        self, stream_id: str, *, at: datetime
    ) -> tuple[FiscalHistoryEntryV1, ...]:
        _aware(at)
        if at > self.observed_through:
            raise _unavailable("history does not cover the requested time")
        selected = tuple(e for e in self.entries if e.event.stream_id == stream_id)
        if not selected:
            raise _unavailable("history does not cover the requested stream")
        required_origin = None
        for cutover in self.epoch.cutovers:
            if at > cutover.source_frontier_at:
                if cutover.activation is None:
                    raise _unavailable("history recovery activation is pending")
                if at < cutover.activation.committed_at:
                    raise _unavailable("recovery_gap: source activity was not observed")
                if at <= cutover.activation.visible_by:
                    raise _unavailable("activation_visibility_ambiguous")
                required_origin = cutover.target_origin_id
        prefix = []
        excluded = False
        for entry in selected:
            bound = entry.commit_bound
            if isinstance(bound, FiscalCommitReceiptV1):
                if at > bound.visible_by:
                    if excluded:
                        raise _unavailable(
                            "history visibility bounds are discontinuous"
                        )
                    prefix.append(entry)
                    continue
                lower = bound.committed_at
            elif isinstance(bound.lower_bound, FiscalCommitLowerV1):
                lower = bound.lower_bound.committed_at
            else:
                raise _unavailable("commit visibility lower bound is unavailable")
            if at < lower:
                excluded = True
                continue
            raise _unavailable("visibility_ambiguous: commit visibility is not proven")
        if not prefix:
            raise _unavailable("history does not cover the requested time")
        if required_origin is not None:
            origins = [self.epoch.cutovers[0].source_origin_id] + [
                link.target_origin_id for link in self.epoch.cutovers
            ]
            if origins.index(prefix[-1].event.origin_id) < origins.index(
                required_origin
            ):
                raise _unavailable("recovery_gap: no local state has been observed")
        return tuple(prefix)

    def evidence_as_of(
        self, artifact_id: str, *, at: datetime
    ) -> ArtifactRecordV1 | None:
        stream = "evidence:" + artifact_id
        entries = self.prefix_as_of(stream, at=at)
        current = None
        for entry in entries:
            body = entry.event.body
            if not isinstance(
                body,
                (
                    FiscalEvidenceCheckpointV1,
                    FiscalEvidenceTransitionV1,
                    FiscalEvidenceReobservationV1,
                ),
            ):
                raise _unavailable("evidence stream contains a control event")
            current = body.record
        return current


class FiscalHistoryAppendV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    entry: FiscalHistoryEntryV1
    wrote: bool


class FiscalAdmissionHistoryReaderPort(Protocol):
    def read_epoch(self, *, deadline_at: datetime) -> FiscalHistoryEpochV1: ...

    def read(
        self, stream_ids: tuple[str, ...], *, deadline_at: datetime
    ) -> FiscalHistoryReadV1: ...

    def require_heads(
        self, heads: tuple[FiscalHistoryHeadV1, ...], *, deadline_at: datetime
    ) -> None: ...

    def finish_observation(
        self,
        records: tuple[ArtifactRecordV1, ...],
        heads: tuple[FiscalHistoryHeadV1, ...],
        epoch: FiscalHistoryEpochV1,
        *,
        deadline_at: datetime,
    ) -> FiscalHistoryReadV1: ...


@runtime_checkable
class FiscalAdmissionHistoryPort(FiscalAdmissionHistoryReaderPort, Protocol):
    def seal_pending(
        self, stream_ids: tuple[str, ...], *, deadline_at: datetime
    ) -> FiscalHistoryReadV1: ...

    def append_once(
        self,
        subject_id: str,
        command: FiscalControlBindingV1,
        *,
        expected_head: FiscalHistoryHeadV1 | None,
        deadline_at: datetime,
    ) -> FiscalHistoryAppendV1: ...

    def checkpoint(
        self, records: tuple[ArtifactRecordV1, ...], *, deadline_at: datetime
    ) -> FiscalHistoryReadV1: ...


class ReadOnlyFiscalAdmissionHistory:
    def __init__(self, history: FiscalAdmissionHistoryReaderPort) -> None:
        self.__history = history

    def read_epoch(self, *, deadline_at: datetime) -> FiscalHistoryEpochV1:
        return self.__history.read_epoch(deadline_at=deadline_at)

    def read(
        self, stream_ids: tuple[str, ...], *, deadline_at: datetime
    ) -> FiscalHistoryReadV1:
        return self.__history.read(stream_ids, deadline_at=deadline_at)

    def require_heads(
        self, heads: tuple[FiscalHistoryHeadV1, ...], *, deadline_at: datetime
    ) -> None:
        self.__history.require_heads(heads, deadline_at=deadline_at)

    def finish_observation(
        self,
        records: tuple[ArtifactRecordV1, ...],
        heads: tuple[FiscalHistoryHeadV1, ...],
        epoch: FiscalHistoryEpochV1,
        *,
        deadline_at: datetime,
    ) -> FiscalHistoryReadV1:
        return self.__history.finish_observation(
            records, heads, epoch, deadline_at=deadline_at
        )


def _unavailable(message: str) -> SnapshotError:
    return SnapshotError("FISCAL_ADMISSION_HISTORY_UNAVAILABLE", message)


def _aware(value: datetime) -> None:
    if value.utcoffset() is None:
        raise _unavailable("history timestamps must be timezone aware")


def _budget(deadline_at: datetime) -> float:
    _aware(deadline_at)
    remaining = (deadline_at - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        raise _expired()
    return remaining


def _expired() -> SnapshotError:
    return SnapshotError(
        "REQUEST_DEADLINE_EXCEEDED", "fiscal history deadline expired", retryable=True
    )


class PostgresFiscalAdmissionHistory:
    """Retain complete fiscal control and evidence streams in metadata transactions."""

    def __init__(
        self,
        metadata: PostgresMetadataStore,
        *,
        max_entries: int = 4096,
        max_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        if max_entries < 1 or max_bytes < 1:
            raise ValueError("history read limits must be positive")
        self._metadata = metadata
        self._max_entries = max_entries
        self._max_bytes = max_bytes

    def _run(
        self,
        operation: Callable[[AsyncConnection], Awaitable[_T]],
        deadline_at: datetime,
    ) -> _T:
        with metadata_operation_budget(partial(_budget, deadline_at), _expired):
            _budget(deadline_at)
            try:
                result = self._metadata.run_fiscal_admission_history(operation)
            except SQLAlchemyError as error:
                if (
                    isinstance(error, DBAPIError)
                    and getattr(error.orig, "sqlstate", None) == "55000"
                ):
                    raise _unavailable(
                        "history commit proof or prerequisite is unavailable"
                    ) from error
                raise SnapshotError(
                    "FISCAL_ADMISSION_HISTORY_STORAGE_FAILED",
                    "fiscal history transaction failed",
                    retryable=True,
                ) from error
            _budget(deadline_at)
            return result

    def append_once(
        self,
        subject_id: str,
        command: FiscalControlBindingV1,
        *,
        expected_head: FiscalHistoryHeadV1 | None,
        deadline_at: datetime,
    ) -> FiscalHistoryAppendV1:
        stream_id = "control:" + subject_id
        if not subject_id or len(stream_id) > 1024:
            raise _unavailable("control subject is invalid")
        if expected_head is not None and expected_head.stream_id != stream_id:
            raise _unavailable("expected head belongs to another stream")
        appended = self._run(
            partial(self._append_once, stream_id, subject_id, command, expected_head),
            deadline_at,
        )
        sealed = self.seal_pending((stream_id,), deadline_at=deadline_at)
        entry = next(
            e for e in sealed.entries if e.event_digest == appended.entry.event_digest
        )
        self._run(partial(self._verify_control, command), deadline_at)
        return FiscalHistoryAppendV1(entry=entry, wrote=appended.wrote)

    async def _verify_control(
        self, command: FiscalControlBindingV1, connection: AsyncConnection
    ) -> None:
        record = await self._artifact(connection, command.payload_ref.artifact_id)
        if (
            record.status != "valid"
            or record.retention != "evidence"
            or record.content_hash != command.payload_ref.content_hash
            or record.media_type != command.payload_ref.media_type
        ):
            raise _unavailable("control payload differs from valid retained evidence")

    async def _append_once(
        self,
        stream_id: str,
        subject_id: str,
        command: FiscalControlBindingV1,
        expected_head: FiscalHistoryHeadV1 | None,
        connection: AsyncConnection,
    ) -> FiscalHistoryAppendV1:
        await self._lock_stream(connection, stream_id)
        record = await self._artifact(connection, command.payload_ref.artifact_id)
        ref = command.payload_ref
        if (
            record.status != "valid"
            or record.retention != "evidence"
            or record.content_hash != ref.content_hash
            or record.media_type != ref.media_type
            or record.media_type != "application/json"
        ):
            raise _unavailable("control payload differs from valid retained evidence")
        existing = await connection.execute(
            text(
                "SELECT payload_bytes, event_digest FROM fundamental.fiscal_history_events "
                "WHERE stream_id=:stream AND command_digest=:command"
            ),
            {"stream": stream_id, "command": command.command_digest},
        )
        row = existing.first()
        if row is not None:
            entry = self._entry(bytes(row[0]), str(row[1]))
            if entry.event.body != command:
                raise SnapshotError(
                    "FISCAL_HISTORY_COMMAND_REUSED",
                    "history command identity is immutable",
                )
            await self._read((stream_id,), connection)
            return FiscalHistoryAppendV1(entry=entry, wrote=False)
        head = await self._head(connection, stream_id)
        if head != expected_head:
            raise SnapshotError(
                "FISCAL_HISTORY_HEAD_CHANGED",
                "fiscal history head changed",
                retryable=True,
            )
        await connection.execute(
            text(
                "SELECT fundamental.fiscal_history_append(:stream, 'control', :subject, "
                "CAST(:body AS jsonb), :command)"
            ),
            {
                "stream": stream_id,
                "subject": subject_id,
                "body": canonical_bytes(command).decode(),
                "command": command.command_digest,
            },
        )
        result = await connection.execute(
            text(
                "SELECT payload_bytes, event_digest FROM fundamental.fiscal_history_events "
                "WHERE stream_id=:stream AND command_digest=:command"
            ),
            {"stream": stream_id, "command": command.command_digest},
        )
        saved = result.one()
        await self._read((stream_id,), connection)
        return FiscalHistoryAppendV1(
            entry=self._entry(bytes(saved[0]), str(saved[1])), wrote=True
        )

    def checkpoint(
        self, records: tuple[ArtifactRecordV1, ...], *, deadline_at: datetime
    ) -> FiscalHistoryReadV1:
        if not records or len(records) > _MAX_STREAMS:
            raise _unavailable("checkpoint evidence count is outside its bound")
        if len({r.artifact_id for r in records}) != len(records):
            raise _unavailable("checkpoint evidence identities must be distinct")
        if any(len("evidence:" + r.artifact_id) > 1024 for r in records):
            raise _unavailable("checkpoint evidence identity exceeds its bound")
        self._run(partial(self._checkpoint, records), deadline_at)
        sealed = self.seal_pending(
            tuple("evidence:" + r.artifact_id for r in records), deadline_at=deadline_at
        )
        current = {
            entry.event.subject_id: entry.event.body.record
            for entry in sealed.entries
            if isinstance(
                entry.event.body,
                (
                    FiscalEvidenceCheckpointV1,
                    FiscalEvidenceTransitionV1,
                    FiscalEvidenceReobservationV1,
                ),
            )
        }
        if any(current[record.artifact_id] != record for record in records):
            raise _unavailable("checkpoint metadata differs from consumed evidence")
        return sealed

    def seal_pending(
        self, stream_ids: tuple[str, ...], *, deadline_at: datetime
    ) -> FiscalHistoryReadV1:
        self._validate_streams(stream_ids)
        self._run(partial(self._seal_pending, stream_ids), deadline_at)
        result = self.read(stream_ids, deadline_at=deadline_at)
        if any(
            not isinstance(e.commit_bound, FiscalCommitReceiptV1)
            for e in result.entries
        ):
            raise _unavailable("history contains unsealed commits; retry seal_pending")
        return result

    async def _seal_pending(
        self, stream_ids: tuple[str, ...], connection: AsyncConnection
    ) -> None:
        read = await self._read(stream_ids, connection)
        writers = sorted(
            {(e.event.origin_id, e.event.writer_xid8) for e in read.entries}
        )
        for origin, writer in writers:
            await connection.execute(
                text(
                    "SELECT fundamental.fiscal_history_seal(CAST(:origin AS uuid), CAST(:writer AS xid8))"
                ),
                {"origin": str(origin), "writer": writer},
            )

    async def _checkpoint(
        self, records: tuple[ArtifactRecordV1, ...], connection: AsyncConnection
    ) -> FiscalHistoryReadV1:
        for expected in sorted(records, key=lambda r: r.artifact_id):
            record = await self._artifact(connection, expected.artifact_id)
            if record != expected:
                raise _unavailable("checkpoint metadata differs from consumed evidence")
            stream_id = "evidence:" + expected.artifact_id
            await self._lock_stream(connection, stream_id)
            if await self._head(connection, stream_id) is None:
                await connection.execute(
                    text(
                        "SELECT fundamental.fiscal_history_append(:stream, 'evidence', :subject, "
                        "CAST(:body AS jsonb))"
                    ),
                    {
                        "stream": stream_id,
                        "subject": expected.artifact_id,
                        "body": canonical_bytes(
                            FiscalEvidenceCheckpointV1(record=record)
                        ).decode(),
                    },
                )
            else:
                existing = await self._read((stream_id,), connection)
                if (
                    existing.entries[-1].event.origin_id
                    != existing.epoch.local_origin_id
                ):
                    if (
                        not existing.epoch.cutovers
                        or existing.epoch.cutovers[-1].activation is None
                    ):
                        raise _unavailable(
                            "evidence reobservation requires recovery activation"
                        )
                    await connection.execute(
                        text(
                            "SELECT fundamental.fiscal_history_append(:stream, 'evidence', :subject, CAST(:body AS jsonb))"
                        ),
                        {
                            "stream": stream_id,
                            "subject": expected.artifact_id,
                            "body": canonical_bytes(
                                FiscalEvidenceReobservationV1(
                                    record=record,
                                    recovery_operation_id=existing.epoch.cutovers[
                                        -1
                                    ].operation_id,
                                )
                            ).decode(),
                        },
                    )
        return await self._read(
            tuple("evidence:" + r.artifact_id for r in records), connection
        )

    def read_epoch(self, *, deadline_at: datetime) -> FiscalHistoryEpochV1:
        observed = self._run(partial(self._consistent_read, ()), deadline_at)
        try:
            observed.epoch.require_current_activity(observed.observed_through)
        except ValueError as error:
            raise _unavailable(str(error)) from error
        return observed.epoch

    def read(
        self, stream_ids: tuple[str, ...], *, deadline_at: datetime
    ) -> FiscalHistoryReadV1:
        self._validate_streams(stream_ids)
        return self._run(partial(self._consistent_read, stream_ids), deadline_at)

    def read_if_present(
        self, stream_id: str, *, deadline_at: datetime
    ) -> FiscalHistoryReadV1 | None:
        self._validate_streams((stream_id,))
        return self._run(partial(self._read_if_present, stream_id), deadline_at)

    async def _read_if_present(
        self, stream_id: str, connection: AsyncConnection
    ) -> FiscalHistoryReadV1 | None:
        await connection.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        )
        observed = await connection.scalar(text("SELECT transaction_timestamp()"))
        if not isinstance(observed, datetime):
            raise _unavailable("history observation time is unavailable")
        if await self._head(connection, stream_id) is None:
            local = await connection.scalar(
                text("SELECT fundamental.fiscal_history_origin_id()")
            )
            epoch = await self._epoch(connection, str(local))
            try:
                epoch.issuance_context
                epoch.require_current_activity(observed)
            except ValueError as error:
                raise _unavailable(str(error)) from error
            return None
        return await self._read((stream_id,), connection, observed_through=observed)

    async def _consistent_read(
        self, stream_ids: tuple[str, ...], connection: AsyncConnection
    ) -> FiscalHistoryReadV1:
        await connection.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        )
        observed = await connection.scalar(text("SELECT transaction_timestamp()"))
        if not isinstance(observed, datetime):
            raise _unavailable("history observation time is unavailable")
        return await self._read(stream_ids, connection, observed_through=observed)

    async def _read(
        self,
        stream_ids: tuple[str, ...],
        connection: AsyncConnection,
        *,
        observed_through: datetime | None = None,
    ) -> FiscalHistoryReadV1:
        heads: list[FiscalHistoryHeadV1] = []
        entries: list[FiscalHistoryEntryV1] = []
        byte_count = 0
        origin = await connection.scalar(
            text("SELECT fundamental.fiscal_history_origin_id()")
        )
        epoch = await self._epoch(connection, str(origin))
        origins = {epoch.local_origin_id} | {
            link.source_origin_id for link in epoch.cutovers
        }
        bounds: dict[tuple[str, int], CommitBound] = {}
        for stream in sorted(stream_ids):
            head = await self._head(connection, stream)
            if head is None:
                raise _unavailable("requested history stream is unavailable")
            if len(entries) + head.sequence > self._max_entries:
                raise _unavailable("history entry limit exceeded")
            stored_size = await connection.scalar(
                text(
                    "SELECT COALESCE(SUM(octet_length(payload_bytes)), 0) "
                    "FROM fundamental.fiscal_history_events WHERE stream_id=:stream"
                ),
                {"stream": stream},
            )
            if stored_size is None or byte_count + int(stored_size) > self._max_bytes:
                raise _unavailable("history byte limit exceeded")
            result = await connection.execute(
                text(
                    "SELECT payload_bytes, event_digest, command_digest, origin_id, writer_xid8::text "
                    "FROM fundamental.fiscal_history_events "
                    "WHERE stream_id=:stream ORDER BY sequence LIMIT :limit"
                ),
                {"stream": stream, "limit": self._max_entries + 1},
            )
            prior = None
            previous_record = None
            previous_event = None
            last_at = None
            stream_entries = []
            for index, row in enumerate(result, start=1):
                raw = bytes(row[0])
                byte_count += len(raw)
                if byte_count > self._max_bytes:
                    raise _unavailable("history byte limit exceeded")
                entry = self._entry(raw, str(row[1]))
                event = entry.event
                if (
                    event.origin_id not in origins
                    or event.origin_id != str(row[3])
                    or event.writer_xid8 != int(row[4])
                ):
                    raise _unavailable("history writer identity or origin differs")
                writer = (event.origin_id, event.writer_xid8)
                if writer not in bounds:
                    bounds[writer] = await self._commit_bound(connection, event)
                bound = bounds[writer]
                lower = (
                    bound.committed_at
                    if isinstance(bound, FiscalCommitReceiptV1)
                    else bound.lower_bound.committed_at
                    if isinstance(bound.lower_bound, FiscalCommitLowerV1)
                    else None
                )
                if lower is not None and lower < event.recorded_at:
                    raise _unavailable("history commit clock reversed")
                entry = entry.model_copy(update={"commit_bound": bound})
                if (
                    event.stream_id != stream
                    or event.subject_id != head.subject_id
                    or event.stream_kind != head.stream_kind
                    or event.sequence != index
                    or event.previous_digest != prior
                    or (last_at is not None and event.recorded_at < last_at)
                ):
                    raise _unavailable("history sequence or scope is invalid")
                if head.stream_kind == "evidence":
                    if row[2] is not None:
                        raise _unavailable("evidence history has a control command")
                    body = event.body
                    if index == 1:
                        if not isinstance(body, FiscalEvidenceCheckpointV1):
                            raise _unavailable("evidence history has no checkpoint")
                    elif isinstance(body, FiscalEvidenceReobservationV1):
                        try:
                            verify_evidence_reobservation(
                                event, previous_event, previous_record, epoch, lower
                            )
                        except ValueError as error:
                            raise _unavailable(
                                "evidence reobservation is invalid"
                            ) from error
                    elif (
                        not isinstance(body, FiscalEvidenceTransitionV1)
                        or body.previous_record != previous_record
                    ):
                        raise _unavailable(
                            "evidence history transition is discontinuous"
                        )
                    if not isinstance(
                        body,
                        (
                            FiscalEvidenceCheckpointV1,
                            FiscalEvidenceTransitionV1,
                            FiscalEvidenceReobservationV1,
                        ),
                    ):
                        raise _unavailable("evidence history has a control event")
                    previous_record = body.record
                    for record in (
                        body.record,
                        body.previous_record
                        if isinstance(body, FiscalEvidenceTransitionV1)
                        else None,
                    ):
                        if record is not None and record.artifact_id != head.subject_id:
                            raise _unavailable(
                                "evidence history record belongs to another artifact"
                            )
                elif (
                    not isinstance(event.body, FiscalControlBindingV1)
                    or row[2] != event.body.command_digest
                ):
                    raise _unavailable("control history has an evidence event")
                prior, last_at = entry.event_digest, event.recorded_at
                previous_event = event
                stream_entries.append(entry)
            if (
                len(stream_entries) != head.sequence
                or prior != head.event_digest
                or last_at != head.recorded_at
            ):
                raise _unavailable("history prefix does not reach the trusted head")
            if head.stream_kind == "evidence":
                value = await connection.scalar(
                    text(
                        "SELECT fundamental.fiscal_artifact_record(artifact) "
                        "FROM fundamental.artifact_references artifact WHERE artifact_id=:identity"
                    ),
                    {"identity": head.subject_id},
                )
                try:
                    current = (
                        ArtifactRecordV1.model_validate(value)
                        if value is not None
                        else None
                    )
                except ValueError as error:
                    raise _unavailable(
                        "current evidence metadata is invalid"
                    ) from error
                if current != previous_record:
                    raise _unavailable(
                        "evidence history does not reach current metadata"
                    )
            heads.append(head)
            entries.extend(stream_entries)
        observed = observed_through or await connection.scalar(
            text("SELECT clock_timestamp()")
        )
        if not isinstance(observed, datetime):
            raise _unavailable("history observation time is unavailable")
        now = await connection.scalar(text("SELECT clock_timestamp()"))
        if not isinstance(now, datetime) or now < observed:
            raise _unavailable("history observation clock reversed")
        if any(entry.event.recorded_at > now for entry in entries):
            raise _unavailable("history event observation clock reversed")
        for bound in bounds.values():
            if isinstance(bound, FiscalCommitReceiptV1):
                latest_at = max(bound.committed_at, bound.visible_by)
            elif isinstance(bound.lower_bound, FiscalCommitLowerV1):
                latest_at = bound.lower_bound.committed_at
            else:
                continue
            if latest_at > now:
                raise _unavailable("history commit observation clock reversed")
        return FiscalHistoryReadV1(
            heads=tuple(heads),
            entries=tuple(entries),
            observed_through=observed,
            epoch=epoch,
        )

    @staticmethod
    async def _epoch(connection: AsyncConnection, local: str) -> FiscalHistoryEpochV1:
        rows = (
            (
                await connection.execute(
                    text(
                        "SELECT l.operation_id,l.source_manifest_digest,l.source_origin_id::text,"
                        "l.target_origin_id::text,l.source_frontier_at,l.source_heads_digest,"
                        "l.import_writer_xid8::text,a.committed_at,a.visible_by "
                        "FROM fundamental.fiscal_history_restore_links l LEFT JOIN "
                        "fundamental.fiscal_history_activation_receipts a USING(target_origin_id)"
                    )
                )
            )
            .mappings()
            .all()
        )
        if len(rows) > 32:
            raise _unavailable("history recovery lineage exceeds its bound")
        by_target = {row["target_origin_id"]: row for row in rows}
        links = []
        cursor = local
        while cursor in by_target:
            row = by_target.pop(cursor)
            activation = (
                {"committed_at": row["committed_at"], "visible_by": row["visible_by"]}
                if row["committed_at"]
                else None
            )
            links.append(
                FiscalHistoryCutoverV1.model_validate(
                    {
                        key: value
                        for key, value in {
                            **dict(row),
                            "activation": activation,
                        }.items()
                        if key not in {"committed_at", "visible_by"}
                    },
                    strict=False,
                )
            )
            cursor = row["source_origin_id"]
        if by_target:
            raise _unavailable("history recovery lineage contains a fork or orphan")
        try:
            return FiscalHistoryEpochV1(
                local_origin_id=local, cutovers=tuple(reversed(links))
            )
        except ValueError as error:
            raise _unavailable("history recovery lineage is invalid") from error

    @staticmethod
    async def _commit_bound(
        connection: AsyncConnection, event: FiscalHistoryEventV1
    ) -> CommitBound:
        params = {"origin": str(event.origin_id), "writer": event.writer_xid8}
        receipt = (
            (
                await connection.execute(
                    text(
                        "SELECT origin_id, writer_xid8, committed_at, visible_by "
                        "FROM fundamental.fiscal_history_commit_receipts "
                        "WHERE origin_id=CAST(:origin AS uuid) AND writer_xid8=CAST(:writer AS xid8)"
                    ),
                    params,
                )
            )
            .mappings()
            .first()
        )
        try:
            if receipt is not None:
                return FiscalCommitReceiptV1.model_validate(
                    {**dict(receipt), "origin_id": str(receipt["origin_id"])}
                )
            lower = await connection.scalar(
                text(
                    "SELECT fundamental.fiscal_history_commit_lower(CAST(:origin AS uuid), CAST(:writer AS xid8))"
                ),
                params,
            )
            return FiscalCommitPendingV1.model_validate_json(
                json.dumps({"kind": "pending", "lower_bound": lower})
            )
        except ValueError as error:
            raise _unavailable("history commit proof is invalid") from error

    def finish_observation(
        self,
        records: tuple[ArtifactRecordV1, ...],
        heads: tuple[FiscalHistoryHeadV1, ...],
        epoch: FiscalHistoryEpochV1,
        *,
        deadline_at: datetime,
    ) -> FiscalHistoryReadV1:
        if (
            not records
            or len(records) > self._max_entries
            or len({record.artifact_id for record in records}) != len(records)
            or len({head.stream_id for head in heads}) != len(heads)
            or len(canonical_bytes((records, heads))) > self._max_bytes
        ):
            raise _unavailable(
                "whole observation exceeds its bounds or repeats an identity"
            )
        streams = tuple(
            sorted(
                {"evidence:" + record.artifact_id for record in records}
                | {head.stream_id for head in heads}
            )
        )
        if len(streams) > self._max_entries or any(
            len(stream) > 1024 for stream in streams
        ):
            raise _unavailable("whole observation stream selection exceeds its bounds")
        return self._run(
            partial(self._finish_observation, records, heads, epoch, streams),
            deadline_at,
        )

    async def _finish_observation(
        self,
        records: tuple[ArtifactRecordV1, ...],
        heads: tuple[FiscalHistoryHeadV1, ...],
        epoch: FiscalHistoryEpochV1,
        streams: tuple[str, ...],
        connection: AsyncConnection,
    ) -> FiscalHistoryReadV1:
        await connection.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        )
        observed_at = await connection.scalar(text("SELECT transaction_timestamp()"))
        if not isinstance(observed_at, datetime):
            raise _unavailable("whole observation clock is unavailable")
        observed = await self._read(streams, connection, observed_through=observed_at)
        if observed.epoch != epoch:
            raise _unavailable("whole observation recovery epoch changed")
        by_stream = {head.stream_id: head for head in observed.heads}
        if any(by_stream.get(head.stream_id) != head for head in heads):
            raise _unavailable("whole observation history head changed")
        latest = {entry.event.stream_id: entry for entry in observed.entries}
        selected = []
        for record in records:
            entry = latest["evidence:" + record.artifact_id]
            if getattr(entry.event.body, "record", None) != record:
                raise _unavailable("whole observation metadata changed")
            storage = await connection.scalar(
                text(
                    "SELECT byte_length FROM fundamental.content_objects "
                    "WHERE content_hash=:digest AND media_type=:media"
                ),
                {"digest": record.content_hash, "media": record.media_type},
            )
            if not isinstance(storage, int) or storage < 0:
                raise _unavailable("whole observation content storage is unavailable")
            selected.append(entry)
        selected.extend(
            latest[head.stream_id] for head in heads if head.stream_kind == "control"
        )
        observed.require_current_epoch(tuple(selected))
        if any(
            not isinstance(entry.commit_bound, FiscalCommitReceiptV1)
            for entry in observed.entries
        ):
            raise _unavailable("whole observation contains unsealed history")
        return observed

    def require_heads(
        self, heads: tuple[FiscalHistoryHeadV1, ...], *, deadline_at: datetime
    ) -> None:
        self._validate_streams(tuple(h.stream_id for h in heads))
        self._run(partial(self._require_heads, heads), deadline_at)

    async def _require_heads(
        self, heads: tuple[FiscalHistoryHeadV1, ...], connection: AsyncConnection
    ) -> None:
        await connection.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        )
        for expected in heads:
            if await self._head(connection, expected.stream_id) != expected:
                raise SnapshotError(
                    "FISCAL_HISTORY_HEAD_CHANGED",
                    "fiscal history head changed",
                    retryable=True,
                )

    @staticmethod
    def _validate_streams(stream_ids: tuple[str, ...]) -> None:
        if (
            not stream_ids
            or len(stream_ids) > _MAX_STREAMS
            or len(set(stream_ids)) != len(stream_ids)
            or any(not s or len(s) > 1024 for s in stream_ids)
        ):
            raise _unavailable("history stream selection is invalid")

    @staticmethod
    async def _lock_stream(connection: AsyncConnection, stream: str) -> None:
        await connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:stream, 0))"),
            {"stream": stream},
        )

    @staticmethod
    async def _artifact(connection: AsyncConnection, identity: str) -> ArtifactRecordV1:
        value = await connection.scalar(
            text(
                "SELECT fundamental.fiscal_artifact_record(artifact) "
                "FROM fundamental.artifact_references artifact WHERE artifact_id=:identity FOR SHARE"
            ),
            {"identity": identity},
        )
        if value is None:
            raise _unavailable("history evidence artifact is unavailable")
        try:
            return ArtifactRecordV1.model_validate(value)
        except ValueError as error:
            raise _unavailable("history evidence metadata is invalid") from error

    @staticmethod
    async def _head(
        connection: AsyncConnection, identity: str
    ) -> FiscalHistoryHeadV1 | None:
        row = (
            (
                await connection.execute(
                    text(
                        "SELECT stream_id, stream_kind, subject_id, sequence, event_digest, recorded_at "
                        "FROM fundamental.fiscal_history_streams WHERE stream_id=:identity"
                    ),
                    {"identity": identity},
                )
            )
            .mappings()
            .first()
        )
        try:
            return (
                FiscalHistoryHeadV1.model_validate(dict(row))
                if row is not None
                else None
            )
        except ValueError as error:
            raise _unavailable("history stream head is invalid") from error

    @staticmethod
    def _entry(raw: bytes, digest: str) -> FiscalHistoryEntryV1:
        if hashlib.sha256(raw).hexdigest() != digest:
            raise _unavailable("history event bytes do not match its digest")
        try:
            event = FiscalHistoryEventV1.model_validate_json(raw)
        except ValueError as error:
            raise _unavailable("history event payload is invalid") from error
        return FiscalHistoryEntryV1(
            event=event,
            event_digest=digest,
            payload_bytes=raw,
            commit_bound=FiscalCommitPendingV1(
                lower_bound=FiscalCommitMissingV1(reason="uncommitted")
            ),
        )
