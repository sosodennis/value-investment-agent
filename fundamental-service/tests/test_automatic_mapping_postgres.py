"""Machine decisions and original bytes survive service restart and recovery."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

from cryptography.hazmat.primitives import serialization

from fundamental_service.automatic_mapping import AutomaticMappingDecisionV1
from fundamental_service.automatic_mapping_runner import approve_mapping
from fundamental_service.metadata import (
    PostgresArtifactStore,
    PostgresContentStore,
    PostgresMetadataStore,
)
from fundamental_service.persistence_recovery import export_backup, restore_backup
from fundamental_service.serialization import canonical_bytes
from test_automatic_mapping import case, MACHINE_KEY, REVISION
from test_issuer_operating_release import inventory


def test_machine_approval_cli_restart_and_empty_store_restore(
    tmp_path, recovery_databases
):
    source_db, target_db = recovery_databases
    request, offline, roots, _ = case(tmp_path)
    request_path = tmp_path / "request.json"
    request_path.write_bytes(canonical_bytes(request))
    roots_path = tmp_path / "roots.json"
    roots_path.write_bytes(canonical_bytes(roots))
    key_path = tmp_path / "machine.pem"
    key_path.write_bytes(
        MACHINE_KEY.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    content = tmp_path / "source" / "content"
    metadata = PostgresMetadataStore(source_db, auto_migrate=True)
    metadata.start()
    try:
        artifacts = PostgresArtifactStore(
            metadata, PostgresContentStore(content, metadata)
        )
        for ref in request.evidence_refs:
            publication = artifacts.put_bytes_with_receipt(
                ref.artifact_id,
                offline.read(ref.artifact_id),
                media_type=ref.media_type,
            )
            assert publication.artifact.content_hash == ref.content_hash
        expected = approve_mapping(
            request, artifacts=artifacts, trust_roots=roots, private_key=MACHINE_KEY
        )
    finally:
        metadata.close()
    command = [
        sys.executable,
        "-m",
        "fundamental_service.automatic_mapping_runner",
        "--request",
        str(request_path),
        "--trust-roots",
        str(roots_path),
        "--private-key",
        str(key_path),
    ]
    environment = dict(
        os.environ,
        PYTHONPATH=str(Path(__file__).parents[1] / "src"),
        FUNDAMENTAL_SERVICE_DATABASE_URL=source_db,
        FUNDAMENTAL_SERVICE_DATA_ROOT=str(content.parent),
    )
    before = inventory(content)
    repeated = []
    for _ in range(2):
        run = subprocess.run(command, env=environment, capture_output=True, check=True)
        assert not run.stderr
        receipt = json.loads(run.stdout)
        assert receipt["input_digest"] == expected.input_digest
        assert receipt["output_digest"] == expected.output_digest
        assert all(
            not receipt[key]["wrote"]
            for key in (
                "input_publication",
                "decision_publication",
                "approval_publication",
            )
        )
        repeated.append(run.stdout)
    assert repeated[0] == repeated[1] and before == inventory(content)
    backup_root = tmp_path / "backups"
    backup = asyncio.run(
        export_backup(source_db, content, backup_root, source_revision=REVISION)
    )
    restored = tmp_path / "restored" / "content"
    asyncio.run(
        restore_backup(
            target_db,
            restored,
            backup_root / backup.manifest_digest,
            manifest_digest=backup.manifest_digest,
        )
    )
    before_restore_repeat = inventory(restored)
    recovered = subprocess.run(
        command,
        env={
            **environment,
            "FUNDAMENTAL_SERVICE_DATABASE_URL": target_db,
            "FUNDAMENTAL_SERVICE_DATA_ROOT": str(restored.parent),
        },
        capture_output=True,
        check=True,
    )
    assert recovered.stdout == repeated[0] and not recovered.stderr
    assert inventory(restored) == before_restore_repeat
    target = PostgresMetadataStore(target_db, auto_migrate=False)
    target.start()
    try:
        artifacts = PostgresArtifactStore(
            target, PostgresContentStore(restored, target)
        )
        decision = AutomaticMappingDecisionV1.model_validate_json(
            artifacts.read(expected.decision_publication.artifact.artifact_id)
        )
        assert decision.status == "approved" and decision.mapping.observation_scope
        for ref in request.evidence_refs:
            assert artifacts.read(ref.artifact_id) == offline.read(ref.artifact_id)
    finally:
        target.close()
    assert not asyncio.run(
        export_backup(target_db, restored, backup_root, source_revision=REVISION)
    ).wrote
