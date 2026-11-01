from __future__ import annotations

import pytest
from src.llm_provider_service.infrastructure.schema import (
    SCHEMA_VERSION,
    initialize_schema,
)


class _Result:
    def __init__(self, value: object = None):
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value


class _LlmConnection:
    def __init__(self, *, legacy: str | None = None, version: int | None = None):
        self.legacy = legacy
        self.version = version
        self.statements: list[str] = []

    async def execute(self, statement: object, parameters: object = None) -> _Result:
        query = str(statement)
        self.statements.append(query)
        if "to_regclass" in query:
            qualified = (parameters or {}).get("qualified")
            return _Result(
                self.legacy if qualified == f"public.{self.legacy}" else None
            )
        if "SELECT version FROM" in query:
            return _Result(self.version)
        return _Result()


@pytest.mark.asyncio
async def test_llm_schema_rejects_legacy_provider_tables() -> None:
    connection = _LlmConnection(legacy="llm_provider_deployments")
    with pytest.raises(RuntimeError, match="legacy LLM provider tables"):
        await initialize_schema(connection)


@pytest.mark.asyncio
async def test_llm_schema_records_target_version_on_fresh_database() -> None:
    connection = _LlmConnection()
    await initialize_schema(connection)
    assert any(
        "llm_provider_organization_deployments" in item
        for item in connection.statements
    )
    assert any(
        "INSERT INTO llm_provider_schema_version" in item
        for item in connection.statements
    )
    assert SCHEMA_VERSION == 1


@pytest.mark.asyncio
async def test_llm_schema_rejects_unknown_version() -> None:
    connection = _LlmConnection(version=2)
    with pytest.raises(RuntimeError, match="unsupported LLM provider schema version"):
        await initialize_schema(connection)
