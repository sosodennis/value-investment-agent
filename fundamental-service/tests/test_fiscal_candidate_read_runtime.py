from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from fundamental_service.fiscal_preparation_runtime import (
    build_fiscal_candidate_runtime,
)
from fundamental_service.metadata import (
    PostgresArtifactStore,
    PostgresContentStore,
    PostgresMetadataStore,
)
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import SnapshotError
import test_fiscal_candidate_preparation as candidate_cases

from test_fiscal_projection_builder import SyntheticRetainedSourcePort

environment = candidate_cases.environment
prepared_runtime = candidate_cases.prepared_runtime
deadline = candidate_cases.deadline


@contextmanager
def select_only_role(metadata, database_url):
    role = "issue495_reader_" + uuid4().hex
    password = uuid4().hex
    database = make_url(database_url).database

    async def create():
        async with metadata._runner._engine.begin() as connection:
            await connection.execute(
                text(f"CREATE ROLE \"{role}\" LOGIN NOINHERIT PASSWORD '{password}'")
            )
            await connection.execute(
                text(f'GRANT CONNECT ON DATABASE "{database}" TO "{role}"')
            )
            await connection.execute(
                text(f'GRANT USAGE ON SCHEMA fundamental TO "{role}"')
            )
            await connection.execute(
                text(f'GRANT SELECT ON ALL TABLES IN SCHEMA fundamental TO "{role}"')
            )

    async def remove():
        async with metadata._runner._engine.begin() as connection:
            await connection.execute(text(f'DROP OWNED BY "{role}"'))
            await connection.execute(text(f'DROP ROLE "{role}"'))

    metadata._runner.run(create())
    try:
        yield (
            make_url(database_url)
            .set(username=role, password=password)
            .render_as_string(hide_password=False)
        )
    finally:
        metadata._runner.run(remove())


def forbid(*args, **kwargs):
    raise AssertionError("read-only operation reached a publication or repair")


async def forbid_migration():
    raise AssertionError("read-only startup reached a migration")


def actual_reader_app(env, inputs, config, source_records, metadata, content_root):
    import fundamental_service.app as app_module

    content = PostgresContentStore(content_root, metadata, read_only=True)
    artifacts = PostgresArtifactStore(metadata, content, read_only=True)
    read_inputs = replace(
        inputs,
        artifacts=artifacts,
        sources=SyntheticRetainedSourcePort(source_records, artifacts),
    )
    reader = build_fiscal_candidate_runtime(read_inputs, metadata, config, write=False)
    app = app_module.create_app(
        metadata_store=metadata,
        artifact_store=artifacts,
        content_store=content,
        snapshot_repository=object(),
        fact_repository=object(),
        fiscal_sec_acquisition=object(),
    )
    return app, reader, artifacts


def test_actual_cli_read_lifecycle_and_nested_storage_succeed_with_select_only_role(
    prepared_runtime, tmp_path, monkeypatch
):
    import fundamental_service.app as app_module
    import fundamental_service.fiscal_source_runner as runner

    env, inputs, config, builder, command, sources = prepared_runtime
    first = builder.prepare(command, deadline_at=deadline())
    ref_file = tmp_path / "exact-ref.json"
    ref_file.write_bytes(canonical_bytes(first.reference))
    with select_only_role(env.metadata, env.database_url) as reader_url:
        metadata = PostgresMetadataStore(reader_url, auto_migrate=True)
        app, reader, artifacts = actual_reader_app(
            env, inputs, config, sources, metadata, tmp_path / "pg-content"
        )
        monkeypatch.setattr(metadata, "_apply_migration", forbid_migration)
        monkeypatch.setattr(metadata, "register_content", forbid)
        monkeypatch.setattr(metadata, "publish_model", forbid)
        monkeypatch.setattr(metadata, "publish_policy", forbid)
        monkeypatch.setattr(metadata, "publish_artifact", forbid)
        monkeypatch.setattr(app_module, "app", app)
        monkeypatch.setattr(
            runner,
            "configured_fiscal_candidate_runtime",
            lambda *args, **kwargs: reader,
        )
        try:
            result = asyncio.run(
                runner._run(
                    argparse.Namespace(
                        command="read-candidate",
                        source_revision=inputs.pin.declared_source_revision,
                        candidate_ref_file=ref_file,
                    ),
                    deadline_at=deadline(),
                )
            )
            assert canonical_bytes(result.evidence) == canonical_bytes(first.candidate)
            assert metadata.auto_migrate is True
            assert metadata._closed
            metadata_check = PostgresMetadataStore(reader_url)
            try:
                metadata_check.start_read_only()

                async def privileges(connection):
                    return tuple(
                        (
                            await connection.execute(
                                text(
                                    "SELECT has_table_privilege(current_user,'fundamental.content_objects','INSERT'), has_schema_privilege(current_user,'fundamental','CREATE'), has_database_privilege(current_user,current_database(),'CREATE')"
                                )
                            )
                        ).one()
                    )

                assert metadata_check.run_fiscal_admission_history(privileges) == (
                    False,
                    False,
                    False,
                )
                with pytest.raises(DBAPIError):
                    metadata_check.register_content(
                        "0" * 64, media_type="application/json", byte_length=0
                    )
            finally:
                metadata_check.close()
            assert not hasattr(reader.mapping_approvals, "approve")
            with pytest.raises(SnapshotError, match="publication capability"):
                artifacts.put_with_receipt("synthetic-refused-write", {})
        finally:
            metadata.close()


@pytest.mark.parametrize("missing", ["schema", "capability"])
def test_actual_cli_read_missing_prerequisite_refuses_and_closes_without_bootstrap(
    prepared_runtime, tmp_path, monkeypatch, missing
):
    import fundamental_service.app as app_module
    import fundamental_service.fiscal_source_runner as runner

    env, inputs, config, builder, command, sources = prepared_runtime
    first = builder.prepare(command, deadline_at=deadline())
    reference = tmp_path / "missing-prerequisite-ref.json"
    reference.write_bytes(canonical_bytes(first.reference))
    metadata = PostgresMetadataStore(env.database_url, auto_migrate=True)
    app, reader, _ = actual_reader_app(
        env, inputs, config, sources, metadata, tmp_path / "pg-content"
    )
    monkeypatch.setattr(metadata, "_apply_migration", forbid_migration)
    monkeypatch.setattr(metadata, "publish_model", forbid)
    monkeypatch.setattr(metadata, "publish_policy", forbid)
    monkeypatch.setattr(app_module, "app", app)
    monkeypatch.setattr(
        runner, "configured_fiscal_candidate_runtime", lambda *args, **kwargs: reader
    )
    if missing == "schema":

        async def unavailable():
            return -1

        monkeypatch.setattr(metadata, "_schema_version", unavailable)
    else:

        async def remove(connection):
            await connection.execute(
                text(
                    "DELETE FROM fundamental.schema_capabilities WHERE capability_id='fiscal-admission-history-v1'"
                )
            )

        env.metadata.run_fiscal_admission_history(remove)
    with pytest.raises(SnapshotError) as failure:
        asyncio.run(
            runner._run(
                argparse.Namespace(
                    command="read-candidate",
                    source_revision=inputs.pin.declared_source_revision,
                    candidate_ref_file=reference,
                ),
                deadline_at=deadline(),
            )
        )
    assert failure.value.code in {
        "METADATA_SCHEMA_UNAVAILABLE",
        "FISCAL_ADMISSION_HISTORY_UNAVAILABLE",
    }
    assert metadata._closed


@pytest.mark.parametrize("retained", [False, True])
@pytest.mark.parametrize("journal", [False, True])
def test_read_only_missing_content_registration_refuses_without_repair(
    prepared_runtime, monkeypatch, retained, journal
):
    env, _, _, _, _, _ = prepared_runtime
    published = env.store.put_with_receipt(
        "synthetic-missing-registration", {"synthetic": "unregistered"}
    )
    record = published.artifact

    async def remove(connection):
        await connection.execute(
            text(
                "DELETE FROM fundamental.content_objects WHERE content_hash=:digest AND media_type=:media"
            ),
            {"digest": record.content_hash, "media": record.media_type},
        )

    env.metadata.run_fiscal_admission_history(remove)
    reader = env.store.as_read_only()
    monkeypatch.setattr(env.metadata, "register_content", forbid)
    check_journal = env.metadata.check_retained_artifact_journal

    def no_repair(stream, *, repair=None):
        assert repair is None
        return check_journal(stream)

    monkeypatch.setattr(env.metadata, "check_retained_artifact_journal", no_repair)
    with pytest.raises(SnapshotError) as failure:
        if retained:
            with reader.retained_read_operation(
                (record.artifact_id,), max_entries=0 if journal else 512
            ) as operation:
                operation.read(record.artifact_id)
        else:
            reader.read(record.artifact_id)
    assert failure.value.code == "CONTENT_REGISTRATION_UNAVAILABLE"
    assert not env.metadata.has_content_hash(
        record.content_hash, media_type=record.media_type
    )


def test_normal_app_lifespan_keeps_catalog_publication(environment):
    import fundamental_service.app as app_module

    env = environment
    calls = {"models": 0, "policies": 0}
    publish_model, publish_policy = (
        env.metadata.publish_model,
        env.metadata.publish_policy,
    )

    def model(*args, **kwargs):
        calls["models"] += 1
        return publish_model(*args, **kwargs)

    def policy(*args, **kwargs):
        calls["policies"] += 1
        return publish_policy(*args, **kwargs)

    env.metadata.publish_model = model
    env.metadata.publish_policy = policy
    app = app_module.create_app(
        metadata_store=env.metadata,
        artifact_store=env.store,
        snapshot_repository=object(),
        fact_repository=object(),
        content_store=env.store._content,
    )

    async def run():
        async with app.router.lifespan_context(app):
            assert env.metadata.ready

    asyncio.run(run())
    assert calls["models"] > 0 and calls["policies"] > 0


def test_candidate_missing_registration_refuses_and_never_heals(
    prepared_runtime, monkeypatch
):
    env, inputs, config, builder, command, _ = prepared_runtime
    first = builder.prepare(command, deadline_at=deadline())

    async def remove(connection):
        await connection.execute(
            text(
                "DELETE FROM fundamental.content_objects WHERE content_hash=:digest AND media_type=:media"
            ),
            {
                "digest": first.reference.content_hash,
                "media": first.reference.media_type,
            },
        )

    env.metadata.run_fiscal_admission_history(remove)
    monkeypatch.setattr(env.metadata, "register_content", forbid)
    reader = build_fiscal_candidate_runtime(inputs, env.metadata, config, write=False)
    with pytest.raises(SnapshotError) as failure:
        reader.verify_candidate(first.reference, deadline_at=deadline())
    assert failure.value.code == "CONTENT_REGISTRATION_UNAVAILABLE"
    assert not env.metadata.has_content_hash(
        first.reference.content_hash, media_type=first.reference.media_type
    )


def test_actual_runtime_import_never_creates_content_root(tmp_path):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path
    import fundamental_service.metadata as metadata_module

    root = tmp_path / "never-created-service-root"
    source = Path(metadata_module.__file__).resolve().parents[1]
    repository = Path(__file__).resolve().parents[2]
    environment = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": str(source) + os.pathsep + str(repository / "finance-agent-core"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "FUNDAMENTAL_SERVICE_DATA_ROOT": str(root),
        "FUNDAMENTAL_SERVICE_DATABASE_URL": "postgresql+asyncpg://synthetic:synthetic@127.0.0.1:1/synthetic",
    }
    script = """
import json,os
from pathlib import Path
root=Path(os.environ['FUNDAMENTAL_SERVICE_DATA_ROOT'])
before=root.exists()
from fundamental_service.app import app
metadata=app.state.metadata_store
result={'before':before,'after':root.exists(),'content_root':(root/'content').exists(),'metadata_started':metadata.ready}
app.state.valuation_diagnostic_sink.close()
metadata.close()
print(json.dumps(result))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "before": False,
        "after": False,
        "content_root": False,
        "metadata_started": False,
    }
    assert not root.exists()


@pytest.mark.parametrize("materialized", [False, True])
def test_readonly_filesystem_disappearing_after_view_never_recreates_root(
    environment, tmp_path, materialized
):
    import shutil

    env = environment
    root = tmp_path / "synthetic-lazy-content"
    content = PostgresContentStore(root, env.metadata)
    assert not root.exists()
    with pytest.raises(SnapshotError):
        content.as_read_only()
    assert not root.exists()
    store = PostgresArtifactStore(env.metadata, content)
    publication = store.put_with_receipt(
        "synthetic-lazy-content-artifact", {"synthetic": "lazy writer"}
    )
    assert root.is_dir()
    reader = store.as_read_only()
    if materialized:
        assert reader.read(publication.artifact.artifact_id) == canonical_bytes(
            {"synthetic": "lazy writer"}
        )
    shutil.rmtree(root)
    with pytest.raises(SnapshotError) as failure:
        reader.read(publication.artifact.artifact_id)
    assert failure.value.code == "SOURCE_BYTES_UNAVAILABLE"
    assert not root.exists()
    with pytest.raises(SnapshotError):
        with reader.retained_read_operation(
            (publication.artifact.artifact_id,)
        ) as retained:
            retained.read(publication.artifact.artifact_id)
    assert not root.exists()
