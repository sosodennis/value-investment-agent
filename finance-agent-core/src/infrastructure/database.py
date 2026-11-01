import os

from sqlalchemy import text
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
        from src.audit.infrastructure.models import AuditEventModel  # noqa: F401

        # We'll import models here or at the top level to ensure they are registered
        from src.auth.infrastructure.models import (  # noqa: F401
            InvitationModel,
            InvitationOperationModel,
            MembershipModel,
            OrganizationModel,
            OwnedResourceModel,
            SessionModel,
            UserModel,
        )
        from src.notifications.infrastructure.models import (  # noqa: F401
            NotificationEventModel,
            NotificationInboxItemModel,
            NotificationOutboxModel,
        )

        from .models import (  # noqa: F401
            Artifact,
            ChatMessage,
            DatabaseMigration,
            DatabaseMigrationWorkItem,
            LlmSetting,
            WorkflowActivityCursor,
            WorkflowActivityEvent,
            WorkflowRetryOperation,
            WorkflowRun,
            WorkflowRunHistory,
            WorkflowRunResume,
        )

        await conn.run_sync(Base.metadata.create_all)
        if conn.dialect.name == "postgresql":
            await conn.execute(
                text(
                    """
                    CREATE OR REPLACE FUNCTION prevent_auth_audit_events_mutation()
                    RETURNS trigger
                    LANGUAGE plpgsql
                    AS $$
                    BEGIN
                        RAISE EXCEPTION 'auth_audit_events is append-only';
                    END;
                    $$
                    """
                )
            )
            await conn.execute(
                text(
                    "DROP TRIGGER IF EXISTS auth_audit_events_append_only "
                    "ON auth_audit_events"
                )
            )
            await conn.execute(
                text(
                    "DROP TRIGGER IF EXISTS auth_audit_events_no_truncate "
                    "ON auth_audit_events"
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TRIGGER auth_audit_events_append_only
                    BEFORE UPDATE OR DELETE ON auth_audit_events
                    FOR EACH ROW EXECUTE FUNCTION prevent_auth_audit_events_mutation()
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TRIGGER auth_audit_events_no_truncate
                    BEFORE TRUNCATE ON auth_audit_events
                    FOR EACH STATEMENT EXECUTE FUNCTION prevent_auth_audit_events_mutation()
                    """
                )
            )


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
