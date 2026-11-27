from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fundamental_service.data_releases import (
    DataReleaseActivationCommandV1,
    DataReleaseTrustRootsV1,
    DataReleaseVerifierV1,
)
from fundamental_service.fiscal_admission_history import (
    PostgresFiscalAdmissionHistory,
    ReadOnlyFiscalAdmissionHistory,
)
from fundamental_service.fiscal_display_runtime import build_fiscal_display_reader
from fundamental_service.fiscal_release_contracts import FiscalPublishV2
from fundamental_service.fiscal_releases import (
    FiscalReleaseReader,
    FiscalReleaseService,
    FiscalReleaseSigningJob,
)
from fundamental_service.fiscal_read_contracts import FiscalReadRequestV2
from fundamental_service.fiscal_authority_contracts import (
    FiscalRevokeAuthorityCommandV1,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
import test_fiscal_display_admission as display_cases

from test_fiscal_admission_authority import public_key
from test_fiscal_projection_builder import assert_frozen_candidate_projection


environment = display_cases.environment
protected_deployment_root = display_cases.protected_deployment_root
display = display_cases.display


def deadline():
    return datetime.now(UTC) + timedelta(seconds=60)


@pytest.fixture
def release(display):
    import os

    current = display.runtime.apply(display.order.order_id, deadline_at=deadline())
    key = Ed25519PrivateKey.generate()
    roots = DataReleaseTrustRootsV1(
        verifiers={
            "ephemeral-fiscal": DataReleaseVerifierV1(
                workflow_identity="ephemeral-fiscal-workflow",
                public_key_ed25519_base64=public_key(key),
                verification_suite_digest="a" * 64,
            )
        },
        mapping_reviewers={"ephemeral-mapping": public_key(key)},
    )
    display.env.metadata._data_release_trust_roots = roots
    readonly = display.env.store.as_read_only()
    history = PostgresFiscalAdmissionHistory(display.env.metadata)
    display_reader = build_fiscal_display_reader(
        candidates=display.runtime.candidates,
        deployment_file=display.runtime.installation.deployment_file,
        deployment_uid=os.getuid(),
        mapping_trust_roots_file=display.candidate_config.mapping_trust_roots_file,
        artifacts=readonly,
        metadata=display.env.metadata,
    )

    def configuration():
        return sha256_digest(
            (
                display.runtime.configuration(),
                hashlib.sha256(
                    display.runtime.installation.mapping_trust_roots_file.read_bytes()
                ).hexdigest(),
            )
        )

    args = dict(
        display=display_reader,
        artifacts=readonly,
        history=ReadOnlyFiscalAdmissionHistory(history),
        publications=display.env.metadata,
        trust_roots=lambda: roots,
        configuration_digest=configuration,
        read_operation=readonly.scoped_read_operation,
        seal_read_operation=readonly.seal_scoped_read_operation,
    )
    reader = FiscalReleaseReader(**args)
    canary = FiscalReleaseReader(**args)
    job = FiscalReleaseSigningJob(
        "ephemeral-fiscal",
        "ephemeral-fiscal-workflow",
        "a" * 64,
        "b" * 40,
        "ephemeral-run-one",
        lambda approved, deadline_at: key,
    )
    service = FiscalReleaseService(
        reader=reader,
        canary=canary,
        artifacts=display.env.store,
        history=history,
        publications=display.env.metadata,
        signing=job,
    )
    return display, current, service, reader


def synthetic_workflow_canary_configuration(path, reader, monkeypatch):
    from contextlib import contextmanager
    from fundamental_service import fiscal_release_runtime

    path.write_bytes(
        canonical_bytes({"kind": "synthetic-full-replay-composition-test"})
    )
    path.chmod(0o600)

    @contextmanager
    def compose(selectors, *, deadline_at):
        assert selectors.configuration_file == path
        assert not hasattr(selectors, "private_key_file")
        assert not hasattr(selectors, "signing")
        assert datetime.now(UTC) < deadline_at
        yield reader

    monkeypatch.setattr(fiscal_release_runtime, "_readonly_canary_reader", compose)
    return path


def test_registry_candidate_display_release_canary_activate_both_frequencies_and_revoke(
    release,
    tmp_path,
):
    display, current, service, reader = release
    timings = []

    def operation(name, action):
        limit = deadline()
        started = time.monotonic()
        value = action(limit)
        timings.append(
            dict(
                operation=name,
                absolute_deadline=limit.isoformat(),
                elapsed_seconds=time.monotonic() - started,
            )
        )
        return value

    approved = FiscalPublishV2(
        candidate_ref=current.candidate.reference, decision_ref=current.reference
    )
    receipt = operation(
        "publish", lambda limit: service.publish(approved, deadline_at=limit)
    )
    assert receipt.wrote
    command = DataReleaseActivationCommandV1(
        profile_id=receipt.profile_id,
        manifest_digest=receipt.manifest_digest,
        expected_revision=0,
        expected_manifest_digest=None,
        operation="activate",
        command_id="fiscal-activation-one",
        actor_id="ephemeral-operator",
        organization_id="ephemeral-org",
        correlation_id="ephemeral-correlation",
        reason="transparent retained Apple slice",
    )
    active = operation(
        "activate", lambda limit: service.activate(command, deadline_at=limit)
    )
    assert active.revision == 1
    manifest = display.env.metadata.get_data_release_manifest(receipt.manifest_digest)
    results = []
    for frequency in ("quarter", "ttm"):
        result = operation(
            "read-" + frequency,
            lambda limit: reader.read(
                FiscalReadRequestV2(
                    manifest_digest=receipt.manifest_digest,
                    scope=manifest.scope,
                    cutoff_at=manifest.cutoff_at,
                    frequency=frequency,
                ),
                deadline_at=limit,
            ),
        )
        assert result.binding.columns.frequency == frequency
        assert len(result.rows) == 25
        results.append(result)
    assert sum(len(row.cells) for result in results for row in result.rows) == 325
    assert_frozen_candidate_projection(current.candidate, "aapl-historical")
    originals = {node.node_id: node for node in current.candidate.projection.nodes}
    for result in results:
        for row in result.rows:
            for cell in row.cells:
                source = originals[cell.node_id]
                if cell.kind in {"reported", "derived"}:
                    assert cell.decimal == format(source.value, "f")
                else:
                    assert cell.reason_code == source.reason_code
    authority = display.runtime.history.read(
        ("control:fiscal-authority:" + display.order.request.authority_id,),
        deadline_at=deadline(),
    )
    grant = current.decision.body.review.execution.grant_ref
    revoke = display.registry_order.model_copy(
        update={
            "order_id": "release-display-revoke",
            "command": FiscalRevokeAuthorityCommandV1(
                command_id="release-display-revoke",
                authority_id=display.order.request.authority_id,
                grant_ref=grant,
                reason="test release current refusal",
            ),
            "expected_head": authority.heads[0],
        }
    )
    path = (
        display.registry._installation.orders_directory / "release-display-revoke.json"
    )
    path.write_bytes(canonical_bytes(revoke))
    display.registry.apply(revoke.order_id, deadline_at=deadline())
    with pytest.raises(SnapshotError):
        reader.read(
            FiscalReadRequestV2(
                manifest_digest=receipt.manifest_digest,
                scope=manifest.scope,
                cutoff_at=manifest.cutoff_at,
                frequency="quarter",
            ),
            deadline_at=deadline(),
        )
    target = tmp_path / ("positive-timings-" + receipt.manifest_digest + ".json")
    target.write_text(
        json.dumps(
            dict(
                adapter="synthetic retained adapter over original Apple captures; not formal SEC commissioning",
                operations=timings,
                cells=325,
                manifest_digest=receipt.manifest_digest,
            ),
            indent=2,
        )
        + "\n"
    )


@pytest.fixture
def published(release):
    display, current, service, reader = release
    receipt = service.publish(
        FiscalPublishV2(
            candidate_ref=current.candidate.reference, decision_ref=current.reference
        ),
        deadline_at=deadline(),
    )
    return display, current, service, reader, receipt


def activation(receipt, command_id="fiscal-activate"):
    return DataReleaseActivationCommandV1(
        profile_id=receipt.profile_id,
        manifest_digest=receipt.manifest_digest,
        expected_revision=0,
        expected_manifest_digest=None,
        operation="activate",
        command_id=command_id,
        actor_id="ephemeral-actor",
        organization_id="ephemeral-org",
        correlation_id="ephemeral-correlation",
        reason="ephemeral behavior verification",
    )


def test_closed_codec_preserves_legacy_bytes_and_rejects_unknown_or_cross_pair():
    from fundamental_service.publication_codec import (
        decode_release_manifest,
        decode_release_verification,
    )
    from fundamental_service.data_releases import DataReleaseError
    from test_data_release_attestations import _manifest

    legacy = _manifest()
    assert canonical_bytes(
        decode_release_manifest(canonical_bytes(legacy))
    ) == canonical_bytes(legacy)
    for tag in (None, "unknown", "fundamental.fiscal-release-manifest.v999"):
        with pytest.raises(DataReleaseError):
            decode_release_manifest({**legacy.model_dump(mode="json"), "protocol": tag})
    with pytest.raises(DataReleaseError):
        decode_release_verification({"protocol": "unknown"})


def test_retry_canary_tamper_and_purpose_scope_boundaries(published, monkeypatch):
    from fundamental_service.publication_codec import require_publication_pair
    from fundamental_service.data_releases import DataReleaseError

    display, current, service, reader, receipt = published
    pair = display.env.metadata.get_data_release_verification(receipt.manifest_digest)
    manifest = display.env.metadata.get_data_release_manifest(receipt.manifest_digest)
    again = service.publish(
        FiscalPublishV2(
            candidate_ref=current.candidate.reference, decision_ref=current.reference
        ),
        deadline_at=deadline(),
    )
    assert not again.wrote
    assert again.manifest_digest == receipt.manifest_digest
    assert canonical_bytes(
        display.env.metadata.get_data_release_verification(receipt.manifest_digest)
    ) == canonical_bytes(pair)
    from test_data_release_attestations import _manifest

    with pytest.raises(DataReleaseError):
        require_publication_pair(_manifest(), pair)
    with pytest.raises(DataReleaseError, match="observation"):
        display.env.metadata.publish_data_release_candidate(manifest, pair)
    with pytest.raises(DataReleaseError, match="observation"):
        display.env.metadata.compare_and_swap_data_release(activation(receipt))
    with pytest.raises(DataReleaseError, match="signature"):
        from fundamental_service.publication_codec import verify_fiscal_signature

        verify_fiscal_signature(
            pair.signed.model_copy(update={"signature": "0" * 128}),
            reader.trust_roots(),
        )
    with pytest.raises(SnapshotError):
        reader.read(
            FiscalReadRequestV2(
                manifest_digest=receipt.manifest_digest,
                scope=manifest.scope.model_copy(update={"security_id": "MSFT"}),
                cutoff_at=manifest.cutoff_at,
                frequency="quarter",
            ),
            deadline_at=deadline(),
        )
    changed = pair.model_copy(
        update={
            "canary_ref": pair.canary_ref.model_copy(update={"content_hash": "f" * 64})
        }
    )
    original = display.env.metadata.get_data_release_verification
    monkeypatch.setattr(
        display.env.metadata, "get_data_release_verification", lambda digest: changed
    )
    with pytest.raises(DataReleaseError, match="exact valid retained"):
        reader.pinned(receipt.manifest_digest, deadline_at=deadline())
    monkeypatch.setattr(display.env.metadata, "get_data_release_verification", original)
    new_configuration = ["generation-one"]
    reader.configuration_digest = lambda: new_configuration[0]
    with pytest.raises(SnapshotError, match="configuration"):
        with reader._open_pinned(receipt.manifest_digest, deadline_at=deadline()):
            new_configuration[0] = "generation-two"


def test_authenticated_http_typed_dag_and_conditional_read(published):
    from fastapi.testclient import TestClient
    from fundamental_service.app import create_app
    from fundamental_service.operations import OperationsConfig
    from fundamental_service.testsupport import (
        TEST_SERVICE_TOKEN,
        auth_headers,
        make_internal_envelope,
    )
    from fundamental_service.fiscal_read_contracts import FiscalReadResultV2

    display, _, _, reader, receipt = published
    manifest = display.env.metadata.get_data_release_manifest(receipt.manifest_digest)
    app = create_app(
        artifact_store=display.env.store,
        content_store=display.inputs.content,
        metadata_store=display.env.metadata,
        config=OperationsConfig(service_token=TEST_SERVICE_TOKEN),
        fiscal_reader_factory=lambda: reader,
    )
    client = TestClient(app)
    payload = FiscalReadRequestV2(
        manifest_digest=receipt.manifest_digest,
        scope=manifest.scope,
        cutoff_at=manifest.cutoff_at,
        frequency="ttm",
    ).model_dump(mode="json")
    response = client.request(
        "GET",
        "/v1/data/fiscal-statements",
        headers=auth_headers() | {"If-None-Match": "*"},
        json=make_internal_envelope(payload),
    )
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    result = FiscalReadResultV2.model_validate_json(
        canonical_bytes(response.json()["result"])
    )
    assert len(result.rows) == 25
    assert sum(len(row.cells) for row in result.rows) == 125
    assert any(cell.kind == "derived" for row in result.rows for cell in row.cells)
    assert any(cell.kind == "unavailable" for row in result.rows for cell in row.cells)
    observed_ids = {item.observation_id for item in result.evidence.observations}
    assert all(
        item.observation_id in observed_ids
        for node in result.evidence.nodes
        for item in node.candidates
    )
    original_nodes = {
        node.node_id: node for node in published[1].candidate.projection.nodes
    }
    assert all(
        node.candidates == original_nodes[node.node_id].candidates
        for node in result.evidence.nodes
    )
    assert any(
        item.outcome != "selected"
        for node in result.evidence.nodes
        for item in node.candidates
    )
    assert all(node.formula != "caller-computed" for node in result.evidence.nodes)
    assert (
        client.request(
            "GET", "/v1/data/fiscal-statements", json=make_internal_envelope(payload)
        ).status_code
        == 401
    )
    wrong = payload | {"scope": payload["scope"] | {"issuer_id": "wrong"}}
    refused = client.request(
        "GET",
        "/v1/data/fiscal-statements",
        headers=auth_headers(),
        json=make_internal_envelope(wrong),
    )
    assert refused.status_code != 200 and "result" not in refused.json()
    schema = app.openapi()
    assert schema["paths"]["/v1/data/fiscal-statements"]["get"]["requestBody"][
        "content"
    ]["application/json"]["schema"]["$ref"].endswith(
        "FundamentalFiscalStatementsRequestEnvelopeV1"
    )


def test_authenticated_fiscal_activation_and_rollback_use_worker_and_current_scope(
    published, monkeypatch, tmp_path
):
    import asyncio
    from threading import get_ident

    import httpx

    from fundamental_service.app import create_app
    from fundamental_service.operations import OperationsConfig
    from fundamental_service.testsupport import (
        TEST_SERVICE_TOKEN,
        auth_headers,
        make_internal_envelope,
    )

    display, _, _, reader, receipt = published
    owner_threads = []
    observations = []
    original = reader.activate

    def traced(*args, **kwargs):
        owner_threads.append(get_ident())
        return original(*args, **kwargs)

    monkeypatch.setattr(reader, "activate", traced)
    app = create_app(
        artifact_store=display.env.store,
        content_store=display.inputs.content,
        metadata_store=display.env.metadata,
        config=OperationsConfig(
            service_token=TEST_SERVICE_TOKEN,
            release_activation_authorized_organizations=frozenset(
                {"organization-test"}
            ),
        ),
        fiscal_reader_factory=lambda: reader,
    )
    assert app.state.operations_config.max_request_ms == 5000

    async def run():
        loop_thread = get_ident()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:

            async def change(
                operation, revision, command_id, *, headers=None, target_client=client
            ):
                started = time.monotonic()
                response = await target_client.post(
                    "/v1/data/releases/" + receipt.profile_id + "/" + operation,
                    headers=auth_headers() if headers is None else headers,
                    json=make_internal_envelope(
                        dict(
                            manifest_digest=receipt.manifest_digest,
                            expected_revision=revision,
                            expected_manifest_digest=(
                                receipt.manifest_digest if revision else None
                            ),
                            operation=operation,
                            command_id=command_id,
                            reason="retained owner HTTP boundary verification",
                        )
                    ),
                )
                observations.append(
                    dict(
                        operation=operation,
                        command_id=command_id,
                        status_code=response.status_code,
                        elapsed_seconds=time.monotonic() - started,
                        response=response.json(),
                    )
                )
                return response

            denied = await change("activate", 0, "http-unauthenticated", headers={})
            assert denied.status_code == 401
            assert not owner_threads
            active = await change("activate", 0, "http-fiscal-activate")
            assert active.status_code == 200, active.text
            assert active.json()["result"]["active"]["revision"] == 1
            rollback = await change("rollback", 1, "http-fiscal-rollback")
            assert rollback.status_code == 200, rollback.text
            assert rollback.json()["result"]["active"]["revision"] == 2
            assert owner_threads and all(
                thread != loop_thread for thread in owner_threads
            ), "actual fiscal owner executed on server event loop"

            unavailable_app = create_app(
                artifact_store=display.env.store,
                content_store=display.inputs.content,
                metadata_store=display.env.metadata,
                config=app.state.operations_config,
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=unavailable_app),
                base_url="http://test",
            ) as unavailable_client:
                unavailable = await change(
                    "activate",
                    2,
                    "http-missing-reader",
                    target_client=unavailable_client,
                )
            assert unavailable.status_code == 503
            assert unavailable.json()["error"]["code"] == "FISCAL_READING_UNAVAILABLE"

            clock = reader.clock
            monkeypatch.setattr(
                reader, "clock", lambda: datetime.now(UTC) + timedelta(seconds=6)
            )
            expired = await change("activate", 2, "http-fiscal-deadline")
            monkeypatch.setattr(reader, "clock", clock)
            assert expired.status_code == 503
            assert expired.json()["error"]["code"] == "REQUEST_DEADLINE_EXCEEDED"
            assert expired.json()["error"]["retryable"]

            authority = display.runtime.history.read(
                ("control:fiscal-authority:" + display.order.request.authority_id,),
                deadline_at=deadline(),
            )
            grant = published[1].decision.body.review.execution.grant_ref
            revoke = display.registry_order.model_copy(
                update={
                    "order_id": "http-release-display-revoke",
                    "command": FiscalRevokeAuthorityCommandV1(
                        command_id="http-release-display-revoke",
                        authority_id=display.order.request.authority_id,
                        grant_ref=grant,
                        reason="test authenticated activation current refusal",
                    ),
                    "expected_head": authority.heads[0],
                }
            )
            path = display.registry._installation.orders_directory / (
                revoke.order_id + ".json"
            )
            path.write_bytes(canonical_bytes(revoke))
            display.registry.apply(revoke.order_id, deadline_at=deadline())
            refused = await change("rollback", 2, "http-fiscal-revoked")
            assert refused.status_code != 200 and "result" not in refused.json()
            pointer = display.env.metadata.get_active_data_release(receipt.profile_id)
            assert pointer.revision == 2
            assert pointer.manifest_digest == receipt.manifest_digest
        (
            tmp_path / ("http-activation-" + receipt.manifest_digest + ".json")
        ).write_text(
            json.dumps(
                dict(
                    loop_thread=loop_thread,
                    owner_threads=owner_threads,
                    max_request_ms=app.state.operations_config.max_request_ms,
                    observations=observations,
                ),
                indent=2,
            )
            + "\n"
        )

    asyncio.run(run())


def test_same_transaction_activation_blocks_metadata_writer_then_current_refuses(
    published, monkeypatch
):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from threading import Event
    import asyncpg
    from fundamental_service.fiscal_admission_history import (
        PostgresFiscalAdmissionHistory,
    )
    from fundamental_service.data_releases import DataReleaseError

    display, _, _, reader, receipt = published
    with reader._open_pinned(
        receipt.manifest_digest, deadline_at=deadline()
    ) as operation:
        observation = operation.observation
        snapshot = operation._complete()
    locked, release_lock, writer_started = Event(), Event(), Event()
    original = PostgresFiscalAdmissionHistory.validate_activation

    async def pause(self, observed, connection):
        result = await original(self, observed, connection)
        locked.set()
        assert await asyncio.to_thread(release_lock.wait, 10)
        return result

    monkeypatch.setattr(PostgresFiscalAdmissionHistory, "validate_activation", pause)
    source = observation.display.candidate.content.source_uses[
        -1
    ].scope.source_validation_ref.artifact_id

    async def invalidate():
        connection = await asyncpg.connect(
            display.env.database_url.replace("postgresql+asyncpg://", "postgresql://")
        )
        try:
            writer_started.set()
            await connection.execute(
                "UPDATE fundamental.artifact_references SET status='invalidated' WHERE artifact_id=$1",
                source,
            )
        finally:
            await connection.close()

    command = activation(receipt)
    with ThreadPoolExecutor(max_workers=2) as pool:
        cas = pool.submit(
            display.env.metadata.compare_and_swap_data_release,
            command,
            fiscal_observation=snapshot,
        )
        assert locked.wait(10)
        writer = pool.submit(asyncio.run, invalidate())
        try:
            assert writer_started.wait(5)
            with pytest.raises(TimeoutError):
                writer.result(timeout=0.2)
        finally:
            release_lock.set()
        active = cas.result(timeout=15)
        writer.result(timeout=15)
    assert active.revision == 1
    with pytest.raises(SnapshotError):
        reader.pinned(receipt.manifest_digest, deadline_at=deadline())
    monkeypatch.setattr(PostgresFiscalAdmissionHistory, "validate_activation", original)
    replay = display.env.metadata.compare_and_swap_data_release(command)
    assert replay == active
    with pytest.raises(DataReleaseError):
        display.env.metadata.compare_and_swap_data_release(
            command.model_copy(update={"reason": "changed"})
        )
    with pytest.raises(SnapshotError):
        display.env.metadata.compare_and_swap_data_release(
            activation(receipt, "stale-after-metadata"), fiscal_observation=snapshot
        )


def test_pointer_wait_crosses_expiry_without_activation(published):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace
    from threading import Event
    import asyncpg

    display, _, _, reader, receipt = published
    command = activation(receipt)

    async def initialize_and_lock(locked, unlock):
        connection = await asyncpg.connect(
            display.env.database_url.replace("postgresql+asyncpg://", "postgresql://")
        )
        try:
            await connection.execute(
                "INSERT INTO fundamental.active_data_release_pointers(profile_id,manifest_digest,revision,activated_at) VALUES($1,NULL,0,NULL)",
                receipt.profile_id,
            )
            async with connection.transaction():
                await connection.fetchrow(
                    "SELECT * FROM fundamental.active_data_release_pointers WHERE profile_id=$1 FOR UPDATE",
                    receipt.profile_id,
                )
                locked.set()
                assert await asyncio.to_thread(unlock.wait, 10)
        finally:
            await connection.close()

    with reader._open_pinned(
        receipt.manifest_digest, deadline_at=deadline()
    ) as operation:
        snapshot = operation._complete()
    locked, unlock = Event(), Event()
    with ThreadPoolExecutor(max_workers=2) as pool:
        holder = pool.submit(asyncio.run, initialize_and_lock(locked, unlock))
        assert locked.wait(5)
        short = replace(snapshot, expires_at=datetime.now(UTC) + timedelta(seconds=0.4))
        cas = pool.submit(
            display.env.metadata.compare_and_swap_data_release,
            command,
            fiscal_observation=short,
        )
        try:
            assert not unlock.wait(0.7)
        finally:
            unlock.set()
        holder.result(timeout=10)
        with pytest.raises(SnapshotError, match="expired"):
            cas.result(timeout=10)
    assert display.env.metadata.get_active_data_release(receipt.profile_id) is None


def test_select_only_fiscal_current_without_signing_keys(
    published, tmp_path, monkeypatch
):
    import os
    from dataclasses import replace
    from fundamental_service.metadata import (
        PostgresMetadataStore,
        PostgresArtifactStore,
        PostgresContentStore,
    )
    from fundamental_service.fiscal_preparation_runtime import (
        build_fiscal_candidate_runtime,
    )
    from test_fiscal_candidate_read_runtime import select_only_role
    from test_fiscal_projection_builder import SyntheticRetainedSourcePort

    display, _, _, reader, receipt = published
    roots = reader.trust_roots()
    for key in (
        display.runtime.installation.private_key_file,
        display.candidate_config.candidate_private_key_file,
        display.candidate_config.mapping_private_key_file,
        display.registry._installation.private_key_file,
    ):
        key.unlink()
    manifest = display.env.metadata.get_data_release_manifest(receipt.manifest_digest)
    with select_only_role(display.env.metadata, display.env.database_url) as reader_url:
        metadata = PostgresMetadataStore(
            reader_url, auto_migrate=False, data_release_trust_roots=roots
        )
        metadata.start_read_only()
        try:

            def forbidden(*args, **kwargs):
                raise AssertionError(
                    "SELECT-only fiscal read attempted a write or repair"
                )

            monkeypatch.setattr(metadata, "register_content", forbidden)
            monkeypatch.setattr(metadata, "publish_artifact", forbidden)
            monkeypatch.setattr(metadata, "_apply_migration", forbidden)
            store = PostgresArtifactStore(
                metadata,
                PostgresContentStore(tmp_path / "pg-content", metadata, read_only=True),
                read_only=True,
            )
            inputs = replace(
                display.inputs,
                artifacts=store,
                sources=SyntheticRetainedSourcePort(
                    display.inputs.sources.evidence, store
                ),
            )
            candidates = build_fiscal_candidate_runtime(
                inputs,
                metadata,
                display.candidate_config.model_copy(
                    update={
                        "candidate_private_key_file": None,
                        "mapping_private_key_file": None,
                    }
                ),
                write=False,
            )
            display_reader = build_fiscal_display_reader(
                candidates=candidates,
                deployment_file=display.runtime.installation.deployment_file,
                deployment_uid=os.getuid(),
                mapping_trust_roots_file=display.candidate_config.mapping_trust_roots_file,
                artifacts=store,
                metadata=metadata,
            )
            readonly = FiscalReleaseReader(
                display=display_reader,
                artifacts=store,
                history=ReadOnlyFiscalAdmissionHistory(
                    PostgresFiscalAdmissionHistory(metadata)
                ),
                publications=metadata,
                trust_roots=lambda: roots,
                configuration_digest=reader.configuration_digest,
                read_operation=store.scoped_read_operation,
                seal_read_operation=store.seal_scoped_read_operation,
            )
            result = readonly.read(
                FiscalReadRequestV2(
                    manifest_digest=receipt.manifest_digest,
                    scope=manifest.scope,
                    cutoff_at=manifest.cutoff_at,
                    frequency="quarter",
                ),
                deadline_at=deadline(),
            )
            assert len(result.rows) == 25
            assert not hasattr(readonly.history, "checkpoint")
        finally:
            metadata.close()


def test_actual_backup_restore_retains_pair_and_refuses_old_epoch(published, tmp_path):
    import asyncio
    import os
    from dataclasses import replace
    from fundamental_service.metadata import (
        PostgresMetadataStore,
        PostgresArtifactStore,
        PostgresContentStore,
    )
    from fundamental_service.persistence_recovery import (
        export_backup,
        restore_backup,
        PersistenceBackupV2,
        RecoveryError,
    )
    from fundamental_service.fiscal_preparation_runtime import (
        build_fiscal_candidate_runtime,
    )
    from test_fiscal_admission_history import _temporary_database
    from test_fiscal_history_recovery import target_pin
    from test_fiscal_projection_builder import SyntheticRetainedSourcePort

    display, _, service, reader, receipt = published
    roots = reader.trust_roots()
    active = service.activate(activation(receipt), deadline_at=deadline())
    with pytest.raises(RecoveryError, match="verification"):
        asyncio.run(
            export_backup(
                display.env.database_url,
                tmp_path / "pg-content",
                tmp_path / "untrusted-backups",
                source_revision="b" * 40,
            )
        )
    backup = asyncio.run(
        export_backup(
            display.env.database_url,
            tmp_path / "pg-content",
            tmp_path / "backups",
            source_revision="b" * 40,
            release_trust_roots=roots,
        )
    )
    bundle = tmp_path / "backups" / backup.manifest_digest
    manifest = PersistenceBackupV2.model_validate_json(
        (bundle / "manifest.json").read_bytes()
    )
    original_pair = canonical_bytes(
        display.env.metadata.get_data_release_verification(receipt.manifest_digest)
    )
    with _temporary_database(os.environ["FUNDAMENTAL_TEST_DATABASE_URL"]) as target:
        with target_pin(target, manifest, tmp_path / "restore-pin.json") as pin:
            asyncio.run(
                restore_backup(
                    target,
                    tmp_path / "restored-content",
                    bundle,
                    manifest_digest=backup.manifest_digest,
                    authorization_path=pin,
                    release_trust_roots=roots,
                )
            )
        metadata = PostgresMetadataStore(
            target, auto_migrate=False, data_release_trust_roots=roots
        )
        try:
            metadata.start_read_only()
            assert (
                canonical_bytes(
                    metadata.get_data_release_verification(receipt.manifest_digest)
                )
                == original_pair
            )
            assert metadata.get_active_data_release(receipt.profile_id) == active
            store = PostgresArtifactStore(
                metadata,
                PostgresContentStore(
                    tmp_path / "restored-content", metadata, read_only=True
                ),
                read_only=True,
            )
            inputs = replace(
                display.inputs,
                artifacts=store,
                sources=SyntheticRetainedSourcePort(
                    display.inputs.sources.evidence, store
                ),
            )
            candidates = build_fiscal_candidate_runtime(
                inputs,
                metadata,
                display.candidate_config.model_copy(
                    update={
                        "candidate_private_key_file": None,
                        "mapping_private_key_file": None,
                    }
                ),
                write=False,
            )
            display_reader = build_fiscal_display_reader(
                candidates=candidates,
                deployment_file=display.runtime.installation.deployment_file,
                deployment_uid=os.getuid(),
                mapping_trust_roots_file=display.candidate_config.mapping_trust_roots_file,
                artifacts=store,
                metadata=metadata,
            )
            restored = FiscalReleaseReader(
                display=display_reader,
                artifacts=store,
                history=ReadOnlyFiscalAdmissionHistory(
                    PostgresFiscalAdmissionHistory(metadata)
                ),
                publications=metadata,
                trust_roots=lambda: roots,
                configuration_digest=reader.configuration_digest,
                read_operation=store.scoped_read_operation,
                seal_read_operation=store.seal_scoped_read_operation,
            )
            with pytest.raises(SnapshotError):
                restored.pinned(receipt.manifest_digest, deadline_at=deadline())
            assert (
                canonical_bytes(
                    metadata.get_data_release_verification(receipt.manifest_digest)
                )
                == original_pair
            )
        finally:
            metadata.close()


def test_protected_workflow_publish_and_exact_order_refusal(
    release, protected_deployment_root, monkeypatch
):
    import os
    from fundamental_service.automatic_data_release import (
        automatic_release_suite_digest,
    )
    from fundamental_service.fiscal_release_runtime import (
        FiscalReleaseRuntime,
        FiscalReleaseInstallationV2,
        FiscalReleaseReadConfigurationV1,
        FiscalReleaseOrderV2,
        release_workflow_configuration_digest,
    )
    from test_fiscal_candidate_preparation import key_file

    display, current, _, reader = release
    key = Ed25519PrivateKey.generate()
    roots = reader.trust_roots().model_copy(
        update={
            "verifiers": {
                "ephemeral-fiscal": DataReleaseVerifierV1(
                    workflow_identity="ephemeral-fiscal-workflow",
                    public_key_ed25519_base64=public_key(key),
                    verification_suite_digest=automatic_release_suite_digest(),
                )
            }
        }
    )
    display.env.metadata._data_release_trust_roots = roots
    trust_file = protected_deployment_root / "release-trust.json"
    trust_file.write_bytes(canonical_bytes(roots))
    trust_file.chmod(0o600)
    orders = protected_deployment_root / "release-orders"
    orders.mkdir(mode=0o700)
    configuration = FiscalReleaseReadConfigurationV1(
        deployment_uid=os.getuid(),
        deployment_file=display.runtime.installation.deployment_file,
        candidate_authority_id=display.candidate_config.candidate_authority_id,
        mapping_trust_roots_file=display.candidate_config.mapping_trust_roots_file,
        release_trust_roots_file=trust_file,
        declared_source_revision=display.runtime.installation.declared_source_revision,
    )
    installation = FiscalReleaseInstallationV2(
        audience="ephemeral-fiscal-release",
        reader=configuration,
        workload_uid=os.getuid(),
        database_role="fundamental",
        orders_directory=orders,
        private_key_file=key_file(protected_deployment_root / "release-key.pem", key),
        verifier_id="ephemeral-fiscal",
        workflow_identity="ephemeral-fiscal-workflow",
        source_revision="b" * 40,
        verification_suite_digest=automatic_release_suite_digest(),
        canary_configuration_file=synthetic_workflow_canary_configuration(
            protected_deployment_root / "canary.json", reader, monkeypatch
        ),
    )
    now = datetime.now(UTC)
    order = FiscalReleaseOrderV2(
        order_id="publish-one",
        audience=installation.audience,
        installation_digest=sha256_digest(installation.model_dump(mode="json")),
        configuration_digest=release_workflow_configuration_digest(installation),
        issuance=display.env.history.read_epoch(
            deadline_at=deadline()
        ).issuance_context,
        approved=FiscalPublishV2(
            candidate_ref=current.candidate.reference, decision_ref=current.reference
        ),
        verification_run_id="ephemeral-installed-job",
        valid_from=now - timedelta(seconds=1),
        valid_until=now + timedelta(minutes=5),
    )
    path = orders / "publish-one.json"
    path.write_bytes(canonical_bytes(order))
    path.chmod(0o600)
    runtime = FiscalReleaseRuntime(
        installation=installation,
        candidates=display.runtime.candidates,
        artifacts=display.env.store,
        metadata=display.env.metadata,
    )
    receipt = runtime.apply(order.order_id, deadline_at=deadline())
    assert receipt.wrote
    path.write_bytes(canonical_bytes(order.model_copy(update={"audience": "wrong"})))
    with pytest.raises(ValueError, match="binding"):
        runtime.apply(order.order_id, deadline_at=deadline())


def test_same_transaction_revoke_writer_waits_and_old_observation_refuses(
    published, monkeypatch
):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from threading import Event
    from fundamental_service.metadata import PostgresMetadataStore
    from fundamental_service.fiscal_admission_history import (
        PostgresFiscalAdmissionHistory,
        FiscalControlBindingV1,
    )

    display, current, _, reader, receipt = published
    with reader._open_pinned(
        receipt.manifest_digest, deadline_at=deadline()
    ) as operation:
        snapshot = operation._complete()
    stream_id = (
        "control:display-decision:"
        + current.decision.body.command.request.locator_digest
    )
    head = next(head for head in snapshot.heads if head.stream_id == stream_id)
    locked, unlock, writer_started = Event(), Event(), Event()
    original = PostgresFiscalAdmissionHistory.validate_activation

    async def pause(self, observed, connection):
        result = await original(self, observed, connection)
        locked.set()
        assert await asyncio.to_thread(unlock.wait, 10)
        return result

    monkeypatch.setattr(PostgresFiscalAdmissionHistory, "validate_activation", pause)
    other = PostgresMetadataStore(display.env.database_url, auto_migrate=False)
    other.start_read_only()
    history = PostgresFiscalAdmissionHistory(other)

    def revoke():
        writer_started.set()
        return history.append_once(
            stream_id.removeprefix("control:"),
            FiscalControlBindingV1(
                action="decision_revoked",
                payload_ref=current.reference,
                command_digest="e" * 64,
            ),
            expected_head=head,
            deadline_at=deadline(),
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            cas = pool.submit(
                display.env.metadata.compare_and_swap_data_release,
                activation(receipt),
                fiscal_observation=snapshot,
            )
            assert locked.wait(10)
            writer = pool.submit(revoke)
            try:
                assert writer_started.wait(5)
                with pytest.raises(TimeoutError):
                    writer.result(timeout=0.2)
            finally:
                unlock.set()
            assert cas.result(timeout=15).revision == 1
            assert writer.result(timeout=15).wrote
        monkeypatch.setattr(
            PostgresFiscalAdmissionHistory, "validate_activation", original
        )
        with pytest.raises(SnapshotError, match="head changed"):
            display.env.metadata.compare_and_swap_data_release(
                activation(receipt, "after-revoke"), fiscal_observation=snapshot
            )
        with pytest.raises(SnapshotError):
            reader.pinned(receipt.manifest_digest, deadline_at=deadline())
    finally:
        other.close()


def test_recovery_table_fence_waits_for_same_transaction_activation(
    published, monkeypatch
):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from threading import Event
    import asyncpg
    from fundamental_service.fiscal_admission_history import (
        PostgresFiscalAdmissionHistory,
    )
    from fundamental_service.persistence_recovery import _lock, _installed_tables

    display, _, _, reader, receipt = published
    with reader._open_pinned(
        receipt.manifest_digest, deadline_at=deadline()
    ) as operation:
        snapshot = operation._complete()
    locked, unlock, recovery_started = Event(), Event(), Event()
    original = PostgresFiscalAdmissionHistory.validate_activation

    async def pause(self, observed, connection):
        result = await original(self, observed, connection)
        locked.set()
        assert await asyncio.to_thread(unlock.wait, 10)
        return result

    monkeypatch.setattr(PostgresFiscalAdmissionHistory, "validate_activation", pause)

    async def recovery_lock():
        connection = await asyncpg.connect(
            display.env.database_url.replace("postgresql+asyncpg://", "postgresql://")
        )
        try:
            async with connection.transaction():
                recovery_started.set()
                await _lock(connection, _installed_tables(), restore=True)
        finally:
            await connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        cas = pool.submit(
            display.env.metadata.compare_and_swap_data_release,
            activation(receipt),
            fiscal_observation=snapshot,
        )
        assert locked.wait(10)
        recovery = pool.submit(asyncio.run, recovery_lock())
        try:
            assert recovery_started.wait(5)
            with pytest.raises(TimeoutError):
                recovery.result(timeout=0.2)
        finally:
            unlock.set()
        assert cas.result(timeout=15).revision == 1
        recovery.result(timeout=15)


@pytest.mark.parametrize("cut", ["signed", "signing", "canary", "database"])
def test_crash_retry_keeps_first_signed_bytes_and_unknown_outcome_refuses(
    release, monkeypatch, cut
):
    display, current, service, reader = release
    approved = FiscalPublishV2(
        candidate_ref=current.candidate.reference, decision_ref=current.reference
    )
    original_put = display.env.store.put_with_receipt
    original_bytes = display.env.store.put_bytes_with_receipt
    original_publish = display.env.metadata.publish_data_release_candidate
    crashed = False
    canary_identity = None

    def after_put(identity, *args, **kwargs):
        nonlocal crashed, canary_identity
        result = original_put(identity, *args, **kwargs)
        if identity.startswith("fiscal-release-canary-v2:"):
            canary_identity = identity
        prefix = {
            "signed": "fiscal-release-signed-v2:",
            "canary": "fiscal-release-canary-v2:",
        }.get(cut)
        if prefix is not None and identity.startswith(prefix) and not crashed:
            crashed = True
            raise RuntimeError("synthetic exit after durable release artifact")
        return result

    def after_bytes(identity, *args, **kwargs):
        nonlocal crashed
        result = original_bytes(identity, *args, **kwargs)
        if (
            cut == "signing"
            and identity.startswith("fiscal-release-signing-v2:")
            and not crashed
        ):
            crashed = True
            raise RuntimeError("synthetic exit after frozen signing body")
        return result

    def after_database(*args, **kwargs):
        nonlocal crashed
        result = original_publish(*args, **kwargs)
        if cut == "database" and not crashed:
            crashed = True
            raise RuntimeError("synthetic exit after publication commit")
        return result

    monkeypatch.setattr(display.env.store, "put_with_receipt", after_put)
    monkeypatch.setattr(display.env.store, "put_bytes_with_receipt", after_bytes)
    monkeypatch.setattr(
        display.env.metadata, "publish_data_release_candidate", after_database
    )
    with pytest.raises(RuntimeError):
        service.publish(approved, deadline_at=deadline())
    assert crashed
    monkeypatch.setattr(display.env.store, "put_with_receipt", original_put)
    monkeypatch.setattr(display.env.store, "put_bytes_with_receipt", original_bytes)
    monkeypatch.setattr(
        display.env.metadata, "publish_data_release_candidate", original_publish
    )
    observation = reader.observe(approved, deadline_at=deadline())
    identity = "fiscal-release-signed-v2:" + observation.manifest.manifest_digest
    marker_id = "fiscal-release-signing-v2:" + observation.manifest.manifest_digest
    assert canary_identity is not None
    retained_report = display.env.store.read(canary_identity)
    if cut == "signing":
        from dataclasses import replace
        from types import SimpleNamespace

        marker = display.env.store.read(marker_id)
        with pytest.raises(SnapshotError) as missing:
            display.env.store.read(identity)
        assert missing.value.code == "ARTIFACT_NOT_FOUND"
        original_authorize = service.signing.authorize

        def refuse_sign(payload):
            pytest.fail("unknown signing outcome must not sign again")

        def authorize(approved, deadline_at):
            original_authorize(approved, deadline_at)
            return SimpleNamespace(sign=refuse_sign)

        monkeypatch.setattr(
            service, "signing", replace(service.signing, authorize=authorize)
        )
        with pytest.raises(SnapshotError) as refused:
            service.publish(approved, deadline_at=deadline())
        assert refused.value.code == "FISCAL_RELEASE_SIGNING_OUTCOME_UNAVAILABLE"
        assert display.env.store.read(marker_id) == marker
        assert display.env.store.read(canary_identity) == retained_report
        with pytest.raises(SnapshotError) as missing:
            display.env.store.read(identity)
        assert missing.value.code == "ARTIFACT_NOT_FOUND"
    elif cut == "canary":
        for absent in (identity, marker_id):
            with pytest.raises(SnapshotError) as missing:
                display.env.store.read(absent)
            assert missing.value.code == "ARTIFACT_NOT_FOUND"
        resumed = service.publish(approved, deadline_at=deadline())
        assert resumed.manifest_digest == observation.manifest.manifest_digest
        assert resumed.canary_ref.artifact_id == canary_identity
        assert display.env.store.read(canary_identity) == retained_report
        signed = json.loads(display.env.store.read(identity))
        assert signed["manifest_digest"] == resumed.manifest_digest
        assert signed["canary_ref"] == resumed.canary_ref.model_dump(mode="json")
        assert display.env.store.read(marker_id)
    else:
        original = display.env.store.read(identity)
        resumed = service.publish(approved, deadline_at=deadline())
        assert resumed.manifest_digest == observation.manifest.manifest_digest
        assert display.env.store.read(identity) == original
