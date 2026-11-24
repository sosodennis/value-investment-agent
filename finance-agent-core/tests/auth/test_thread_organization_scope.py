from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select

from api.server import OwnedThreadPort
from src.analysis_runtime.application.runtime_service import AnalysisRuntimeService
from src.analysis_runtime.domain.errors import ThreadNotFoundError
from src.analysis_runtime.infrastructure.memory_repository import (
    InMemoryActivityRepository,
)
from src.artifacts.application.service import ArtifactService
from src.artifacts.infrastructure.sqlalchemy_repository import (
    SqlAlchemyArtifactRepository,
)
from src.artifacts.interface.routes import build_default_artifact_service, router
from src.auth.application.ownership_service import OwnershipService
from src.auth.entrypoint import Principal, require_current_user
from src.auth.infrastructure.models import OwnedResourceModel, UserModel
from src.auth.infrastructure.repositories import SqlAlchemyOwnershipRepository
from src.infrastructure.database import AsyncSessionLocal, init_db
from src.infrastructure.migrations.thread_ownership import (
    run_thread_ownership_migration,
)
from src.infrastructure.models import Artifact, WorkflowRunHistory
from src.shared.artifacts.artifact_data_models import FinancialReportsArtifactData

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("AUTH_POSTGRES_TEST") != "1",
        reason="requires the isolated PostgreSQL integration project",
    ),
]


@pytest.fixture
async def scoped_user():
    await init_db()
    await run_thread_ownership_migration()
    user_id = str(uuid4())
    async with AsyncSessionLocal() as session:
        session.add(
            UserModel(
                id=user_id,
                email=f"{user_id}@example.test",
                display_name="Scope reader",
                display_name_normalized="scope reader",
                password_hash="test-only",
            )
        )
        await session.commit()
    yield user_id
    async with AsyncSessionLocal() as session:
        thread_ids = select(OwnedResourceModel.resource_id).where(
            OwnedResourceModel.user_id == user_id,
            OwnedResourceModel.resource_type == "thread",
        )
        await session.execute(
            delete(Artifact).where(Artifact.thread_id.in_(thread_ids))
        )
        await session.execute(
            delete(WorkflowRunHistory).where(WorkflowRunHistory.principal_id == user_id)
        )
        await session.execute(
            delete(OwnedResourceModel).where(OwnedResourceModel.user_id == user_id)
        )
        await session.execute(delete(UserModel).where(UserModel.id == user_id))
        await session.commit()


async def test_concurrent_thread_claim_binds_one_org_and_cannot_be_adopted(scoped_user):
    repo = SqlAlchemyOwnershipRepository()
    thread_id = f"scope-{uuid4()}"
    results = await asyncio.gather(
        *(
            repo.claim(
                resource_type="thread",
                resource_id=thread_id,
                user_id=scoped_user,
                organization_id=org,
            )
            for org in ("org-a", "org-b")
        )
    )
    assert sorted(results) == [False, True]
    winner = ("org-a", "org-b")[results.index(True)]
    loser = "org-b" if winner == "org-a" else "org-a"
    assert (
        await repo.owner_of(
            resource_type="thread", resource_id=thread_id, organization_id=winner
        )
        == scoped_user
    )
    assert (
        await repo.owner_of(
            resource_type="thread", resource_id=thread_id, organization_id=loser
        )
        is None
    )
    assert not await repo.claim(
        resource_type="thread",
        resource_id=thread_id,
        user_id="another-user",
        organization_id=winner,
    )
    assert await repo.claim(
        resource_type="thread",
        resource_id=thread_id,
        user_id=scoped_user,
        organization_id=winner,
    )

    ownership = OwnershipService(repo)
    with patch("api.server.get_ownership_service", return_value=ownership):
        runtime = AnalysisRuntimeService(
            repository=InMemoryActivityRepository(),
            owner=OwnedThreadPort(),
            runner=AsyncMock(),
        )
        with pytest.raises(ThreadNotFoundError):
            await runtime.start(
                principal_id=scoped_user,
                thread_id=thread_id,
                organization_id=loser,
                input_data={"message": "Must not start"},
            )
        with pytest.raises(ThreadNotFoundError):
            await runtime.snapshot(
                principal_id=scoped_user, thread_id=thread_id, organization_id=loser
            )


async def test_unscoped_thread_cannot_be_claimed_until_exact_retained_history_proves_org(
    scoped_user,
):
    ids = {
        name: f"{name}-{uuid4()}"
        for name in ("proven", "ambiguous", "unscoped", "empty", "wrong-owner")
    }
    async with AsyncSessionLocal() as session:
        session.add_all(
            [
                OwnedResourceModel(
                    resource_type="thread", resource_id=value, user_id=scoped_user
                )
                for value in ids.values()
            ]
        )
        for name, orgs in {
            "proven": ["org-a"],
            "ambiguous": ["org-a", "org-b"],
            "unscoped": ["unscoped"],
            "wrong-owner": ["org-a"],
        }.items():
            session.add_all(
                [
                    WorkflowRunHistory(
                        thread_id=ids[name],
                        run_id=str(uuid4()),
                        principal_id="another-user"
                        if name == "wrong-owner"
                        else scoped_user,
                        organization_id=org,
                        status="completed",
                    )
                    for org in orgs
                ]
            )
        await session.commit()
    repo = SqlAlchemyOwnershipRepository()
    assert not await repo.claim(
        resource_type="thread",
        resource_id=ids["proven"],
        user_id=scoped_user,
        organization_id="org-a",
    )
    await run_thread_ownership_migration()
    await run_thread_ownership_migration()
    assert (
        await repo.owner_of(
            resource_type="thread", resource_id=ids["proven"], organization_id="org-a"
        )
        == scoped_user
    )
    for name in ("ambiguous", "unscoped", "empty", "wrong-owner"):
        assert (
            await repo.owner_of(
                resource_type="thread", resource_id=ids[name], organization_id="org-a"
            )
            is None
        )
        assert not await repo.claim(
            resource_type="thread",
            resource_id=ids[name],
            user_id=scoped_user,
            organization_id="org-a",
        )
    # Wrong-principal history is not cascade-owned by the test user.
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(WorkflowRunHistory).where(
                WorkflowRunHistory.thread_id == ids["wrong-owner"]
            )
        )
        await session.commit()


async def test_standalone_artifact_reads_without_a_run_and_rejects_cross_org_or_owner(
    scoped_user,
):
    thread_id = f"statement-{uuid4()}"
    ownership = OwnershipService(SqlAlchemyOwnershipRepository())
    assert await ownership.claim(
        user_id=scoped_user,
        resource_type="thread",
        resource_id=thread_id,
        organization_id="org-a",
    )
    artifacts = ArtifactService(SqlAlchemyArtifactRepository())
    payload = FinancialReportsArtifactData(
        ticker="TEST",
        model_type="read-only",
        company_name="Example Issuer",
        status="done",
    ).model_dump(mode="json")
    first = await artifacts.save_thread_artifact(
        data=payload,
        artifact_type="financial_reports",
        produced_by="fundamental_analysis",
        thread_id=thread_id,
    )
    second = await artifacts.save_thread_artifact(
        data=payload,
        artifact_type="financial_reports",
        produced_by="fundamental_analysis",
        thread_id=thread_id,
    )
    assert first == second
    async with AsyncSessionLocal() as session:
        assert (
            await session.scalar(
                select(WorkflowRunHistory.run_id).where(
                    WorkflowRunHistory.thread_id == thread_id
                )
            )
            is None
        )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[build_default_artifact_service] = lambda: artifacts

    def principal(org="org-a", user=None):
        return Principal(
            user_id=user or scoped_user,
            subject=user or scoped_user,
            email="scope@example.test",
            organization_id=org,
            membership_id="member",
        )

    with patch(
        "src.artifacts.interface.routes.get_ownership_service", return_value=ownership
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            app.dependency_overrides[require_current_user] = lambda: principal()
            response = await client.get(f"/api/v1/artifacts/{first}")
            assert response.status_code == 200
            assert response.json()["data"]["ticker"] == "TEST"
            assert (
                await client.get(f"/api/v1/artifacts/{first}?run_id=nonexistent")
            ).status_code == 404
            app.dependency_overrides[require_current_user] = lambda: principal(
                org="org-b"
            )
            assert (await client.get(f"/api/v1/artifacts/{first}")).status_code == 404
            app.dependency_overrides[require_current_user] = lambda: principal(
                user="another-user"
            )
            assert (await client.get(f"/api/v1/artifacts/{first}")).status_code == 404
