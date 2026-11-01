from __future__ import annotations

import pytest

from search_service.schema import SCHEMA_VERSION, initialize_schema


class _SearchConnection:
    def __init__(self, *, legacy: str | None = None, version: int | None = None):
        self.legacy = legacy
        self.version = version
        self.statements: list[str] = []

    async def execute(self, statement: str, *args: object) -> None:
        self.statements.append(str(statement))

    async def fetchval(self, statement: str, *args: object) -> object:
        query = str(statement)
        if "to_regclass" in query:
            return self.legacy if args and args[0] == f"public.{self.legacy}" else None
        return self.version


@pytest.mark.asyncio
async def test_search_schema_rejects_legacy_provider_tables() -> None:
    connection = _SearchConnection(legacy="search_provider_keys")
    with pytest.raises(RuntimeError, match="legacy Search provider tables"):
        await initialize_schema(connection)


@pytest.mark.asyncio
async def test_search_schema_records_target_version_on_fresh_database() -> None:
    connection = _SearchConnection()
    await initialize_schema(connection)
    assert any(
        "organization_search_provider_keys" in item for item in connection.statements
    )
    assert any(
        "INSERT INTO search_provider_schema_version" in item
        for item in connection.statements
    )
    assert SCHEMA_VERSION == 1


@pytest.mark.asyncio
async def test_search_schema_rejects_unknown_version() -> None:
    connection = _SearchConnection(version=2)
    with pytest.raises(
        RuntimeError, match="unsupported Search provider schema version"
    ):
        await initialize_schema(connection)
