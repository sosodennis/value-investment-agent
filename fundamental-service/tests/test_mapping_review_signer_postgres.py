from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import asyncpg
import pytest
from sqlalchemy.exc import SQLAlchemyError

from fundamental_service.data_releases import (
    DataReleaseTrustRootsV1,
    MappingReviewEvidenceV1,
    MappingReviewStatementV1,
    sign_mapping_review_evidence,
    verify_mapping_review_evidence,
)
from fundamental_service.facts import CanonicalMappingV1
from fundamental_service.mapping_review_signer import main
from fundamental_service.metadata import (
    PostgresArtifactStore,
    PostgresContentStore,
    PostgresMetadataStore,
)
from fundamental_service.persistence_recovery import export_backup, restore_backup
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_mapping_review_signer import (
    REVISION,
    SYNTHETIC_REVIEW_KEY,
    _argv,
    _file_inventory,
    _inputs,
)


def _service_argv(paths: dict[str, Path]) -> list[str]:
    return _argv(
        {name: path for name, path in paths.items() if name != "artifacts-root"}
    )


def test_service_signing_survives_restart_and_backup_restore(
    tmp_path: Path, recovery_databases: tuple[str, str]
) -> None:
    source_db, target_db = recovery_databases
    paths = _inputs(tmp_path)
    data_root = tmp_path / "service"
    content_root = data_root / "content"
    seed = PostgresMetadataStore(source_db, auto_migrate=True)
    seed.start()
    try:
        source = ArtifactStore(paths["artifacts-root"])
        evidence = source.get("synthetic-disclosure")
        PostgresArtifactStore(seed, PostgresContentStore(content_root, seed)).put(
            evidence.artifact_id, json.loads(source.read(evidence.artifact_id))
        )
        seed.publish_mapping(
            CanonicalMappingV1.model_validate_json(paths["mapping"].read_bytes())
        )
    finally:
        seed.close()
    command = [
        sys.executable,
        "-m",
        "fundamental_service.mapping_review_signer",
        *_service_argv(paths),
    ]
    environment = dict(
        os.environ,
        PYTHONPATH=str(Path(__file__).parents[1] / "src"),
        FUNDAMENTAL_SERVICE_DATABASE_URL=source_db,
        FUNDAMENTAL_SERVICE_DATA_ROOT=str(data_root),
    )
    first = subprocess.run(command, env=environment, capture_output=True, check=True)
    assert not first.stderr
    receipt = json.loads(first.stdout)
    assert receipt["publication"]["wrote"] is True
    unsigned = MappingReviewStatementV1.model_validate_json(
        paths["statement"].read_bytes()
    )
    signed = sign_mapping_review_evidence(
        unsigned.model_dump(mode="python"), SYNTHETIC_REVIEW_KEY
    )
    assert receipt["output_digest"] == sha256_digest(signed)
    backups = tmp_path / "backups"
    backup = asyncio.run(
        export_backup(source_db, content_root, backups, source_revision=REVISION)
    )
    before = _file_inventory(data_root)
    expected = {**receipt, "publication": {**receipt["publication"], "wrote": False}}
    for _ in range(2):
        repeated = subprocess.run(
            command, env=environment, capture_output=True, check=True
        )
        assert not repeated.stderr
        assert json.loads(repeated.stdout) == expected
        assert _file_inventory(data_root) == before
    assert asyncio.run(
        export_backup(source_db, content_root, backups, source_revision=REVISION)
    ) == backup.model_copy(update={"wrote": False})
    restored_root = tmp_path / "restored-service"
    restored_content = restored_root / "content"
    assert (
        asyncio.run(
            restore_backup(
                target_db,
                restored_content,
                backups / backup.manifest_digest,
                manifest_digest=backup.manifest_digest,
            )
        )
        == backup
    )
    restored_before = _file_inventory(restored_root)
    restored = subprocess.run(
        command,
        env={
            **environment,
            "FUNDAMENTAL_SERVICE_DATABASE_URL": target_db,
            "FUNDAMENTAL_SERVICE_DATA_ROOT": str(restored_root),
        },
        capture_output=True,
        check=True,
    )
    assert not restored.stderr
    assert json.loads(restored.stdout) == expected
    assert _file_inventory(restored_root) == restored_before
    reopened = PostgresMetadataStore(target_db)
    try:
        reopened.start()
        artifacts = PostgresArtifactStore(
            reopened, PostgresContentStore(restored_content, reopened)
        )
        retained = artifacts.read(receipt["publication"]["artifact"]["artifact_id"])
        assert retained == canonical_bytes(signed)
        verify_mapping_review_evidence(
            MappingReviewEvidenceV1.model_validate_json(retained),
            DataReleaseTrustRootsV1.from_file(paths["trust-roots"]),
        )
    finally:
        reopened.close()
    assert (
        asyncio.run(
            export_backup(
                target_db, restored_content, backups, source_revision=REVISION
            )
        ).wrote
        is False
    )


def test_service_signer_requires_configured_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _inputs(tmp_path)
    monkeypatch.delenv("FUNDAMENTAL_SERVICE_DATABASE_URL", raising=False)
    monkeypatch.delenv("FUNDAMENTAL_SERVICE_DATA_ROOT", raising=False)
    before = _file_inventory(tmp_path)
    assert main(_service_argv(paths)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error_code": "MAPPING_REVIEW_STORAGE_UNCONFIGURED"
    }
    assert _file_inventory(tmp_path) == before


def test_service_signer_redacts_invalid_database_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _inputs(tmp_path)
    monkeypatch.setenv(
        "FUNDAMENTAL_SERVICE_DATABASE_URL", "secret-user:secret-password@invalid"
    )
    monkeypatch.setenv("FUNDAMENTAL_SERVICE_DATA_ROOT", str(tmp_path / "service"))
    assert main(_service_argv(paths)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"error_code": "MAPPING_REVIEW_INPUT_INVALID"}
    assert not (tmp_path / "service").exists()


def test_service_signer_does_not_initialize_missing_schema(
    tmp_path: Path,
    recovery_databases: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_db, _ = recovery_databases
    paths = _inputs(tmp_path)
    monkeypatch.setenv("FUNDAMENTAL_SERVICE_DATABASE_URL", source_db)
    monkeypatch.setenv("FUNDAMENTAL_SERVICE_DATA_ROOT", str(tmp_path / "service"))
    monkeypatch.setenv("FUNDAMENTAL_SERVICE_AUTO_MIGRATE", "1")
    assert main(_service_argv(paths)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"error_code": "METADATA_SCHEMA_UNAVAILABLE"}

    async def schema_exists() -> bool:
        connection = await asyncpg.connect(
            source_db.replace("postgresql+asyncpg://", "postgresql://")
        )
        try:
            return await connection.fetchval(
                "SELECT to_regnamespace('fundamental') IS NOT NULL"
            )
        finally:
            await connection.close()

    assert asyncio.run(schema_exists()) is False
    assert not (tmp_path / "service").exists()


def test_storage_errors_do_not_expose_credentials_or_query_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _inputs(tmp_path)

    def fail_read(self: ArtifactStore, artifact_id: str) -> None:
        raise SQLAlchemyError("secret-user:secret-password private SQL parameter")

    monkeypatch.setattr(ArtifactStore, "get", fail_read)
    before = _file_inventory(tmp_path)
    assert main(_argv(paths)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"error_code": "MAPPING_REVIEW_STORAGE_FAILED"}
    assert _file_inventory(tmp_path) == before
