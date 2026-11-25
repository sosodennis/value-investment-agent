"""Offline, digest-checked recovery of Fundamental metadata and source bytes."""

from __future__ import annotations

import argparse
import asyncio
import errno
import hashlib
import json
import os
import re
import sys
import tempfile
import stat
from datetime import UTC, datetime, timedelta
from contextvars import ContextVar
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator, Iterator
from typing import BinaryIO
from importlib import resources
from pathlib import Path
from typing import Literal, TypeVar

import asyncpg
from pydantic import AwareDatetime, BaseModel, Field, ValidationError, model_validator

from .contracts import CanonicalFactV1, SourceSnapshotV1, StrictModel
from .data_releases import (
    ActiveDataReleaseV1,
    DataReleaseActivationCommandV1,
    DataReleaseManifestV1,
    DataReleaseVerificationV1,
)
from .facts import (
    CanonicalMappingV1,
    canonical_fact_digest,
    verify_accounting_role_evidence,
)
from .history_composition import verify_history_components
from .history_recovery_contracts import (
    FiscalHistoryFrontierV1,
    RecoveryAuthorizationV1,
    PostgresDatabaseIdentityV1,
    FiscalRecoveryActivationV1,
)
from .fiscal_history_backup import (
    verify_fiscal_history_backup,
    history_heads_digest,
    BackupRow,
)
from .fiscal_admission_history import FiscalHistoryHeadV1
from .metadata import SCHEMA_VERSION
from .parser_action_contracts import read_action_result
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError


_OPERATION_DEADLINE: ContextVar[datetime | None] = ContextVar(
    "persistence_recovery_deadline", default=None
)
_MAX_BACKUP_BYTES = 8 * 1024**3
_MAX_BACKUP_ROWS = 1_000_000
_MAX_BACKUP_FILES = 100_000
_MAX_METADATA_BYTES = 256 * 1024**2
_MAX_ROW_BYTES = 8 * 1024**2


class RecoveryError(RuntimeError):
    """A backup or target failed validation; existing evidence is retained."""


def _check_budget() -> None:
    deadline = _OPERATION_DEADLINE.get()
    if deadline is not None and datetime.now(UTC) >= deadline:
        raise RecoveryError("persistence recovery deadline exceeded")


def _copy_file(source: BinaryIO, target: BinaryIO) -> None:
    while True:
        _check_budget()
        chunk = source.read(1024 * 1024)
        if not chunk:
            return
        target.write(chunk)


BackupRecordTable = Literal[
    "canonical_facts", "mapping_decisions", "snapshot_manifests"
]
RecordT = TypeVar("RecordT", bound=BaseModel)


class RecoveryRecordError(RecoveryError):
    """Identify a refused record without retaining its payload or raw identity."""

    def __init__(self, table: BackupRecordTable, identity: str) -> None:
        super().__init__("backup record does not satisfy the installed contract")
        self.table = table
        self.record_identity_digest = sha256_digest(identity)


def _validate_backup_record(
    model: type[RecordT], payload: str, *, table: BackupRecordTable, identity: str
) -> RecordT:
    try:
        return model.model_validate_json(payload)
    except ValidationError:
        raise RecoveryRecordError(table, identity) from None


class BackupFileV1(StrictModel):
    path: str
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_length: int = Field(ge=0)


class BackupTableV1(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    columns: tuple[str, ...] = Field(min_length=1)
    row_count: int = Field(ge=0)
    file: BackupFileV1


class PersistenceBackupV2(StrictModel):
    protocol: Literal["fundamental-persistence-backup-v2"] = (
        "fundamental-persistence-backup-v2"
    )
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    migration_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_version: Literal["fundamental-metadata-v2"] = "fundamental-metadata-v2"
    postgres_major: int = Field(ge=14)
    tables: tuple[BackupTableV1, ...] = Field(min_length=1)
    objects: tuple[BackupFileV1, ...]
    history_frontier: FiscalHistoryFrontierV1

    @model_validator(mode="after")
    def paths_are_canonical(self) -> PersistenceBackupV2:
        if (
            len(self.objects) > _MAX_BACKUP_FILES
            or sum(table.row_count for table in self.tables) > _MAX_BACKUP_ROWS
            or sum(table.file.byte_length for table in self.tables)
            > _MAX_METADATA_BYTES
            or sum(item.byte_length for item in self.objects)
            + sum(table.file.byte_length for table in self.tables)
            > _MAX_BACKUP_BYTES
        ):
            raise ValueError("backup exceeds installed recovery limits")
        names = tuple(table.name for table in self.tables)
        if names != tuple(sorted(set(names))):
            raise ValueError("backup tables must be unique and sorted")
        for table in self.tables:
            if table.file.path != f"tables/{table.name}.jsonl":
                raise ValueError("backup table path must match its name")
        paths = tuple(item.path for item in self.objects)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("backup objects must be unique and sorted")
        for item in self.objects:
            expected = f"content/{item.digest[:2]}/{item.digest}"
            if item.path not in {expected + ".json", expected + ".bin"}:
                raise ValueError("backup object path must match its digest")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)


class RecoveryReceiptV2(StrictModel):
    manifest_digest: str
    wrote: bool
    table_count: int
    row_count: int
    object_count: int
    history_frontier: FiscalHistoryFrontierV1
    target_origin_id: str | None = None
    operation_id: str | None = None
    activation: FiscalRecoveryActivationV1 | None = None


class _SecRequestSlotV1(StrictModel):
    rate_key: Literal["sec-edgar"]
    next_request_at: AwareDatetime


class _ReleasePointerV1(StrictModel):
    profile_id: str = Field(min_length=1)
    manifest_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    revision: int = Field(ge=0)
    activated_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def coherent(self) -> _ReleasePointerV1:
        if self.revision == 0:
            if self.manifest_digest is not None or self.activated_at is not None:
                raise ValueError("unactivated release pointer contains an activation")
        elif self.manifest_digest is None or self.activated_at is None:
            raise ValueError("active release pointer lacks an activation")
        return self


class _ParserActionIndexV1(StrictModel):
    action_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_id: str = Field(min_length=1)


class _ReleaseActivationV1(StrictModel):
    command_id: str = Field(min_length=1)
    profile_id: str = Field(min_length=1)
    operation: Literal["activate", "rollback"]
    expected_revision: int = Field(ge=0)
    expected_manifest_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    from_manifest_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    to_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    actor_id: str = Field(min_length=1)
    organization_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    resulting_revision: int = Field(gt=0)
    activated_at: AwareDatetime

    def command(self) -> DataReleaseActivationCommandV1:
        return DataReleaseActivationCommandV1(
            **self.model_dump(
                exclude={
                    "from_manifest_digest",
                    "to_manifest_digest",
                    "resulting_revision",
                    "activated_at",
                }
            ),
            manifest_digest=self.to_manifest_digest,
        )

    def pointer(self) -> _ReleasePointerV1:
        active = ActiveDataReleaseV1(
            profile_id=self.profile_id,
            manifest_digest=self.to_manifest_digest,
            revision=self.resulting_revision,
            activated_at=self.activated_at,
        )
        return _ReleasePointerV1.model_validate(active.model_dump())


def _migrations() -> dict[str, str]:
    root = resources.files("fundamental_service").joinpath("migrations")
    return {
        item.name: item.read_text(encoding="utf-8")
        for item in sorted(root.iterdir(), key=lambda item: item.name)
        if item.name.endswith(".sql")
    }


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", value):
        raise RecoveryError("unexpected database identifier")
    return f'"{value}"'


async def _connect(database_url: str) -> asyncpg.Connection:
    database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(database_url, command_timeout=60)
    await connection.execute(
        "SET TIME ZONE 'UTC'; SET datestyle TO 'ISO, YMD'; "
        "SET bytea_output TO 'hex'; SET extra_float_digits TO 3; "
        "SET intervalstyle TO 'postgres'; SET lock_timeout TO '10s'"
    )
    return connection


async def _layout(
    connection: asyncpg.Connection,
) -> tuple[dict[str, tuple[str, ...]], str]:
    rows = await connection.fetch(
        "SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod) AS type, "
        "a.attnotnull, a.attidentity::text, pg_get_expr(d.adbin, d.adrelid) AS default_expr "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "JOIN pg_attribute a ON a.attrelid=c.oid "
        "LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum "
        "WHERE n.nspname='fundamental' AND c.relkind='r' "
        "AND a.attnum>0 AND NOT a.attisdropped ORDER BY c.relname, a.attnum"
    )
    columns: dict[str, tuple[str, ...]] = {}
    for row in rows:
        name, column = row["relname"], row["attname"]
        _identifier(name)
        _identifier(column)
        columns[name] = (*columns.get(name, ()), column)
    expected = set(
        re.findall(
            r"CREATE TABLE IF NOT EXISTS fundamental\.([a-z_]+)",
            "\n".join(_migrations().values()),
        )
    )
    if set(columns) != expected:
        raise RecoveryError("metadata tables do not match the installed migrations")
    version = await connection.fetchval(
        "SELECT version FROM fundamental.schema_migrations "
        "ORDER BY applied_at DESC, version DESC LIMIT 1"
    )
    if version != SCHEMA_VERSION:
        raise RecoveryError("metadata schema version is incompatible")
    constraints = await connection.fetch(
        "SELECT c.relname, k.conname, pg_get_constraintdef(k.oid) AS definition "
        "FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='fundamental' ORDER BY c.relname, k.conname"
    )
    return columns, sha256_digest(
        {
            "columns": [dict(row) for row in rows],
            "constraints": [dict(row) for row in constraints],
        }
    )


async def _lock(
    connection: asyncpg.Connection, tables: dict[str, tuple[str, ...]], *, restore: bool
) -> None:
    names = ", ".join(f"fundamental.{_identifier(name)}" for name in sorted(tables))
    mode = "ACCESS EXCLUSIVE" if restore else "SHARE"
    await connection.execute(f"LOCK TABLE {names} IN {mode} MODE")


def _file_record(path: Path, root: Path) -> BackupFileV1:
    if path.is_symlink() or not path.is_file():
        raise RecoveryError("backup entries must be regular files")
    _check_budget()
    if path.stat().st_size > _MAX_BACKUP_BYTES:
        raise RecoveryError("backup file exceeds its byte limit")
    digest_state = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            _check_budget()
            digest_state.update(chunk)
    digest = digest_state.hexdigest()
    _check_budget()
    return BackupFileV1(
        path=path.relative_to(root).as_posix(),
        digest=digest,
        byte_length=path.stat().st_size,
    )


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        _check_budget()
        os.fsync(descriptor)
        _check_budget()
    finally:
        os.close(descriptor)


async def _export_tables(
    connection: asyncpg.Connection, root: Path, tables: dict[str, tuple[str, ...]]
) -> tuple[BackupTableV1, ...]:
    (root / "tables").mkdir()
    result: list[BackupTableV1] = []
    total_bytes = 0
    total_rows = 0
    for name, columns in sorted(tables.items()):
        fields = ",".join(f"{_identifier(column)}::text" for column in columns)
        query = (
            f"SELECT row FROM (SELECT json_build_array({fields})::text AS row "
            f"FROM fundamental.{_identifier(name)}) AS backup_rows "
            'ORDER BY row COLLATE "C"'
        )
        path = root / "tables" / f"{name}.jsonl"
        count = 0
        with path.open("wb") as handle:
            async for record in connection.cursor(query, prefetch=500):
                _check_budget()
                if total_rows >= _MAX_BACKUP_ROWS:
                    raise RecoveryError("backup exceeds installed row limit")
                raw = canonical_bytes(json.loads(record["row"])) + b"\n"
                total_bytes += len(raw)
                if len(raw) > _MAX_ROW_BYTES or total_bytes > _MAX_METADATA_BYTES:
                    raise RecoveryError("backup exceeds installed metadata byte limit")
                handle.write(raw)
                count += 1
                total_rows += 1
            handle.flush()
            os.fsync(handle.fileno())
        result.append(
            BackupTableV1(
                name=name,
                columns=columns,
                row_count=count,
                file=_file_record(path, root),
            )
        )
    return tuple(result)


def _content_inventory(root: Path) -> tuple[BackupFileV1, ...]:
    if root.is_symlink():
        raise RecoveryError("content root must not be a symlink")
    result: list[BackupFileV1] = []
    total_bytes = 0
    for index, path in enumerate(root.rglob("*")):
        _check_budget()
        if index > _MAX_BACKUP_FILES * 2 or len(result) >= _MAX_BACKUP_FILES:
            raise RecoveryError("content inventory exceeds its file limit")
        if path.is_symlink():
            raise RecoveryError("content store must not contain symlinks")
        if path.relative_to(root).parts[0] == ".restore-pending":
            continue
        if path.is_dir():
            continue
        item = _file_record(path, root)
        total_bytes += item.byte_length
        if total_bytes > _MAX_BACKUP_BYTES:
            raise RecoveryError("content inventory exceeds its byte limit")
        if item.path not in {
            f"{item.digest[:2]}/{item.digest}.json",
            f"{item.digest[:2]}/{item.digest}.bin",
        }:
            raise RecoveryError("content name or bytes failed digest verification")
        result.append(item.model_copy(update={"path": f"content/{item.path}"}))
    return tuple(sorted(result, key=lambda item: item.path))


def _verify_bundle(root: Path, digest: str) -> PersistenceBackupV2:
    if root.is_symlink():
        raise RecoveryError("backup root must not be a symlink")
    path = root / "manifest.json"
    if path.is_symlink():
        raise RecoveryError("backup manifest must not be a symlink")
    if path.stat().st_size > 32 * 1024 * 1024:
        raise RecoveryError("backup manifest exceeds its byte limit")
    _check_budget()
    payload = path.read_bytes()
    manifest = PersistenceBackupV2.model_validate_json(payload)
    if manifest.digest != digest or payload != canonical_bytes(manifest):
        raise RecoveryError("backup manifest does not match its pinned digest")
    files = tuple(table.file for table in manifest.tables) + manifest.objects
    expected = {item.path for item in files} | {"manifest.json"}
    observed: set[str] = set()
    for entry in root.rglob("*"):
        _check_budget()
        if len(observed) > _MAX_BACKUP_FILES + 128:
            raise RecoveryError("backup inventory exceeds its entry limit")
        if entry.is_symlink():
            raise RecoveryError("backup must not contain symlinks")
        if not entry.is_dir():
            observed.add(entry.relative_to(root).as_posix())
    if observed != expected:
        raise RecoveryError(
            "backup inventory is incomplete or contains undeclared files"
        )
    for item in files:
        if _file_record(root / item.path, root) != item:
            raise RecoveryError("backup file failed digest verification")
    _verify_rows(root, manifest)
    try:
        verify_fiscal_history_backup(
            _backup_tables(root, manifest),
            manifest.history_frontier,
            check_budget=_check_budget,
        )
    except ValueError as error:
        raise RecoveryError(
            "backup fiscal history is incomplete or inconsistent"
        ) from error
    return manifest


def _rows(root: Path, table: BackupTableV1) -> Iterator[BackupRow]:
    count = 0
    byte_count = 0
    digest = hashlib.sha256()
    with (root / table.file.path).open("rb") as handle:
        while line := handle.readline(_MAX_ROW_BYTES + 1):
            _check_budget()
            if len(line) > _MAX_ROW_BYTES or count >= _MAX_BACKUP_ROWS:
                raise RecoveryError("backup rows exceed installed limits")
            digest.update(line)
            byte_count += len(line)
            row = json.loads(line)
            if (
                not isinstance(row, list)
                or len(row) != len(table.columns)
                or any(
                    value is not None and not isinstance(value, str) for value in row
                )
                or line != canonical_bytes(row) + b"\n"
            ):
                raise RecoveryError("backup row has an incompatible shape")
            count += 1
            yield dict(zip(table.columns, row, strict=True))
    if (
        count != table.row_count
        or byte_count != table.file.byte_length
        or digest.hexdigest() != table.file.digest
    ):
        raise RecoveryError("backup row count or bytes do not match the manifest")


class _BackupSnapshots:
    def __init__(self) -> None:
        self.snapshots: dict[str, SourceSnapshotV1] = {}

    def get(self, snapshot_id: str) -> SourceSnapshotV1:
        try:
            return self.snapshots[snapshot_id]
        except KeyError as error:
            raise SnapshotError(
                "HISTORY_COMPONENT_MISSING", "history original is absent from backup"
            ) from error


def _required_value(row: BackupRow, key: str) -> str:
    value = row[key]
    if value is None:
        raise RecoveryError("backup metadata lacks a required value")
    return value


def _metadata_state(model: type[RecordT], row: BackupRow) -> RecordT:
    try:
        decoded = {
            key: datetime.fromisoformat(value)
            if key in {"activated_at", "next_request_at"} and isinstance(value, str)
            else value
            for key, value in row.items()
        }
        return model.model_validate(decoded, strict=False)
    except ValueError as error:
        raise RecoveryError("mutable metadata state has an invalid contract") from error


def _verify_release_activation_state(
    manifests: dict[str, DataReleaseManifestV1],
    verifications: dict[str, DataReleaseVerificationV1],
    pointers: dict[str, _ReleasePointerV1],
    activations: list[_ReleaseActivationV1],
) -> None:
    if set(manifests) != set(verifications):
        raise RecoveryError("data release candidate verification is incomplete")
    by_profile: dict[str, list[_ReleaseActivationV1]] = {}
    for activation in activations:
        by_profile.setdefault(activation.profile_id, []).append(activation)
    for profile_id in set(pointers) | set(by_profile):
        expected = _ReleasePointerV1(profile_id=profile_id, revision=0)
        previous_targets: set[str] = set()
        for activation in sorted(
            by_profile.get(profile_id, ()), key=lambda item: item.resulting_revision
        ):
            _check_budget()
            try:
                command = activation.command()
            except ValidationError as error:
                raise RecoveryError(
                    "data release activation command is invalid"
                ) from error
            manifest = manifests.get(command.manifest_digest)
            if (
                manifest is None
                or manifest.profile_id != profile_id
                or command.expected_revision != expected.revision
                or command.expected_manifest_digest != expected.manifest_digest
                or activation.from_manifest_digest != expected.manifest_digest
                or activation.resulting_revision != expected.revision + 1
                or command.operation == "rollback"
                and command.manifest_digest not in previous_targets
            ):
                raise RecoveryError("data release activation audit is discontinuous")
            expected = activation.pointer()
            previous_targets.add(command.manifest_digest)
        if pointers.get(profile_id) != expected:
            raise RecoveryError("active data release pointer differs from its audit")


def _verify_rows(
    root: Path, manifest: PersistenceBackupV2, *, content_root: Path | None = None
) -> None:
    objects = {item.path: item for item in manifest.objects}
    hashes = {item.digest for item in manifest.objects}
    snapshots = _BackupSnapshots()
    accounting_facts: list[CanonicalFactV1] = []
    mappings: dict[str, CanonicalMappingV1] = {}
    artifacts: dict[str, tuple[str, str]] = {}
    release_manifests: dict[str, DataReleaseManifestV1] = {}
    release_verifications: dict[str, DataReleaseVerificationV1] = {}
    release_pointers: dict[str, _ReleasePointerV1] = {}
    release_activations: list[_ReleaseActivationV1] = []

    def require_content(content_hash: str, media_type: str) -> BackupFileV1:
        suffix = ".json" if media_type == "application/json" else ".bin"
        item = objects.get(f"content/{content_hash[:2]}/{content_hash}{suffix}")
        if item is None:
            raise RecoveryError(
                "metadata references source or artifact bytes absent from backup"
            )
        return item

    for table in manifest.tables:
        for row in _rows(root, table):
            if table.name == "content_objects":
                item = require_content(
                    _required_value(row, "content_hash"),
                    _required_value(row, "media_type"),
                )
                if item.byte_length != int(_required_value(row, "byte_length")):
                    raise RecoveryError("registered content size does not match bytes")
            elif table.name == "artifact_references":
                content_hash, media_type = (
                    _required_value(row, "content_hash"),
                    _required_value(row, "media_type"),
                )
                require_content(content_hash, media_type)
                artifacts[_required_value(row, "artifact_id")] = (
                    content_hash,
                    media_type,
                )
            elif table.name == "parser_action_results":
                reference = artifacts.get(_required_value(row, "artifact_id"))
                if reference is None or reference[1] != "application/json":
                    raise RecoveryError(
                        "parser action index references absent evidence"
                    )
                item = require_content(*reference)
                try:
                    path = (
                        root / item.path
                        if content_root is None
                        else content_root / item.path.removeprefix("content/")
                    )
                    result = read_action_result(path.read_bytes())
                except ValueError as error:
                    raise RecoveryError(
                        "parser action result contract differs"
                    ) from error
                if (
                    result.request.digest != row["action_key"]
                    or result.artifact_id != row["artifact_id"]
                ):
                    raise RecoveryError("parser action index identity differs")
                require_content(result.report_content_hash, "application/json")
                if artifacts.get(
                    f"sec-parser-action-report-v1:{result.report_content_hash}"
                ) != (result.report_content_hash, "application/json"):
                    raise RecoveryError("parser action report reference is absent")
            elif table.name == "sec_provider_rate_limits":
                _metadata_state(_SecRequestSlotV1, row)
            elif table.name == "active_data_release_pointers":
                pointer = _metadata_state(_ReleasePointerV1, row)
                release_pointers[pointer.profile_id] = pointer
            elif table.name == "data_release_activation_audit":
                release_activations.append(_metadata_state(_ReleaseActivationV1, row))
            elif table.name == "data_release_manifests":
                try:
                    release_manifest = DataReleaseManifestV1.model_validate_json(
                        _required_value(row, "payload")
                    )
                except ValidationError as error:
                    raise RecoveryError("data release manifest is invalid") from error
                if (
                    release_manifest.manifest_digest != row["manifest_digest"]
                    or release_manifest.profile_id != row["profile_id"]
                    or release_manifest.release_id != row["release_id"]
                ):
                    raise RecoveryError("data release manifest identity differs")
                release_manifests[release_manifest.manifest_digest] = release_manifest
            elif table.name == "data_release_verifications":
                try:
                    release_verification = (
                        DataReleaseVerificationV1.model_validate_json(
                            _required_value(row, "payload")
                        )
                    )
                except ValidationError as error:
                    raise RecoveryError(
                        "data release verification is invalid"
                    ) from error
                if (
                    release_verification.manifest_digest != row["manifest_digest"]
                    or release_verification.verification_digest
                    != row["verification_digest"]
                ):
                    raise RecoveryError("data release verification identity differs")
                release_verifications[release_verification.manifest_digest] = (
                    release_verification
                )
            elif table.name == "snapshot_manifests":
                snapshot = _validate_backup_record(
                    SourceSnapshotV1,
                    _required_value(row, "payload"),
                    table="snapshot_manifests",
                    identity=_required_value(row, "snapshot_id"),
                )
                if (
                    snapshot.manifest_digest != row["manifest_digest"]
                    or snapshot.snapshot_id != row["snapshot_id"]
                ):
                    raise RecoveryError("snapshot metadata digest is inconsistent")
                if snapshot.snapshot_id in snapshots.snapshots:
                    raise RecoveryError("backup contains duplicate snapshot identities")
                snapshots.snapshots[snapshot.snapshot_id] = snapshot
                for source in snapshot.source_records:
                    require_content(source.content_hash, source.media_type)
            elif table.name == "canonical_facts":
                fact = _validate_backup_record(
                    CanonicalFactV1,
                    _required_value(row, "payload"),
                    table="canonical_facts",
                    identity=_required_value(row, "fact_id"),
                )
                if fact.source.content_hash not in hashes:
                    raise RecoveryError("canonical fact source is absent from backup")
                if (
                    fact.fact_id != row["fact_id"]
                    or canonical_fact_digest(fact) != row["fact_digest"]
                ):
                    raise RecoveryError(
                        "canonical fact metadata digest is inconsistent"
                    )
                if fact.accounting_evidence is not None:
                    accounting_facts.append(fact)
            elif table.name == "mapping_decisions":
                mapping = _validate_backup_record(
                    CanonicalMappingV1,
                    _required_value(row, "payload"),
                    table="mapping_decisions",
                    identity=_required_value(row, "mapping_id"),
                )
                if (
                    mapping.decision_id != row["mapping_id"]
                    or sha256_digest(mapping) != row["mapping_digest"]
                ):
                    raise RecoveryError(
                        "canonical mapping metadata digest is inconsistent"
                    )
                mappings[mapping.decision_id] = mapping
    _verify_release_activation_state(
        release_manifests, release_verifications, release_pointers, release_activations
    )
    for snapshot in snapshots.snapshots.values():
        try:
            verify_history_components(snapshot, snapshots)
        except SnapshotError as error:
            raise RecoveryError(
                "backup history does not match its retained original snapshots"
            ) from error
    for fact in accounting_facts:
        role_mapping = mappings.get(fact.mapping_decision_id or "")
        if role_mapping is None:
            raise RecoveryError("computed accounting fact has no retained mapping")
        bound = False
        for snapshot in snapshots.snapshots.values():
            if snapshot.identity.issuer_id != fact.issuer_id or not any(
                source.content_hash == fact.source.content_hash
                for source in snapshot.source_records
            ):
                continue
            try:
                verify_accounting_role_evidence(fact, role_mapping, snapshot)
            except SnapshotError:
                continue
            bound = True
            break
        if not bound:
            raise RecoveryError(
                "computed accounting evidence has no matching original snapshot"
            )


def _receipt(manifest: PersistenceBackupV2, *, wrote: bool) -> RecoveryReceiptV2:
    return RecoveryReceiptV2(
        manifest_digest=manifest.digest,
        wrote=wrote,
        table_count=len(manifest.tables),
        row_count=sum(table.row_count for table in manifest.tables),
        object_count=len(manifest.objects),
        history_frontier=manifest.history_frontier,
    )


async def _export_backup(
    database_url: str, content_root: Path, destination: Path, *, source_revision: str
) -> RecoveryReceiptV2:
    if not content_root.is_dir():
        raise RecoveryError("source content directory is unavailable")
    if (
        content_root.resolve() == destination.resolve()
        or content_root.resolve() in destination.resolve().parents
    ):
        raise RecoveryError("backup destination must be outside the content store")
    destination.mkdir(parents=True, exist_ok=True)
    connection = await _connect(database_url)
    try:
        with tempfile.TemporaryDirectory(
            prefix=".backup-", dir=destination
        ) as temporary:
            stage = Path(temporary)
            async with _locked_export(connection) as (tables, schema_digest):
                exported = await _export_tables(connection, stage, tables)
                objects = _content_inventory(content_root)
                inventory = {item.path: item for item in objects}
                for row in await connection.fetch(
                    "SELECT * FROM fundamental.content_objects"
                ):
                    content_hash = row["content_hash"]
                    suffix = (
                        ".json" if row["media_type"] == "application/json" else ".bin"
                    )
                    item = inventory.get(
                        f"content/{content_hash[:2]}/{content_hash}{suffix}"
                    )
                    if item is None or item.byte_length != row["byte_length"]:
                        raise RecoveryError(
                            "registered content is missing or has a different size"
                        )
                for item in objects:
                    target = stage / item.path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with (
                        (content_root / item.path.removeprefix("content/")).open(
                            "rb"
                        ) as source,
                        target.open("wb") as handle,
                    ):
                        _copy_file(source, handle)
                        handle.flush()
                        os.fsync(handle.fileno())
                if objects != _content_inventory(content_root):
                    raise RecoveryError(
                        "content changed during export; stop writers and retry"
                    )
                manifest = PersistenceBackupV2(
                    source_revision=source_revision,
                    migration_digest=sha256_digest(_migrations()),
                    schema_digest=schema_digest,
                    postgres_major=connection.get_server_version().major,
                    tables=exported,
                    objects=objects,
                    history_frontier=await _frontier(connection),
                )
                with (stage / "manifest.json").open("wb") as handle:
                    handle.write(canonical_bytes(manifest))
                    handle.flush()
                    os.fsync(handle.fileno())
                _verify_bundle(stage, manifest.digest)
                for directory in sorted(
                    (entry for entry in stage.rglob("*") if entry.is_dir()),
                    reverse=True,
                ):
                    _sync_directory(directory)
                _sync_directory(stage)
            target = destination / manifest.digest
            try:
                os.rename(stage, target)
            except OSError as error:
                if error.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
                    raise
                _verify_bundle(target, manifest.digest)
                return _receipt(manifest, wrote=False)
            _sync_directory(destination)
            return _receipt(manifest, wrote=True)
    finally:
        await connection.close()


async def _restore_order(
    connection: asyncpg.Connection, tables: dict[str, tuple[str, ...]]
) -> tuple[str, ...]:
    dependencies: dict[str, set[str]] = {name: set() for name in tables}
    for row in await connection.fetch(
        "SELECT child.relname AS child, parent.relname AS parent, pn.nspname AS parent_schema "
        "FROM pg_constraint k JOIN pg_class child ON child.oid=k.conrelid "
        "JOIN pg_namespace cn ON cn.oid=child.relnamespace "
        "JOIN pg_class parent ON parent.oid=k.confrelid "
        "JOIN pg_namespace pn ON pn.oid=parent.relnamespace "
        "WHERE k.contype='f' AND cn.nspname='fundamental'"
    ):
        if row["parent_schema"] != "fundamental":
            raise RecoveryError("foreign keys must remain Fundamental-owned")
        dependencies[row["child"]].add(row["parent"])
    order: list[str] = []
    while dependencies:
        ready = sorted(
            name for name, parents in dependencies.items() if not parents - set(order)
        )
        if not ready:
            raise RecoveryError("cyclic restore dependencies are unsupported")
        order.extend(ready)
        for name in ready:
            del dependencies[name]
    return tuple(order)


async def _restore_backup(
    database_url: str,
    content_root: Path,
    bundle: Path,
    *,
    manifest_digest: str,
    authorization_path: Path,
) -> RecoveryReceiptV2:
    manifest = _verify_bundle(bundle, manifest_digest)
    if manifest.migration_digest != sha256_digest(_migrations()):
        raise RecoveryError("backup migrations do not match the installed release")
    authorization = _read_authorization(authorization_path)
    if (
        authorization.manifest_digest != manifest_digest
        or authorization.source_origin_id != manifest.history_frontier.origin_id
    ):
        raise RecoveryError("recovery authorization differs from the pinned bundle")
    connection = await _connect(database_url)
    try:
        if connection.get_server_version().major != manifest.postgres_major:
            raise RecoveryError("backup PostgreSQL major version is incompatible")
        if await _database_identity(connection) != authorization.expected_target:
            raise RecoveryError("recovery target identity differs from authorization")
        if not await connection.fetchval(
            "SELECT to_regnamespace('fundamental') IS NOT NULL"
        ):
            for migration in _migrations().values():
                async with connection.transaction():
                    await connection.execute(migration)
        await _require_recovery_access(connection, authorization.runtime_role)
        local = str(
            await connection.fetchval("SELECT fundamental.fiscal_history_origin_id()")
        )
        operation = authorization.operation_id
        async with connection.transaction():
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended('fundamental-recovery',0))"
            )
            tables, schema_digest = await _layout(connection)
            await _lock(connection, tables, restore=True)
            if (
                schema_digest != manifest.schema_digest
                or {table.name: table.columns for table in manifest.tables} != tables
            ):
                raise RecoveryError(
                    "backup schema or PostgreSQL major version is incompatible"
                )
            existing = await connection.fetchrow(
                "SELECT * FROM fundamental.fiscal_history_restore_links WHERE target_origin_id=$1::uuid",
                local,
            )
            if existing is not None:
                if (
                    existing["operation_id"] != operation
                    or existing["source_manifest_digest"] != manifest_digest
                ):
                    raise RecoveryError(
                        "restore target contains a different recovery operation"
                    )
                await _verify_imported_prefix(
                    connection, bundle, manifest, local, allow_local_changes=True
                )
                await _verify_current_state(connection, content_root, manifest)
                wrote = False
            else:
                await _require_bootstrap(connection, tables, local)
                await _publish_content(content_root, bundle, manifest)
                await _install_bundle(
                    connection, bundle, manifest, authorization, local
                )
                await _verify_imported_prefix(connection, bundle, manifest, local)
                wrote = True
        await _activate_import(connection, local)
        activation_row = await connection.fetchrow(
            "SELECT committed_at,visible_by FROM fundamental.fiscal_history_activation_receipts WHERE target_origin_id=$1::uuid",
            local,
        )
        if activation_row is None:
            raise RecoveryError("recovery activation is pending")
        activation = FiscalRecoveryActivationV1.model_validate(dict(activation_row))
        if datetime.now(UTC) <= activation.visible_by:
            raise RecoveryError("recovery activation clock is not yet proven")
        return _receipt(manifest, wrote=wrote).model_copy(
            update={
                "target_origin_id": local,
                "operation_id": operation,
                "activation": activation,
            }
        )
    finally:
        await connection.close()


async def _activate_import(connection: asyncpg.Connection, local: str) -> None:
    async with connection.transaction():
        await connection.execute(
            "SELECT fundamental.fiscal_history_activate($1::uuid)", local
        )


def _installed_tables() -> dict[str, tuple[str, ...]]:
    return {
        name: ()
        for name in re.findall(
            r"CREATE TABLE IF NOT EXISTS fundamental\.([a-z_]+)",
            "\n".join(_migrations().values()),
        )
    }


def _backup_tables(
    root: Path, manifest: PersistenceBackupV2
) -> dict[str, list[BackupRow]]:
    return {table.name: list(_rows(root, table)) for table in manifest.tables}


async def _database_identity(
    connection: asyncpg.Connection,
) -> PostgresDatabaseIdentityV1:
    row = await connection.fetchrow(
        "SELECT system_identifier::text,timeline_id,(SELECT oid::bigint FROM pg_database WHERE datname=current_database()) AS database_oid FROM pg_control_system(),pg_control_checkpoint()"
    )
    return PostgresDatabaseIdentityV1.model_validate(dict(row))


async def _pending_export_writers(
    connection: asyncpg.Connection,
) -> list[asyncpg.Record]:
    rows = await connection.fetch(
        "SELECT DISTINCT e.origin_id::text,e.writer_xid8::text FROM fundamental.fiscal_history_events e LEFT JOIN fundamental.fiscal_history_commit_receipts r USING(origin_id,writer_xid8) WHERE r.origin_id IS NULL ORDER BY 1,2 LIMIT 100001"
    )
    if len(rows) > 100000:
        raise RecoveryError("history export pending writers exceed the operation bound")
    return rows


async def _seal_export_writers(connection: asyncpg.Connection) -> None:
    for row in await _pending_export_writers(connection):
        _check_budget()
        async with connection.transaction():
            await connection.execute(
                "SELECT fundamental.fiscal_history_seal($1::uuid,$2::xid8)",
                row["origin_id"],
                int(row["writer_xid8"]),
            )


@asynccontextmanager
async def _locked_export(
    connection: asyncpg.Connection,
) -> AsyncIterator[tuple[dict[str, tuple[str, ...]], str]]:
    for _ in range(3):
        await _seal_export_writers(connection)
        transaction = connection.transaction(isolation="read_committed")
        await transaction.start()
        try:
            await _lock(connection, _installed_tables(), restore=False)
            if await _pending_export_writers(connection):
                await transaction.rollback()
                continue
            layout = await _layout(connection)
            yield layout
            await transaction.commit()
            return
        except BaseException:
            await transaction.rollback()
            raise
    raise RecoveryError("history export could not obtain a sealed source frontier")


async def _frontier(connection: asyncpg.Connection) -> FiscalHistoryFrontierV1:
    heads = [
        FiscalHistoryHeadV1.model_validate(dict(row))
        for row in await connection.fetch(
            "SELECT * FROM fundamental.fiscal_history_streams ORDER BY stream_id"
        )
    ]
    return FiscalHistoryFrontierV1(
        origin_id=str(
            await connection.fetchval("SELECT fundamental.fiscal_history_origin_id()")
        ),
        covered_through=await connection.fetchval("SELECT clock_timestamp()"),
        heads_digest=history_heads_digest(heads),
    )


def _read_authorization(path: Path) -> RecoveryAuthorizationV1:
    flags = os.O_RDONLY | os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
            or metadata.st_size > 16_384
        ):
            raise RecoveryError(
                "recovery authorization requires an owner-private regular file"
            )
        raw = os.read(fd, 16_385)
        authorization = RecoveryAuthorizationV1.model_validate_json(raw)
        if raw != canonical_bytes(authorization):
            raise RecoveryError("recovery authorization must have canonical bytes")
        return authorization
    finally:
        os.close(fd)


async def _require_recovery_access(
    connection: asyncpg.Connection, runtime_role: str
) -> None:
    owner = await connection.fetchval(
        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid='fundamental.fiscal_history_origin'::regclass"
    )
    user = await connection.fetchval("SELECT session_user")
    if user != owner:
        raise RecoveryError("offline recovery requires the metadata owner")
    runtime = await connection.fetchrow(
        "SELECT rolsuper,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=$1",
        runtime_role,
    )
    if runtime is None or any(runtime.values()) or runtime_role == owner:
        raise RecoveryError(
            "recovery requires an independent least-privilege runtime role"
        )
    if await connection.fetchval(
        "SELECT pg_has_role($1,$2,'MEMBER')", runtime_role, owner
    ):
        raise RecoveryError("runtime role can assume the metadata owner")
    if await connection.fetchval(
        "SELECT has_schema_privilege($1,'fundamental','CREATE')", runtime_role
    ):
        raise RecoveryError("runtime role can change the metadata schema")
    for privilege in ("USAGE", "CREATE"):
        if await connection.fetchval(
            "SELECT has_schema_privilege($1,'fundamental_recovery',$2)",
            runtime_role,
            privilege,
        ):
            raise RecoveryError("runtime role can access recovery staging")
    for signature in (
        "fundamental.fiscal_recovery_freeze_stage()",
        "fundamental.fiscal_history_activate(uuid)",
    ):
        if await connection.fetchval(
            "SELECT has_function_privilege($1,$2,'EXECUTE')", runtime_role, signature
        ):
            raise RecoveryError("runtime role can execute offline recovery")
    owned = await connection.fetchval(
        "SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('fundamental','fundamental_recovery') AND pg_has_role($1,c.relowner,'MEMBER'))",
        runtime_role,
    )
    if owned:
        raise RecoveryError("runtime role owns protected metadata relations")


async def _require_bootstrap(
    connection: asyncpg.Connection, tables: dict[str, tuple[str, ...]], local: str
) -> None:
    bootstrap = {
        "schema_migrations",
        "schema_capabilities",
        "fiscal_history_origin",
        "fiscal_history_local_origin",
    }
    for name in tables:
        count = await connection.fetchval(
            f"SELECT count(*) FROM fundamental.{_identifier(name)}"
        )
        if name not in bootstrap and count:
            raise RecoveryError("restore requires an empty or identical metadata store")
    for name in ("fiscal_history_origin", "fiscal_history_local_origin"):
        values = await connection.fetch(
            f"SELECT origin_id::text FROM fundamental.{name}"
        )
        if len(values) != 1 or values[0]["origin_id"] != local:
            raise RecoveryError(
                "restore target does not contain its exact bootstrap origin"
            )
    migrations = "\n".join(_migrations().values())
    for table, column in (
        ("schema_migrations", "version"),
        ("schema_capabilities", "capability_id"),
    ):
        expected = set(
            re.findall(
                rf"INSERT INTO fundamental\.{table}\({column}\)\s+VALUES \('([^']+)'\)",
                migrations,
            )
        )
        actual = {
            row[column]
            for row in await connection.fetch(
                f"SELECT {_identifier(column)} FROM fundamental.{_identifier(table)}"
            )
        }
        if actual != expected:
            raise RecoveryError("restore target contains non-bootstrap schema records")


async def _publish_content(
    content_root: Path, bundle: Path, manifest: PersistenceBackupV2
) -> None:
    expected = {item.path: item for item in manifest.objects}
    for item in _content_inventory(content_root):
        if expected.get(item.path) != item:
            raise RecoveryError("target contains unrelated or conflicting content")
    for item in manifest.objects:
        target = content_root / item.path.removeprefix("content/")
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        pending = content_root / ".restore-pending"
        pending.mkdir(exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="restore-", dir=pending)
        try:
            with (
                os.fdopen(fd, "wb") as handle,
                (bundle / item.path).open("rb") as source,
            ):
                _copy_file(source, handle)
                handle.flush()
                os.fsync(handle.fileno())
            checked = _file_record(Path(temporary), Path(temporary).parent)
            if checked.digest != item.digest or checked.byte_length != item.byte_length:
                raise RecoveryError(
                    "copied recovery content differs from the pinned bytes"
                )
            _check_budget()
            os.link(temporary, target)
            _sync_directory(target.parent)
        finally:
            os.unlink(temporary)
    if manifest.objects:
        _sync_directory(content_root)
        _sync_directory(content_root.parent)


async def _normalized_row(
    connection: asyncpg.Connection, name: str, row: BackupRow
) -> str:
    json_columns = await connection.fetch(
        "SELECT attname FROM pg_attribute WHERE attrelid=$1::regclass AND atttypid IN ('json'::regtype,'jsonb'::regtype) AND attnum>0",
        "fundamental." + name,
    )
    decoded: dict[str, object] = dict(row)
    for column in json_columns:
        value = row[column["attname"]]
        decoded[column["attname"]] = json.loads(value) if value is not None else None
    normalized = await connection.fetchval(
        f"SELECT to_jsonb(jsonb_populate_record(NULL::fundamental.{_identifier(name)},$1::jsonb))::text",
        json.dumps(decoded),
    )
    if normalized is None:
        raise RecoveryError("recovery row normalization failed")
    return normalized


async def _stage_row(connection: asyncpg.Connection, name: str, row: BackupRow) -> None:
    normalized = await _normalized_row(connection, name, row)
    await connection.execute(
        "INSERT INTO fundamental_recovery.rows VALUES(pg_backend_pid(),$1,$2,$3::jsonb)",
        name,
        hashlib.sha256(normalized.encode()).hexdigest(),
        normalized,
    )


async def _install_bundle(
    connection: asyncpg.Connection,
    bundle: Path,
    manifest: PersistenceBackupV2,
    authorization: RecoveryAuthorizationV1,
    local: str,
) -> None:
    if manifest.history_frontier.origin_id == local:
        raise RecoveryError("recovery cannot import its own local origin")
    now = await connection.fetchval("SELECT clock_timestamp()")
    if now <= manifest.history_frontier.covered_through:
        raise RecoveryError("recovery target clock precedes source frontier")
    await connection.execute(
        "INSERT INTO fundamental_recovery.context VALUES(pg_backend_pid(),pg_current_xact_id(),$1::uuid,$2,$3,NULL)",
        local,
        manifest.digest,
        authorization.operation_id,
    )
    skip = {"schema_migrations", "schema_capabilities", "fiscal_history_local_origin"}
    for table in manifest.tables:
        if table.name in skip:
            continue
        for row in _rows(bundle, table):
            await _stage_row(connection, table.name, row)
    link: BackupRow = {
        "target_origin_id": local,
        "source_origin_id": manifest.history_frontier.origin_id,
        "operation_id": authorization.operation_id,
        "source_manifest_digest": manifest.digest,
        "source_frontier_at": manifest.history_frontier.covered_through.isoformat(),
        "source_heads_digest": manifest.history_frontier.heads_digest,
        "import_writer_xid8": str(
            await connection.fetchval("SELECT pg_current_xact_id()::text")
        ),
        "runtime_role": authorization.runtime_role,
    }
    await _stage_row(connection, "fiscal_history_restore_links", link)
    await connection.execute("SELECT fundamental.fiscal_recovery_freeze_stage()")
    tables = {table.name: table.columns for table in manifest.tables}
    order = await _restore_order(connection, tables)
    for name in order:
        if name in skip:
            continue
        if name == "fiscal_history_streams":
            continue
        if name == "fiscal_history_events":
            await connection.execute(
                "INSERT INTO fundamental.fiscal_history_streams SELECT (jsonb_populate_record(NULL::fundamental.fiscal_history_streams,row_data)).* FROM fundamental_recovery.rows WHERE backend_pid=pg_backend_pid() AND table_name='fiscal_history_streams'"
            )
        await connection.execute(
            f"INSERT INTO fundamental.{_identifier(name)} OVERRIDING SYSTEM VALUE SELECT (jsonb_populate_record(NULL::fundamental.{_identifier(name)},row_data)).* FROM fundamental_recovery.rows WHERE backend_pid=pg_backend_pid() AND table_name=$1",
            name,
        )
    await connection.execute(
        "DELETE FROM fundamental_recovery.context WHERE backend_pid=pg_backend_pid()"
    )
    await connection.execute(
        "DELETE FROM fundamental_recovery.rows WHERE backend_pid=pg_backend_pid()"
    )
    await connection.execute(
        "SELECT setval(pg_get_serial_sequence('fundamental.source_acquisition_audits','audit_id'), GREATEST(COALESCE(MAX(audit_id),1),1),COUNT(*)>0) FROM fundamental.source_acquisition_audits"
    )


async def _verify_imported_prefix(
    connection: asyncpg.Connection,
    bundle: Path,
    manifest: PersistenceBackupV2,
    local: str,
    *,
    allow_local_changes: bool = False,
) -> None:
    for table in manifest.tables:
        if table.name in {
            "schema_migrations",
            "schema_capabilities",
            "fiscal_history_local_origin",
        }:
            continue
        for row in _rows(bundle, table):
            normalized = await _normalized_row(connection, table.name, row)
            if table.name == "fiscal_history_streams":
                identity = row["stream_id"]
                actual = await connection.fetchrow(
                    "SELECT sequence,event_digest FROM fundamental.fiscal_history_streams WHERE stream_id=$1",
                    identity,
                )
                if actual is None or actual["sequence"] < int(row["sequence"] or "0"):
                    raise RecoveryError("restored history prefix is missing")
                digest = await connection.fetchval(
                    "SELECT event_digest FROM fundamental.fiscal_history_events WHERE stream_id=$1 AND sequence=$2",
                    identity,
                    int(row["sequence"] or "0"),
                )
                if digest != row["event_digest"]:
                    raise RecoveryError("restored history prefix digest differs")
            elif table.name == "artifact_references" and allow_local_changes:
                current = await connection.fetchval(
                    "SELECT to_jsonb(value) - 'status' - 'retention' FROM fundamental.artifact_references value WHERE artifact_id=$1",
                    row["artifact_id"],
                )
                expected = json.loads(normalized)
                expected.pop("status")
                expected.pop("retention")
                if current is None or json.loads(current) != expected:
                    raise RecoveryError("restored artifact identity differs")
            elif table.name == "sec_provider_rate_limits" and allow_local_changes:
                original_slot = _metadata_state(_SecRequestSlotV1, row)
                current_slot_row = await connection.fetchrow(
                    "SELECT rate_key,next_request_at FROM fundamental.sec_provider_rate_limits WHERE rate_key=$1",
                    original_slot.rate_key,
                )
                if current_slot_row is None:
                    raise RecoveryError("restored SEC request slot is missing")
                current_slot = _metadata_state(
                    _SecRequestSlotV1, dict(current_slot_row)
                )
                if current_slot.next_request_at < original_slot.next_request_at:
                    raise RecoveryError("restored SEC request slot moved backwards")
            elif table.name == "active_data_release_pointers" and allow_local_changes:
                original_pointer = _metadata_state(_ReleasePointerV1, row)
                current_pointer_row = await connection.fetchrow(
                    "SELECT * FROM fundamental.active_data_release_pointers WHERE profile_id=$1",
                    original_pointer.profile_id,
                )
                if current_pointer_row is None:
                    raise RecoveryError("restored data release pointer is missing")
                current_pointer = _metadata_state(
                    _ReleasePointerV1, dict(current_pointer_row)
                )
                if current_pointer.revision < original_pointer.revision or (
                    current_pointer.revision == original_pointer.revision
                    and current_pointer != original_pointer
                ):
                    raise RecoveryError("restored data release pointer diverged")
            elif table.name == "parser_action_results" and allow_local_changes:
                original_index = _metadata_state(_ParserActionIndexV1, row)
                current_index_row = await connection.fetchrow(
                    "SELECT action_key,artifact_id FROM fundamental.parser_action_results WHERE action_key=$1",
                    original_index.action_key,
                )
                if current_index_row is None:
                    raise RecoveryError("restored parser action index is missing")
                _metadata_state(_ParserActionIndexV1, dict(current_index_row))
            elif not await connection.fetchval(
                f"SELECT EXISTS(SELECT 1 FROM fundamental.{_identifier(table.name)} value WHERE to_jsonb(value)=$1::jsonb)",
                normalized,
            ):
                raise RecoveryError("restored metadata failed digest verification")

    if not allow_local_changes:
        for table in manifest.tables:
            if table.name in {
                "schema_migrations",
                "schema_capabilities",
                "fiscal_history_local_origin",
            }:
                continue
            count = await connection.fetchval(
                f"SELECT count(*) FROM fundamental.{_identifier(table.name)}"
            )
            extra = (
                1
                if table.name
                in {"fiscal_history_origin", "fiscal_history_restore_links"}
                else 0
            )
            if count != table.row_count + extra:
                raise RecoveryError("restored metadata inventory differs")


async def _verify_current_state(
    connection: asyncpg.Connection, content_root: Path, original: PersistenceBackupV2
) -> None:
    await _seal_export_writers(connection)
    tables, schema_digest = await _layout(connection)
    with tempfile.TemporaryDirectory(
        prefix="fundamental-recovery-readback-"
    ) as directory:
        root = Path(directory)
        exported = await _export_tables(connection, root, tables)
        objects = _content_inventory(content_root)
        current = PersistenceBackupV2(
            source_revision=original.source_revision,
            migration_digest=original.migration_digest,
            schema_digest=schema_digest,
            postgres_major=original.postgres_major,
            tables=exported,
            objects=objects,
            history_frontier=await _frontier(connection),
        )
        _verify_rows(root, current, content_root=content_root)
        try:
            verify_fiscal_history_backup(
                _backup_tables(root, current),
                current.history_frontier,
                allow_pending_local=True,
                check_budget=_check_budget,
            )
        except ValueError as error:
            raise RecoveryError(
                "current recovery metadata graph is inconsistent"
            ) from error


async def export_backup(
    database_url: str,
    content_root: Path,
    destination: Path,
    *,
    source_revision: str,
    deadline_at: datetime | None = None,
) -> RecoveryReceiptV2:
    deadline = deadline_at or datetime.now(UTC) + timedelta(seconds=300)
    if deadline.utcoffset() is None:
        raise RecoveryError("persistence recovery deadline must be timezone aware")
    remaining = (deadline - datetime.now(UTC)).total_seconds()
    if remaining <= 0 or remaining > 3600:
        raise RecoveryError("persistence recovery deadline is invalid or expired")
    token = _OPERATION_DEADLINE.set(deadline)
    try:
        async with asyncio.timeout(remaining):
            result = await _export_backup(
                database_url, content_root, destination, source_revision=source_revision
            )
            _check_budget()
            return result
    except TimeoutError as error:
        raise RecoveryError("persistence recovery deadline exceeded") from error
    finally:
        _OPERATION_DEADLINE.reset(token)


async def restore_backup(
    database_url: str,
    content_root: Path,
    bundle: Path,
    *,
    manifest_digest: str,
    authorization_path: Path,
    deadline_at: datetime | None = None,
) -> RecoveryReceiptV2:
    deadline = deadline_at or datetime.now(UTC) + timedelta(seconds=300)
    if deadline.utcoffset() is None:
        raise RecoveryError("persistence recovery deadline must be timezone aware")
    remaining = (deadline - datetime.now(UTC)).total_seconds()
    if remaining <= 0 or remaining > 3600:
        raise RecoveryError("persistence recovery deadline is invalid or expired")
    token = _OPERATION_DEADLINE.set(deadline)
    try:
        async with asyncio.timeout(remaining):
            result = await _restore_backup(
                database_url,
                content_root,
                bundle,
                manifest_digest=manifest_digest,
                authorization_path=authorization_path,
            )
            _check_budget()
            return result
    except TimeoutError as error:
        raise RecoveryError("persistence recovery deadline exceeded") from error
    finally:
        _OPERATION_DEADLINE.reset(token)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    export = subparsers.add_parser("export")
    export.add_argument("--destination", type=Path, required=True)
    export.add_argument("--source-revision", required=True)
    restore = subparsers.add_parser("restore")
    restore.add_argument("--bundle", type=Path, required=True)
    restore.add_argument("--manifest-digest", required=True)
    restore.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--deadline-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    try:
        database_url = os.environ["FUNDAMENTAL_SERVICE_DATABASE_URL"]
        content_root = Path(os.environ["FUNDAMENTAL_SERVICE_DATA_ROOT"]) / "content"
        if args.operation == "export":
            receipt = asyncio.run(
                export_backup(
                    database_url,
                    content_root,
                    args.destination,
                    source_revision=args.source_revision,
                    deadline_at=datetime.now(UTC)
                    + timedelta(seconds=args.deadline_seconds),
                )
            )
        else:
            receipt = asyncio.run(
                restore_backup(
                    database_url,
                    content_root,
                    args.bundle,
                    manifest_digest=args.manifest_digest,
                    authorization_path=args.authorization,
                    deadline_at=datetime.now(UTC)
                    + timedelta(seconds=args.deadline_seconds),
                )
            )
    except RecoveryRecordError as error:
        print(
            canonical_bytes(
                {
                    "protocol": "fundamental-persistence-error-v1",
                    "code": "BACKUP_RECORD_CONTRACT_INVALID",
                    "table": error.table,
                    "record_identity_digest": error.record_identity_digest,
                }
            ).decode("utf-8"),
            file=sys.stderr,
        )
        return 2
    except (
        RecoveryError,
        SnapshotError,
        ValueError,
        OSError,
        KeyError,
        asyncpg.PostgresError,
    ):
        print(
            "persistence recovery failed validation or storage access", file=sys.stderr
        )
        return 2
    print(canonical_bytes(receipt).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
