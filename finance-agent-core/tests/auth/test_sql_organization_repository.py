from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime

import pytest
from sqlalchemy import delete, func, select

from src.auth.application.errors import MembershipInvariantError
from src.auth.domain.entities import MembershipRole, MembershipStatus
from src.auth.domain.events import (
    OrganizationLifecycleEvent,
    OrganizationLifecycleEventType,
)
from src.auth.infrastructure.models import (
    MembershipModel,
    OrganizationLifecycleEventModel,
    OrganizationModel,
    SessionModel,
    UserModel,
)
from src.auth.infrastructure.organization_repository import (
    SqlAlchemyOrganizationLifecycleRepository,
)
from src.auth.infrastructure.repositories import SqlAlchemyUserRepository
from src.infrastructure.database import AsyncSessionLocal, init_db

pytestmark = pytest.mark.skipif(
    os.getenv("AUTH_POSTGRES_TEST") != "1",
    reason="requires the isolated PostgreSQL integration project",
)


async def _cleanup(*, user_ids: set[str], organization_ids: set[str]) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(OrganizationLifecycleEventModel).where(
                OrganizationLifecycleEventModel.organization_id.in_(organization_ids)
            )
        )
        await session.execute(
            delete(SessionModel).where(SessionModel.user_id.in_(user_ids))
        )
        await session.execute(
            delete(MembershipModel).where(MembershipModel.user_id.in_(user_ids))
        )
        await session.execute(
            delete(OrganizationModel).where(OrganizationModel.id.in_(organization_ids))
        )
        await session.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))
        await session.commit()


@pytest.mark.asyncio
async def test_lifecycle_repository_locks_owner_transfer_and_persists_events() -> None:
    await init_db()
    now = datetime.utcnow()
    owner_email = f"owner-{uuid.uuid4()}@example.test"
    target_email = f"target-{uuid.uuid4()}@example.test"
    users = SqlAlchemyUserRepository()
    repository = SqlAlchemyOrganizationLifecycleRepository()
    owner = await users.create_with_default_organization(
        email=owner_email, password_hash="hash"
    )
    target = await users.create_with_default_organization(
        email=target_email, password_hash="hash"
    )
    organization = await repository.create_organization(
        owner_user_id=owner.user.id, name="Alpha", now=now
    )
    organization_id = organization.organization.id
    try:
        async with AsyncSessionLocal() as session:
            target_membership = MembershipModel(
                organization_id=organization_id,
                user_id=target.user.id,
                role=MembershipRole.MEMBER.value,
                status=MembershipStatus.ACTIVE.value,
            )
            session.add(target_membership)
            await session.commit()

        event = OrganizationLifecycleEvent(
            event_type=OrganizationLifecycleEventType.ORGANIZATION_RENAMED,
            organization_id=organization_id,
            actor_user_id=owner.user.id,
            target_user_id=None,
            payload={"name": "Alpha"},
            occurred_at=now,
        )
        await repository.append_event(event)

        results = await asyncio.gather(
            repository.transfer_ownership(
                organization_id=organization_id,
                current_owner_user_id=owner.user.id,
                target_user_id=target.user.id,
                now=now,
            ),
            repository.transfer_ownership(
                organization_id=organization_id,
                current_owner_user_id=owner.user.id,
                target_user_id=target.user.id,
                now=now,
            ),
            return_exceptions=True,
        )
        successes = [result for result in results if not isinstance(result, Exception)]
        failures = [result for result in results if isinstance(result, Exception)]
        assert len(successes) == 1, results
        assert len(failures) == 1

        members = await repository.list_members(organization_id=organization_id)
        assert (
            sum(
                member.membership.role is MembershipRole.OWNER
                and member.membership.status is MembershipStatus.ACTIVE
                for member in members
            )
            == 1
        )
        assert await session_count_events(organization_id=organization_id) == 1

        with pytest.raises(MembershipInvariantError):
            await repository.change_membership(
                organization_id=organization_id,
                user_id=target.user.id,
                role=None,
                status=MembershipStatus.SUSPENDED.value,
                now=now,
            )
    finally:
        await _cleanup(
            user_ids={owner.user.id, target.user.id},
            organization_ids={
                owner.organization.id,
                target.organization.id,
                organization_id,
            },
        )


async def session_count_events(*, organization_id: str) -> int:
    async with AsyncSessionLocal() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(OrganizationLifecycleEventModel)
                .where(
                    OrganizationLifecycleEventModel.organization_id == organization_id
                )
            )
            or 0
        )
