import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

# Construct DB URI from environment variables (keeping it consistent with graph.py)
pg_user = os.environ.get("POSTGRES_USER", "postgres")
pg_pass = os.environ.get("POSTGRES_PASSWORD", "postgres")
pg_host = os.environ.get("POSTGRES_HOST", "localhost")
pg_port = os.environ.get("POSTGRES_PORT", "5432")
pg_db = os.environ.get("POSTGRES_DB", "langgraph")

# Using asyncpg (native asyncio) for stability
DATABASE_URL = f"postgresql+asyncpg://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=20,  # Increased from default 5
    max_overflow=20,  # Increased from default 10
    pool_timeout=360,  # Wait up to 60s for a connection
    pool_pre_ping=True,  # Check connection health before checking out
)
AsyncSessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)


Base = declarative_base()


async def init_db():
    async with engine.begin() as conn:
        # We'll import models here or at the top level to ensure they are registered
        from .models import Artifact, ChatMessage  # noqa

        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
