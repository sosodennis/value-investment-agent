from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from fundamental_service.history_recovery_contracts import RecoveryAuthorizationV1
from fundamental_service.persistence_recovery import (
    RecoveryReceiptV2,
    _connect,
    _database_identity,
    _verify_bundle,
    restore_backup as restore_authorized_backup,
)
from fundamental_service.serialization import canonical_bytes


def assert_same_data_plane_projection(
    first: RecoveryReceiptV2, second: RecoveryReceiptV2, backups: Path
) -> None:
    original = _verify_bundle(backups / first.manifest_digest, first.manifest_digest)
    repeated = _verify_bundle(backups / second.manifest_digest, second.manifest_digest)
    assert (
        repeated.history_frontier.covered_through
        > original.history_frontier.covered_through
    )
    assert repeated.objects == original.objects

    def domain_tables(manifest):
        return tuple(
            table
            for table in manifest.tables
            if not table.name.startswith("fiscal_history_")
            and table.name not in {"schema_migrations", "schema_capabilities"}
        )

    assert domain_tables(repeated) == domain_tables(original)


async def restore_backup(
    database_url: str,
    content_root: Path,
    bundle: Path,
    *,
    manifest_digest: str,
    authorization_path: Path | None = None,
    deadline_at: datetime | None = None,
) -> RecoveryReceiptV2:
    if authorization_path is not None:
        return await restore_authorized_backup(
            database_url,
            content_root,
            bundle,
            manifest_digest=manifest_digest,
            authorization_path=authorization_path,
            deadline_at=deadline_at,
        )
    role = os.environ["FUNDAMENTAL_TEST_RECOVERY_RUNTIME_ROLE"]
    connection = await _connect(database_url)
    try:
        target = await _database_identity(connection)
    finally:
        await connection.close()
    payload = json.loads((bundle / "manifest.json").read_bytes())
    authorization = RecoveryAuthorizationV1(
        manifest_digest=manifest_digest,
        source_origin_id=payload.get("history_frontier", {}).get(
            "origin_id", "00000000-0000-0000-0000-000000000001"
        ),
        expected_target=target,
        runtime_role=role,
        source_fence_reference="synthetic:isolated-test-source",
    )
    content_root.parent.mkdir(parents=True, exist_ok=True)
    path = content_root.parent / (
        "synthetic-recovery-pin-" + str(target.database_oid) + ".json"
    )
    path.write_bytes(canonical_bytes(authorization))
    path.chmod(0o600)
    return await restore_authorized_backup(
        database_url,
        content_root,
        bundle,
        manifest_digest=manifest_digest,
        authorization_path=path,
        deadline_at=deadline_at,
    )
