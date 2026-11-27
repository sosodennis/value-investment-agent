from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from typing import Mapping, Sequence

from .fiscal_admission_history import (
    FiscalControlBindingV1,
    FiscalEvidenceCheckpointV1,
    FiscalEvidenceTransitionV1,
    FiscalEvidenceReobservationV1,
    FiscalHistoryEventV1,
    FiscalHistoryHeadV1,
    FiscalCommitReceiptV1,
    verify_evidence_reobservation,
)
from .history_recovery_contracts import (
    FiscalHistoryCutoverV1,
    FiscalHistoryEpochV1,
    FiscalHistoryFrontierV1,
    FiscalHistoryOriginV1,
)
from .replay import ArtifactRecordV1
from .serialization import sha256_digest

BackupRow = dict[str, str | None]


def history_heads_digest(heads: Sequence[FiscalHistoryHeadV1]) -> str:
    return sha256_digest(tuple(sorted(heads, key=lambda head: head.stream_id)))


def _required(row: BackupRow, key: str) -> str:
    value = row[key]
    if value is None:
        raise ValueError("history backup contains a missing required value")
    return value


def _decoded(row: BackupRow) -> dict[str, object]:
    dates = {"recorded_at", "committed_at", "visible_by", "source_frontier_at"}
    return {
        key: datetime.fromisoformat(value)
        if key in dates and value is not None
        else value
        for key, value in row.items()
    }


def backup_epoch(
    tables: Mapping[str, Sequence[BackupRow]],
    local_origin_id: str,
    *,
    allow_pending_local: bool = False,
    check_budget: Callable[[], None] | None = None,
) -> FiscalHistoryEpochV1:
    receipts = {
        _required(row, "target_origin_id"): row
        for row in tables["fiscal_history_activation_receipts"]
    }
    links = {
        _required(row, "target_origin_id"): row
        for row in tables["fiscal_history_restore_links"]
    }
    if len(links) != len(tables["fiscal_history_restore_links"]) or len(
        receipts
    ) != len(tables["fiscal_history_activation_receipts"]):
        raise ValueError("history backup contains duplicate recovery identities")
    if len(links) > 32:
        raise ValueError("history backup recovery lineage exceeds its bound")
    result = []
    cursor = local_origin_id
    while cursor in links:
        if check_budget is not None:
            check_budget()
        row = links.pop(cursor)
        receipt = receipts.pop(cursor, None)
        if receipt is None and not (allow_pending_local and cursor == local_origin_id):
            raise ValueError("history backup contains pending recovery activation")
        result.append(
            FiscalHistoryCutoverV1.model_validate(
                {
                    key: value
                    for key, value in {
                        **_decoded(row),
                        "activation": {
                            "committed_at": datetime.fromisoformat(
                                _required(receipt, "committed_at")
                            ),
                            "visible_by": datetime.fromisoformat(
                                _required(receipt, "visible_by")
                            ),
                        }
                        if receipt is not None
                        else None,
                    }.items()
                    if key != "runtime_role"
                },
                strict=False,
            )
        )
        cursor = _required(row, "source_origin_id")
    if links or receipts:
        raise ValueError("history backup lineage contains a fork or orphan")
    return FiscalHistoryEpochV1(
        local_origin_id=local_origin_id, cutovers=tuple(reversed(result))
    )


def verify_fiscal_history_backup(
    tables: Mapping[str, Sequence[BackupRow]],
    frontier: FiscalHistoryFrontierV1,
    *,
    allow_pending_local: bool = False,
    check_budget: Callable[[], None] | None = None,
) -> FiscalHistoryEpochV1:
    origins = {
        _required(row, "origin_id"): FiscalHistoryOriginV1.model_validate(
            row, strict=False
        )
        for row in tables["fiscal_history_origin"]
    }
    local = tables["fiscal_history_local_origin"]
    if (
        len(local) != 1
        or local[0]["singleton"] != "true"
        or local[0]["origin_id"] != frontier.origin_id
    ):
        raise ValueError("history backup local origin differs from its frontier")
    if len(origins) != len(tables["fiscal_history_origin"]):
        raise ValueError("history backup contains duplicate origins")
    epoch = backup_epoch(
        tables,
        frontier.origin_id,
        allow_pending_local=allow_pending_local,
        check_budget=check_budget,
    )
    order = ([epoch.cutovers[0].source_origin_id] if epoch.cutovers else []) + [
        link.target_origin_id for link in epoch.cutovers
    ]
    if not order:
        order = [frontier.origin_id]
    if set(order) != set(origins):
        raise ValueError("history backup contains unrelated origins")
    ranks = {origin: index for index, origin in enumerate(order)}
    activations = {link.target_origin_id: link.activation for link in epoch.cutovers}
    frontiers = {
        link.source_origin_id: link.source_frontier_at for link in epoch.cutovers
    }
    if any(
        link.activation is not None
        and link.activation.visible_by >= frontier.covered_through
        for link in epoch.cutovers
    ):
        raise ValueError("history backup frontier does not cover recovery activation")
    commit_receipts = {}
    for row in tables["fiscal_history_commit_receipts"]:
        parsed_receipt = FiscalCommitReceiptV1.model_validate(
            _decoded(row), strict=False
        )
        key = (parsed_receipt.origin_id, parsed_receipt.writer_xid8)
        if key in commit_receipts or parsed_receipt.origin_id not in ranks:
            raise ValueError("history backup contains duplicate or foreign receipts")
        commit_receipts[key] = parsed_receipt
    indexed_events = {
        (row["stream_id"], int(_required(row, "sequence"))): row
        for row in tables["fiscal_history_events"]
    }
    if len(indexed_events) != len(tables["fiscal_history_events"]):
        raise ValueError("history backup has duplicate event identities")
    grouped: dict[str, list[FiscalHistoryEventV1]] = defaultdict(list)
    writers: set[tuple[str, int]] = set()
    for row in tables["fiscal_history_events"]:
        if check_budget is not None:
            check_budget()
        payload = _required(row, "payload_bytes")
        if not payload.startswith("\\x"):
            raise ValueError("history event bytes require PostgreSQL hex encoding")
        raw = bytes.fromhex(payload[2:])
        if hashlib.sha256(raw).hexdigest() != row["event_digest"]:
            raise ValueError("history backup event digest differs")
        event = FiscalHistoryEventV1.model_validate_json(raw)
        if (
            event.stream_id != row["stream_id"]
            or event.sequence != int(_required(row, "sequence"))
            or event.origin_id != row["origin_id"]
            or event.writer_xid8 != int(_required(row, "writer_xid8"))
            or event.origin_id not in ranks
            or (
                event.body.command_digest
                if isinstance(event.body, FiscalControlBindingV1)
                else None
            )
            != row["command_digest"]
        ):
            raise ValueError("history backup indexed event differs")
        key = (event.origin_id, event.writer_xid8)
        receipt = commit_receipts.get(key)
        if receipt is None:
            raise ValueError("history backup contains an unsealed writer")
        if (
            event.recorded_at > receipt.committed_at
            or receipt.visible_by >= frontier.covered_through
        ):
            raise ValueError("history backup visibility or frontier clock reversed")
        activation = activations.get(event.origin_id)
        if event.origin_id in activations and (
            activation is None or event.recorded_at <= activation.visible_by
        ):
            raise ValueError("history backup event precedes its recovery activation")
        if (
            event.origin_id in frontiers
            and receipt.visible_by >= frontiers[event.origin_id]
        ):
            raise ValueError("history backup event exceeds its source frontier")
        grouped[event.stream_id].append(event)
        writers.add(key)
    if set(commit_receipts) != writers:
        raise ValueError("history backup contains receipts without complete events")
    heads = [
        FiscalHistoryHeadV1.model_validate(_decoded(row), strict=False)
        for row in tables["fiscal_history_streams"]
    ]
    if (
        len(heads) != len(grouped)
        or history_heads_digest(heads) != frontier.heads_digest
    ):
        raise ValueError("history backup trusted heads differ")
    artifacts = {
        _required(row, "artifact_id"): ArtifactRecordV1.model_validate(
            {
                key: json.loads(value)
                if key == "dependency_hashes" and value
                else value
                for key, value in row.items()
                if key != "created_at"
            },
            strict=False,
        )
        for row in tables["artifact_references"]
    }
    for head in heads:
        events = sorted(grouped[head.stream_id], key=lambda event: event.sequence)
        previous = None
        previous_record = None
        previous_event = None
        last_at: datetime | None = None
        rank = -1
        for sequence, event in enumerate(events, 1):
            if check_budget is not None:
                check_budget()
            indexed = indexed_events[(head.stream_id, sequence)]
            if (
                event.sequence != sequence
                or event.previous_digest != previous
                or event.subject_id != head.subject_id
                or event.stream_kind != head.stream_kind
                or ranks[event.origin_id] < rank
                or (last_at and event.recorded_at < last_at)
            ):
                raise ValueError("history backup stream sequence is invalid")
            if head.stream_kind == "evidence":
                body = event.body
                if sequence == 1 and not isinstance(body, FiscalEvidenceCheckpointV1):
                    raise ValueError("history backup evidence lacks a checkpoint")
                if sequence > 1 and isinstance(body, FiscalEvidenceReobservationV1):
                    verify_evidence_reobservation(
                        event,
                        previous_event,
                        previous_record,
                        epoch,
                        commit_receipts[
                            (event.origin_id, event.writer_xid8)
                        ].committed_at,
                    )
                elif sequence > 1 and (
                    not isinstance(body, FiscalEvidenceTransitionV1)
                    or body.previous_record != previous_record
                ):
                    raise ValueError("history backup evidence transitions differ")
                if not isinstance(
                    body,
                    (
                        FiscalEvidenceCheckpointV1,
                        FiscalEvidenceTransitionV1,
                        FiscalEvidenceReobservationV1,
                    ),
                ):
                    raise ValueError("history backup evidence contains a control")
                previous_record = body.record
                if body.record and body.record.artifact_id != head.subject_id:
                    raise ValueError("history backup evidence scope differs")
            elif not isinstance(event.body, FiscalControlBindingV1):
                raise ValueError("history backup control contains evidence")
            else:
                reference = event.body.payload_ref
                control_artifact = artifacts.get(reference.artifact_id)
                if (
                    control_artifact is None
                    or control_artifact.content_hash != reference.content_hash
                    or control_artifact.media_type != reference.media_type
                ):
                    raise ValueError(
                        "history backup control payload is absent or inconsistent"
                    )
            previous = _required(indexed, "event_digest")
            last_at = event.recorded_at
            rank = ranks[event.origin_id]
            previous_event = event
        if (
            len(events) != head.sequence
            or previous != head.event_digest
            or last_at != head.recorded_at
        ):
            raise ValueError("history backup stream does not reach its head")
        if (
            head.stream_kind == "evidence"
            and artifacts.get(head.subject_id) != previous_record
        ):
            raise ValueError("history backup evidence does not reach current metadata")
    for cutover in epoch.cutovers:
        prefix_heads = []
        for stream, events in grouped.items():
            if check_budget is not None:
                check_budget()
            prefix = [
                event
                for event in events
                if ranks[event.origin_id] <= ranks[cutover.source_origin_id]
            ]
            if not prefix:
                continue
            last = max(prefix, key=lambda event: event.sequence)
            indexed = indexed_events[(stream, last.sequence)]
            prefix_heads.append(
                FiscalHistoryHeadV1(
                    stream_id=stream,
                    stream_kind=last.stream_kind,
                    subject_id=last.subject_id,
                    sequence=last.sequence,
                    event_digest=_required(indexed, "event_digest"),
                    recorded_at=last.recorded_at,
                )
            )
            if (
                commit_receipts[(last.origin_id, last.writer_xid8)].visible_by
                >= cutover.source_frontier_at
            ):
                raise ValueError("history ancestor frontier is incomplete")
        if history_heads_digest(prefix_heads) != cutover.source_heads_digest:
            raise ValueError("history ancestor head set differs")
    return epoch
