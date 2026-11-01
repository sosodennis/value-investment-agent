from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from src.llm_provider_service.domain.errors import ProviderSettingsError
from src.llm_provider_service.domain.key_imports import KeyImportInput
from src.llm_provider_service.infrastructure.state import ProviderState

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LLM_PROVIDER_POSTGRES_TESTS") != "1",
    reason="requires the isolated PostgreSQL integration database",
)


def _new_key(index: int) -> str:
    return f"sk-or-v1-import-test-{index:04d}-synthetic-material"


async def _delete_organization_data(state: ProviderState, organization_id: str) -> None:
    async with state._sessions() as session:
        await session.execute(
            text(
                "DELETE FROM llm_provider_organization_key_import_batches WHERE organization_id=:organization_id"
            ),
            {"organization_id": organization_id},
        )
        await session.execute(
            text(
                "DELETE FROM llm_provider_organization_owned_keys WHERE organization_id=:organization_id"
            ),
            {"organization_id": organization_id},
        )
        await session.execute(
            text(
                "DELETE FROM llm_provider_organization_deployments WHERE organization_id=:organization_id"
            ),
            {"organization_id": organization_id},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_import_staging_is_encrypted_idempotent_organization_scoped_and_restartable() -> (
    None
):
    encryption_key = Fernet.generate_key().decode("ascii")
    organization_id = f"import-organization-{uuid4()}"
    api_key = _new_key(1)
    state = ProviderState(encryption_key=encryption_key)
    await state.initialize()
    try:
        items = [
            KeyImportInput(1, "Primary", api_key),
            KeyImportInput(2, "Repeated", api_key),
        ]
        batch = await state.create_key_import(
            organization_id=organization_id,
            idempotency_key="same-import-request-192",
            items=items,
        )
        assert (batch.status, batch.total_count, batch.processed_count) == (
            "queued",
            2,
            1,
        )
        assert batch.duplicate_count == 1
        assert batch.items[1].error_code == "duplicate_in_batch"

        async with state._sessions() as session:
            stored = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT encrypted_key FROM llm_provider_organization_key_import_items
                        WHERE organization_id=:organization_id AND batch_id=:batch_id
                        ORDER BY source_line
                        """
                        ),
                        {"organization_id": organization_id, "batch_id": batch.id},
                    )
                )
                .scalars()
                .all()
            )
        assert api_key not in stored[0]
        assert state._cipher is not None
        assert state._cipher.decrypt(stored[0].encode("ascii")).decode() == api_key
        assert stored[1] is None

        replay = await state.create_key_import(
            organization_id=organization_id,
            idempotency_key="same-import-request-192",
            items=items,
        )
        assert replay.id == batch.id
        with pytest.raises(ProviderSettingsError, match="idempotency_key_reused"):
            await state.create_key_import(
                organization_id=organization_id,
                idempotency_key="same-import-request-192",
                items=[KeyImportInput(1, "Primary", _new_key(2))],
            )
        other_organization_id = f"other-organization-{uuid4()}"
        assert (
            await state.get_key_import(
                organization_id=other_organization_id, batch_id=batch.id
            )
            is None
        )
        assert await state.list_key_imports(organization_id=other_organization_id) == []
        other_batch = await state.create_key_import(
            organization_id=other_organization_id,
            idempotency_key="same-import-request-192",
            items=[KeyImportInput(1, "Other organization", _new_key(3))],
        )
        assert other_batch.id != batch.id

        crashed_worker = await state.claim_key_import_items(
            worker_id="worker-before-restart", limit=1
        )
        assert len(crashed_worker) == 1
        async with state._sessions() as session:
            await session.execute(
                text(
                    """
                    UPDATE llm_provider_organization_key_import_items
                    SET lease_until=NOW() - INTERVAL '1 second'
                    WHERE id=:item_id
                    """
                ),
                {"item_id": crashed_worker[0].id},
            )
            await session.commit()

        await state.close()
        restarted = ProviderState(encryption_key=encryption_key)
        await restarted.initialize()
        try:
            resumed = await restarted.claim_key_import_items(
                worker_id="worker-after-restart", limit=1
            )
            assert len(resumed) == 1
            assert resumed[0].id == crashed_worker[0].id
            assert resumed[0].attempts == 2
            assert await restarted.finish_import_success(
                item=resumed[0], model="openrouter/free"
            )
            completed = await restarted.get_key_import(
                organization_id=organization_id, batch_id=batch.id
            )
            assert completed is not None
            assert completed.status == "completed"
            assert completed.imported_count == 1
            assert completed.duplicate_count == 1
            assert completed.items[0].status == "imported"
            listed = await restarted.list_deployments(organization_id=organization_id)
            assert len(listed) == 1
            assert listed[0].organization_id == organization_id
            assert listed[0].fingerprint == resumed[0].fingerprint

            async with restarted._sessions() as session:
                staged = (
                    await session.execute(
                        text(
                            """
                            SELECT encrypted_key FROM llm_provider_organization_key_import_items
                            WHERE organization_id=:organization_id
                              AND batch_id=:batch_id AND source_line=1
                            """
                        ),
                        {"organization_id": organization_id, "batch_id": batch.id},
                    )
                ).scalar_one()
                deployed = (
                    await session.execute(
                        text(
                            """
                            SELECT encrypted_key FROM llm_provider_organization_deployments
                            WHERE organization_id=:organization_id AND fingerprint=:fingerprint
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "fingerprint": resumed[0].fingerprint,
                        },
                    )
                ).scalar_one()
            assert staged is None
            assert api_key not in deployed
            assert restarted._cipher is not None
            assert (
                restarted._cipher.decrypt(deployed.encode("ascii")).decode() == api_key
            )

        finally:
            await _delete_organization_data(restarted, organization_id)
            await restarted.close()
    finally:
        await state.close()


@pytest.mark.asyncio
async def test_encryption_rotation_reencrypts_organization_deployments() -> None:
    old_key = Fernet.generate_key().decode("ascii")
    new_key = Fernet.generate_key().decode("ascii")
    organization_id = f"rotation-organization-{uuid4()}"
    state = ProviderState(encryption_key=old_key)
    await state.initialize()
    try:
        deployment = await state.create_deployment(
            organization_id=organization_id,
            key=_new_key(7),
            label="rotation",
            suffix="0007",
            fingerprint="rotation-fingerprint",
            model="openrouter/free",
        )
        assert await state.rotate_encryption_key(old_key=old_key, new_key=new_key) == 1
        assert await state.deployment_key(
            organization_id=organization_id, deployment_id=deployment.id
        ) == _new_key(7)
    finally:
        await _delete_organization_data(state, organization_id)
        await state.close()


@pytest.mark.asyncio
async def test_two_workers_claim_all_items_of_a_hundred_key_batch_once() -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    organization_id = f"import-organizations-{uuid4()}"
    state_one = ProviderState(encryption_key=encryption_key)
    state_two = ProviderState(encryption_key=encryption_key)
    await asyncio.gather(state_one.initialize(), state_two.initialize())
    try:
        batch = await state_one.create_key_import(
            organization_id=organization_id,
            idempotency_key="hundred-key-batch-192",
            items=[
                KeyImportInput(index + 1, f"Key {index + 1}", _new_key(index + 1))
                for index in range(100)
            ],
        )
        assert batch.total_count == 100
        claims = await asyncio.gather(
            state_one.claim_key_import_items(worker_id="worker-one", limit=50),
            state_two.claim_key_import_items(worker_id="worker-two", limit=50),
        )
        ids_one = {item.id for item in claims[0]}
        ids_two = {item.id for item in claims[1]}
        assert len(ids_one) == len(ids_two) == 50
        assert ids_one.isdisjoint(ids_two)
        assert len(ids_one | ids_two) == 100
        async with state_one._sessions() as session:
            await session.execute(
                text(
                    """
                    UPDATE llm_provider_organization_key_import_items
                    SET expires_at=NOW() - INTERVAL '1 second'
                    WHERE organization_id=:organization_id AND batch_id=:batch_id
                    """
                ),
                {"organization_id": organization_id, "batch_id": batch.id},
            )
            await session.commit()
        assert await state_one.cleanup_key_imports() > 0
        expired = await state_two.get_key_import(
            organization_id=organization_id, batch_id=batch.id
        )
        assert expired is not None
        assert {item.status for item in expired.items} == {"expired"}
        async with state_two._sessions() as session:
            secrets = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT encrypted_key FROM llm_provider_organization_key_import_items
                        WHERE organization_id=:organization_id AND batch_id=:batch_id
                        """
                        ),
                        {"organization_id": organization_id, "batch_id": batch.id},
                    )
                )
                .scalars()
                .all()
            )
        assert secrets == [None] * 100
    finally:
        await _delete_organization_data(state_one, organization_id)
        await asyncio.gather(state_one.close(), state_two.close())


@pytest.mark.asyncio
async def test_concurrent_completion_reconciles_batch_without_router_refresh() -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    organization_id = f"import-complete-organization-{uuid4()}"
    state_one = ProviderState(encryption_key=encryption_key)
    state_two = ProviderState(encryption_key=encryption_key)
    await asyncio.gather(state_one.initialize(), state_two.initialize())
    try:
        batch = await state_one.create_key_import(
            organization_id=organization_id,
            idempotency_key="concurrent-completion-batch-192",
            items=[
                KeyImportInput(index + 1, f"Key {index + 1}", _new_key(index + 1))
                for index in range(100)
            ],
        )
        claims = await asyncio.gather(
            state_one.claim_key_import_items(worker_id="complete-worker-one", limit=50),
            state_two.claim_key_import_items(worker_id="complete-worker-two", limit=50),
        )
        assert len(claims[0]) == len(claims[1]) == 50
        completed = await asyncio.gather(
            *(
                state.finish_import_success(item=item, model="openrouter/free")
                for state, items in zip((state_one, state_two), claims, strict=True)
                for item in items
            )
        )
        assert all(completed)

        snapshot = await state_one.get_key_import(
            organization_id=organization_id, batch_id=batch.id
        )
        assert snapshot is not None
        assert snapshot.status == "completed"
        assert snapshot.imported_count == 100

        async with state_one._sessions() as session:
            stored_status = (
                await session.execute(
                    text(
                        """
                        SELECT status FROM llm_provider_organization_key_import_batches
                        WHERE id=:batch_id AND organization_id=:organization_id
                        """
                    ),
                    {"batch_id": batch.id, "organization_id": organization_id},
                )
            ).scalar_one()
        assert stored_status == "completed"
    finally:
        await _delete_organization_data(state_one, organization_id)
        await asyncio.gather(state_one.close(), state_two.close())


@pytest.mark.asyncio
async def test_retry_after_partial_success_completes_without_router_refresh() -> None:
    encryption_key = Fernet.generate_key().decode("ascii")
    organization_id = f"import-retry-organization-{uuid4()}"
    state = ProviderState(encryption_key=encryption_key)
    await state.initialize()
    try:
        batch = await state.create_key_import(
            organization_id=organization_id,
            idempotency_key="partial-retry-batch-192",
            items=[
                KeyImportInput(1, "Available", _new_key(1)),
                KeyImportInput(2, "Rate limited", _new_key(2)),
            ],
        )
        first_claim = await state.claim_key_import_items(
            worker_id="initial-worker", limit=2
        )
        assert len(first_claim) == 2
        assert await state.finish_import_success(
            item=first_claim[0], model="openrouter/free"
        )

        transient = first_claim[1]
        for attempt in range(1, 4):
            await state.finish_import_failure(
                item=transient,
                error_code="rate_limited",
                retryable=True,
                delay_seconds=0,
            )
            if attempt < 3:
                next_claim = await state.claim_key_import_items(
                    worker_id=f"retry-worker-{attempt}", limit=1
                )
                assert len(next_claim) == 1
                transient = next_claim[0]
                assert transient.attempts == attempt + 1

        failed = await state.get_key_import(
            organization_id=organization_id, batch_id=batch.id
        )
        assert failed is not None
        assert failed.status == "completed_with_errors"
        assert failed.retryable_count == 1

        retried = await state.retry_key_import(
            organization_id=organization_id, batch_id=batch.id
        )
        assert retried is not None
        assert retried.status == "queued"
        assert retried.retryable_count == 0
        retried_claim = await state.claim_key_import_items(
            worker_id="manual-retry-worker", limit=1
        )
        assert len(retried_claim) == 1
        assert retried_claim[0].attempts == 1
        assert await state.finish_import_success(
            item=retried_claim[0], model="openrouter/free"
        )
    finally:
        await _delete_organization_data(state, organization_id)
        await state.close()
