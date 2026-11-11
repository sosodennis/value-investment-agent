"""Offline, digest-checked recovery of Fundamental metadata and source bytes."""

from __future__ import annotations

import argparse
import asyncio
import errno
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from importlib import resources
from pathlib import Path
from typing import Literal

import asyncpg
from pydantic import Field, model_validator

from .contracts import SourceSnapshotV1, StrictModel
from .metadata import SCHEMA_VERSION, PostgresMetadataStore
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError


class RecoveryError(RuntimeError):
    """A backup or target failed validation; existing evidence is retained."""


class BackupFileV1(StrictModel):
    path: str
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_length: int = Field(ge=0)


class BackupTableV1(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    columns: tuple[str, ...] = Field(min_length=1)
    row_count: int = Field(ge=0)
    file: BackupFileV1


class PersistenceBackupV1(StrictModel):
    protocol: Literal["fundamental-persistence-backup-v1"] = (
        "fundamental-persistence-backup-v1"
    )
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    migration_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_version: Literal["fundamental-metadata-v2"] = "fundamental-metadata-v2"
    postgres_major: int = Field(ge=14)
    tables: tuple[BackupTableV1, ...] = Field(min_length=1)
    objects: tuple[BackupFileV1, ...]

    @model_validator(mode="after")
    def paths_are_canonical(self) -> PersistenceBackupV1:
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


class RecoveryReceiptV1(StrictModel):
    manifest_digest: str
    wrote: bool
    table_count: int
    row_count: int
    object_count: int


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


async def _lock(connection: asyncpg.Connection, tables: dict, *, restore: bool) -> None:
    names = ", ".join(f"fundamental.{_identifier(name)}" for name in sorted(tables))
    mode = "ACCESS EXCLUSIVE" if restore else "SHARE"
    await connection.execute(f"LOCK TABLE {names} IN {mode} MODE")


def _file_record(path: Path, root: Path) -> BackupFileV1:
    if path.is_symlink() or not path.is_file():
        raise RecoveryError("backup entries must be regular files")
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return BackupFileV1(
        path=path.relative_to(root).as_posix(),
        digest=digest,
        byte_length=path.stat().st_size,
    )


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


async def _export_tables(
    connection: asyncpg.Connection, root: Path, tables: dict[str, tuple[str, ...]]
) -> tuple[BackupTableV1, ...]:
    (root / "tables").mkdir()
    result = []
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
                handle.write(canonical_bytes(json.loads(record["row"])) + b"\n")
                count += 1
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
    result = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RecoveryError("content store must not contain symlinks")
        if path.relative_to(root).parts[0] == ".restore-pending":
            continue
        if path.is_dir():
            continue
        item = _file_record(path, root)
        if item.path not in {
            f"{item.digest[:2]}/{item.digest}.json",
            f"{item.digest[:2]}/{item.digest}.bin",
        }:
            raise RecoveryError("content name or bytes failed digest verification")
        result.append(item.model_copy(update={"path": f"content/{item.path}"}))
    return tuple(result)


def _verify_bundle(root: Path, digest: str) -> PersistenceBackupV1:
    if root.is_symlink():
        raise RecoveryError("backup root must not be a symlink")
    path = root / "manifest.json"
    if path.is_symlink():
        raise RecoveryError("backup manifest must not be a symlink")
    payload = path.read_bytes()
    manifest = PersistenceBackupV1.model_validate_json(payload)
    if manifest.digest != digest or payload != canonical_bytes(manifest):
        raise RecoveryError("backup manifest does not match its pinned digest")
    files = tuple(table.file for table in manifest.tables) + manifest.objects
    expected = {item.path for item in files} | {"manifest.json"}
    observed = set()
    for entry in root.rglob("*"):
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
    return manifest


def _rows(root: Path, table: BackupTableV1):
    count = 0
    with (root / table.file.path).open("rb") as handle:
        for line in handle:
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
    if count != table.row_count:
        raise RecoveryError("backup row count does not match the manifest")


def _verify_rows(root: Path, manifest: PersistenceBackupV1) -> None:
    objects = {item.path: item for item in manifest.objects}
    hashes = {item.digest for item in manifest.objects}

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
                item = require_content(row["content_hash"], row["media_type"])
                if item.byte_length != int(row["byte_length"]):
                    raise RecoveryError("registered content size does not match bytes")
            elif table.name == "artifact_references":
                require_content(row["content_hash"], row["media_type"])
            elif table.name == "snapshot_manifests":
                snapshot = SourceSnapshotV1.model_validate_json(row["payload"])
                if (
                    snapshot.manifest_digest != row["manifest_digest"]
                    or snapshot.snapshot_id != row["snapshot_id"]
                ):
                    raise RecoveryError("snapshot metadata digest is inconsistent")
                for source in snapshot.source_records:
                    require_content(source.content_hash, source.media_type)
            elif table.name == "canonical_facts":
                if json.loads(row["payload"])["source"]["content_hash"] not in hashes:
                    raise RecoveryError("canonical fact source is absent from backup")


def _receipt(manifest: PersistenceBackupV1, *, wrote: bool) -> RecoveryReceiptV1:
    return RecoveryReceiptV1(
        manifest_digest=manifest.digest,
        wrote=wrote,
        table_count=len(manifest.tables),
        row_count=sum(table.row_count for table in manifest.tables),
        object_count=len(manifest.objects),
    )


async def export_backup(
    database_url: str, content_root: Path, destination: Path, *, source_revision: str
) -> RecoveryReceiptV1:
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
            async with connection.transaction(isolation="repeatable_read"):
                tables, schema_digest = await _layout(connection)
                await _lock(connection, tables, restore=False)
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
                        shutil.copyfileobj(source, handle)
                        handle.flush()
                        os.fsync(handle.fileno())
                if objects != _content_inventory(content_root):
                    raise RecoveryError(
                        "content changed during export; stop writers and retry"
                    )
                manifest = PersistenceBackupV1(
                    source_revision=source_revision,
                    migration_digest=sha256_digest(_migrations()),
                    schema_digest=schema_digest,
                    postgres_major=connection.get_server_version().major,
                    tables=exported,
                    objects=objects,
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
    connection: asyncpg.Connection, tables: dict
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


async def _copy_rows(root: Path, table: BackupTableV1):
    for row in _rows(root, table):
        yield (
            "\t".join(
                "\\N"
                if value is None
                else value.replace("\\", "\\\\")
                .replace("\t", "\\t")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                for value in row.values()
            )
            + "\n"
        ).encode("utf-8")


async def restore_backup(
    database_url: str, content_root: Path, bundle: Path, *, manifest_digest: str
) -> RecoveryReceiptV1:
    manifest = _verify_bundle(bundle, manifest_digest)
    if manifest.migration_digest != sha256_digest(_migrations()):
        raise RecoveryError("backup migrations do not match the installed release")
    connection = await _connect(database_url)
    try:
        if connection.get_server_version().major != manifest.postgres_major:
            raise RecoveryError("backup PostgreSQL major version is incompatible")
        if not await connection.fetchval(
            "SELECT to_regnamespace('fundamental') IS NOT NULL"
        ):
            store = PostgresMetadataStore(database_url, auto_migrate=True)
            try:
                await asyncio.to_thread(store.start)
            finally:
                await asyncio.to_thread(store.close)
        async with connection.transaction():
            tables, schema_digest = await _layout(connection)
            await _lock(connection, tables, restore=True)
            if (
                schema_digest != manifest.schema_digest
                or {table.name: table.columns for table in manifest.tables} != tables
            ):
                raise RecoveryError(
                    "backup schema or PostgreSQL major version is incompatible"
                )
            with tempfile.TemporaryDirectory(
                prefix="fundamental-restore-"
            ) as temporary:
                current = await _export_tables(connection, Path(temporary), tables)
            matches = current == manifest.tables
            if not matches:
                if any(
                    table.row_count
                    for table in current
                    if table.name not in {"schema_migrations", "schema_capabilities"}
                ):
                    raise RecoveryError(
                        "restore requires an empty or identical metadata store"
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
                    present = {
                        row[column]
                        for row in await connection.fetch(
                            f"SELECT {_identifier(column)} FROM fundamental.{_identifier(table)}"
                        )
                    }
                    if present != expected:
                        raise RecoveryError(
                            "restore target contains non-bootstrap schema records"
                        )
            expected_objects = {item.path: item for item in manifest.objects}
            for item in _content_inventory(content_root):
                if expected_objects.get(item.path) != item:
                    raise RecoveryError(
                        "target contains unrelated or conflicting content"
                    )
            wrote = not matches
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
                        shutil.copyfileobj(source, handle)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.link(temporary, target)
                    _sync_directory(target.parent)
                finally:
                    os.unlink(temporary)
                wrote = True
            if manifest.objects:
                _sync_directory(content_root)
                _sync_directory(content_root.parent)
            if not matches:
                names = ",".join(
                    f"fundamental.{_identifier(name)}" for name in sorted(tables)
                )
                await connection.execute(f"TRUNCATE {names} RESTART IDENTITY")
                for name in await _restore_order(connection, tables):
                    backup_table = next(
                        table for table in manifest.tables if table.name == name
                    )
                    await connection.copy_to_table(
                        name,
                        schema_name="fundamental",
                        columns=tables[name],
                        format="text",
                        source=_copy_rows(bundle, backup_table),
                    )
                await connection.execute(
                    "SELECT setval(pg_get_serial_sequence('fundamental.source_acquisition_audits','audit_id'), "
                    "GREATEST(COALESCE(MAX(audit_id),1),1), COUNT(*)>0) "
                    "FROM fundamental.source_acquisition_audits"
                )
                with tempfile.TemporaryDirectory(
                    prefix="fundamental-restore-check-"
                ) as temporary:
                    if (
                        await _export_tables(connection, Path(temporary), tables)
                        != manifest.tables
                    ):
                        raise RecoveryError(
                            "restored metadata failed digest verification"
                        )
            return _receipt(manifest, wrote=wrote)
    finally:
        await connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    export = subparsers.add_parser("export")
    export.add_argument("--destination", type=Path, required=True)
    export.add_argument("--source-revision", required=True)
    restore = subparsers.add_parser("restore")
    restore.add_argument("--bundle", type=Path, required=True)
    restore.add_argument("--manifest-digest", required=True)
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
                )
            )
        else:
            receipt = asyncio.run(
                restore_backup(
                    database_url,
                    content_root,
                    args.bundle,
                    manifest_digest=args.manifest_digest,
                )
            )
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
