from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from cryptography.fernet import Fernet

from search_service.postgres_control_plane import PostgresSearchControlPlane

pytestmark = pytest.mark.skipif(
    not os.getenv("SEARCH_TEST_DATABASE_URL"),
    reason="set SEARCH_TEST_DATABASE_URL to run PostgreSQL integration coverage",
)


@pytest.mark.asyncio
async def test_postgres_control_plane_is_owner_scoped_atomic_and_durable() -> None:
    owner = f"search-test-{uuid.uuid4()}"
    encryption_key = os.getenv(
        "SEARCH_TEST_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    store = PostgresSearchControlPlane(
        os.environ["SEARCH_TEST_DATABASE_URL"],
        encryption_key,
    )
    pool = await store._connection()
    try:
        assert await store.is_ready() is True
        inserted = await asyncio.gather(
            *(
                store.add_tested_key(
                    organization_id=owner,
                    provider=f"provider-{index // 4}",
                    api_key=f"secret-{index}",
                    label=f"key-{index}",
                    suffix=f"{index:04}",
                    fingerprint=f"fingerprint-{index}",
                )
                for index in range(8)
            )
        )
        assert {
            item.priority for item in inserted if item.provider == "provider-0"
        } == {0, 1, 2, 3}
        assert {
            item.priority for item in inserted if item.provider == "provider-1"
        } == {0, 1, 2, 3}
        duplicate = await store.add_tested_key(
            organization_id=owner,
            provider="provider-0",
            api_key="secret-0",
            label="duplicate-label-is-ignored",
            suffix="0000",
            fingerprint="fingerprint-0",
        )
        assert duplicate.id == inserted[0].id
        credentials = await store.credentials_for(organization_id=owner)
        assert {item.api_key for item in credentials} == {
            f"secret-{index}" for index in range(8)
        }
        assert await store.credentials_for(organization_id=f"{owner}-other") == ()

        async with pool.acquire() as connection:
            ciphertexts = await connection.fetch(
                "SELECT encrypted_key FROM organization_search_provider_keys WHERE organization_id=$1",
                owner,
            )
        assert len(ciphertexts) == 8
        assert all("secret-" not in row["encrypted_key"] for row in ciphertexts)

        claims = await asyncio.gather(
            *(
                store.claim_credential(
                    organization_id=owner, provider="provider-0", lease_seconds=2
                )
                for _ in range(2)
            )
        )
        assert all(item is not None for item in claims)
        claimed_ids = {item.key_id for item in claims if item is not None}
        assert len(claimed_ids) == 2
        await store.record_key_failure(
            organization_id=owner,
            key_id=claims[0].key_id,
            cooldown_seconds=1,
        )
        await store.release_credential(
            organization_id=owner, key_id=claims[1].key_id, succeeded=False
        )
        available = await store.credentials_for(organization_id=owner)
        assert sum(item.provider == "provider-0" for item in available) == 3
        await asyncio.sleep(1.1)
        assert (
            sum(
                item.provider == "provider-0"
                for item in await store.credentials_for(organization_id=owner)
            )
            == 4
        )

        leased = await store.claim_credential(
            organization_id=owner, provider="provider-1", lease_seconds=30
        )
        assert leased is not None
        disabled = await store.set_key_enabled(
            organization_id=owner, key_id=leased.key_id, enabled=False
        )
        assert disabled.enabled is False
        claimed_again = await store.claim_credential(
            organization_id=owner, provider="provider-1", lease_seconds=30
        )
        assert claimed_again is not None
        assert claimed_again.key_id != leased.key_id
        await store.release_credential(
            organization_id=owner, key_id=claimed_again.key_id, succeeded=True
        )
        await store.release_credential(
            organization_id=owner, key_id=leased.key_id, succeeded=True
        )
        assert (
            next(
                item
                for item in await store.list_keys(organization_id=owner)
                if item.id == leased.key_id
            ).status
            == "disabled"
        )

        persisted = PostgresSearchControlPlane(
            os.environ["SEARCH_TEST_DATABASE_URL"],
            encryption_key,
        )
        assert {
            item.api_key
            for item in await persisted.credentials_for(organization_id=owner)
        } == {f"secret-{index}" for index in range(8)}
        await persisted.aclose()

        rotated_key = Fernet.generate_key().decode("ascii")
        assert (
            await store.rotate_encryption_key(
                old_key=encryption_key, new_key=rotated_key
            )
            == 8
        )
        rotated = PostgresSearchControlPlane(
            os.environ["SEARCH_TEST_DATABASE_URL"], rotated_key
        )
        assert {
            item.api_key
            for item in await rotated.credentials_for(organization_id=owner)
        } == {f"secret-{index}" for index in range(8)}
        await rotated.aclose()
    finally:
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "DELETE FROM organization_search_provider_preferences WHERE organization_id=$1",
                    owner,
                )
                await connection.execute(
                    "DELETE FROM organization_search_provider_keys WHERE organization_id=$1",
                    owner,
                )
                await connection.execute(
                    "DELETE FROM organization_search_provider_health WHERE organization_id=$1",
                    owner,
                )
        await store.aclose()
