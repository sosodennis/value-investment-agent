"""Disposable databases for isolated persistence recovery checks."""

import asyncio
import os
from uuid import uuid4

import asyncpg
import pytest


@pytest.fixture(autouse=True)
def isolated_image_build_value(monkeypatch):
    import fundamental_service.parser_action_identity as identity

    monkeypatch.setattr(identity, "_SHARED_BUILD", None)


@pytest.fixture
def recovery_databases():
    database_url = os.getenv("FUNDAMENTAL_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("isolated PostgreSQL is required")
    base = database_url.replace("postgresql+asyncpg://", "postgresql://")
    prefix, _ = base.rsplit("/", 1)
    names = tuple(f"issue361_recovery_{uuid4().hex}" for _ in range(2))

    async def create():
        connection = await asyncpg.connect(base)
        try:
            for name in names:
                await connection.execute(f'CREATE DATABASE "{name}"')
        finally:
            await connection.close()

    async def drop():
        connection = await asyncpg.connect(base)
        try:
            for name in names:
                await connection.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        finally:
            await connection.close()

    asyncio.run(create())
    try:
        yield tuple(f"{prefix}/{name}" for name in names)
    finally:
        asyncio.run(drop())
