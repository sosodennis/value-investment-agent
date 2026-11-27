from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from fundamental_service.fiscal_admission_history import PostgresFiscalAdmissionHistory
from fundamental_service.snapshots import SnapshotError
import test_fiscal_admission_authority as authority_cases

metadata = authority_cases.metadata
artifacts = authority_cases.artifacts
database_url = authority_cases.database_url


def deadline():
    return datetime.now(UTC) + timedelta(seconds=60)


def test_whole_observation_exceeds_single_batch_in_one_readonly_snapshot(
    metadata, artifacts, monkeypatch
):
    records = tuple(
        artifacts.put_with_receipt(
            "synthetic-whole:" + str(index).zfill(4), {"synthetic": index}
        ).artifact
        for index in range(270)
    )
    history = PostgresFiscalAdmissionHistory(metadata)
    for start in range(0, len(records), 256):
        history.checkpoint(records[start : start + 256], deadline_at=deadline())
    epoch = history.read_epoch(deadline_at=deadline())
    read_group = history._stream_group
    changed = False
    read_groups = []

    async def racing(streams, connection, *, remaining_entries, remaining_bytes):
        nonlocal changed
        group = await read_group(
            streams,
            connection,
            remaining_entries=remaining_entries,
            remaining_bytes=remaining_bytes,
        )
        read_groups.append(streams)
        if not changed and "evidence:synthetic-whole:0260" in streams:
            async with metadata._runner._engine.begin() as writer:
                await writer.execute(
                    text(
                        "UPDATE fundamental.artifact_references SET status='invalidated' WHERE artifact_id IN (:first,:last)"
                    ),
                    {"first": records[0].artifact_id, "last": records[-1].artifact_id},
                )
            changed = True
        return group

    monkeypatch.setattr(history, "_stream_group", racing)
    observed = history.finish_observation(records, (), epoch, deadline_at=deadline())
    assert changed
    assert len(read_groups) > 1
    assert len(observed.heads) == 270
    assert {entry.event.body.record.artifact_id for entry in observed.entries} == {
        record.artifact_id for record in records
    }
    assert artifacts.get(records[0].artifact_id).status == "invalidated"
    assert artifacts.get(records[-1].artifact_id).status == "invalidated"
    with pytest.raises(SnapshotError):
        history.finish_observation(records, (), epoch, deadline_at=deadline())


def test_whole_observation_rejects_duplicate_total_limits_changed_heads_and_epoch(
    metadata, artifacts
):
    history = PostgresFiscalAdmissionHistory(metadata)
    record = artifacts.put_with_receipt(
        "synthetic-whole-bounds", {"synthetic": True}
    ).artifact
    observed = history.checkpoint((record,), deadline_at=deadline())
    epoch = observed.epoch
    for records in (
        (record, record),
        tuple(
            record.model_copy(
                update={"artifact_id": "synthetic-too-many:" + str(index)}
            )
            for index in range(4097)
        ),
    ):
        with pytest.raises(SnapshotError):
            history.finish_observation(records, (), epoch, deadline_at=deadline())
    for heads, selected_epoch in (
        ((observed.heads[0].model_copy(update={"sequence": 2}),), epoch),
        (observed.heads, epoch.model_copy(update={"local_origin_id": str(uuid4())})),
    ):
        with pytest.raises(SnapshotError):
            history.finish_observation(
                (record,), heads, selected_epoch, deadline_at=deadline()
            )
