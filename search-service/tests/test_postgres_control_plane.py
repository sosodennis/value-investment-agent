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
                    subject_id=owner,
                    provider=f"provider-{index}",
                    api_key=f"secret-{index}",
                    label=f"key-{index}",
                    suffix=f"{index:04}",
                    fingerprint=f"fingerprint-{index}",
                )
                for index in range(8)
            )
        )
        assert len({item.priority for item in inserted}) == 8
        credentials = await store.credentials_for(subject_id=owner)
        assert {item.api_key for item in credentials} == {
            f"secret-{index}" for index in range(8)
        }
        assert await store.credentials_for(subject_id=f"{owner}-other") == ()

        async with pool.acquire() as connection:
            ciphertexts = await connection.fetch(
                "SELECT encrypted_key FROM search_provider_keys WHERE owner_id=$1",
                owner,
            )
        assert len(ciphertexts) == 8
        assert all("secret-" not in row["encrypted_key"] for row in ciphertexts)

        await store.record_failure(
            subject_id=owner, provider="provider-0", cooldown_seconds=1
        )
        assert "provider-0" not in {
            item.provider for item in await store.credentials_for(subject_id=owner)
        }
        await asyncio.sleep(1.1)
        assert "provider-0" in {
            item.provider for item in await store.credentials_for(subject_id=owner)
        }

        persisted = PostgresSearchControlPlane(
            os.environ["SEARCH_TEST_DATABASE_URL"],
            encryption_key,
        )
        assert {
            item.api_key for item in await persisted.credentials_for(subject_id=owner)
        } == {f"secret-{index}" for index in range(8)}
        await persisted.aclose()
    finally:
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "DELETE FROM search_provider_preferences WHERE owner_id=$1", owner
                )
                await connection.execute(
                    "DELETE FROM search_provider_keys WHERE owner_id=$1", owner
                )
        await store.aclose()
