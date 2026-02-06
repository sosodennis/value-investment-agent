import asyncio

import pytest

from src.infrastructure.database import engine


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def cleanup_database_connections():
    """Ensure database connections are disposed after each test to avoid event loop issues."""
    yield
    await engine.dispose()
