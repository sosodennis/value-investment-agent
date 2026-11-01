from __future__ import annotations

import os
import uuid
from dataclasses import replace
from datetime import datetime

import pytest
from sqlalchemy import delete, text

from src.auth.application.directory_service import DirectoryService
from src.auth.domain.entities import (
    AuthenticatedContext,
    MembershipRole,
    MembershipStatus,
    SessionRecord,
)
from src.auth.infrastructure.directory_repository import SqlAlchemyDirectoryRepository
from src.auth.infrastructure.models import MembershipModel, OrganizationModel, UserModel
from src.auth.infrastructure.repositories import SqlAlchemyUserRepository
from src.infrastructure.database import AsyncSessionLocal, init_db

pytestmark = pytest.mark.skipif(
    os.getenv("AUTH_POSTGRES_TEST") != "1",
    reason="requires the isolated PostgreSQL integration project",
)


@pytest.mark.asyncio
async def test_directory_search_filters_current_members_and_supports_cursor_pages() -> (
    None
):
    await init_db()
    suffix = uuid.uuid4().hex
    emails = [
        f"directory-{name}-{suffix}@example.test"
        for name in ("actor", "member", "pending", "one", "two", "three")
    ]
    users = SqlAlchemyUserRepository()
    registrations = [
        await users.create_with_default_organization(
            email=email,
            password_hash="hash",
            display_name=name,
            display_name_normalized=name.casefold(),
        )
        for email, name in zip(
            emails,
            (
                "Actor",
                "Analyst Member",
                "Analyst Pending",
                "Analyst One",
                "Analyst Two",
                "Analyst Three",
            ),
            strict=True,
        )
    ]
    actor = registrations[0]
    current_organization_id = actor.organization.id
    try:
        async with AsyncSessionLocal() as session:
            session.add_all(
                [
                    MembershipModel(
                        organization_id=current_organization_id,
                        user_id=registrations[1].user.id,
                        role=MembershipRole.MEMBER.value,
                        status=MembershipStatus.ACTIVE.value,
                    ),
                    MembershipModel(
                        organization_id=current_organization_id,
                        user_id=registrations[2].user.id,
                        role=MembershipRole.MEMBER.value,
                        status=MembershipStatus.PENDING.value,
                    ),
                ]
            )
            await session.commit()

        now = datetime.utcnow()
        context = AuthenticatedContext(
            user=actor.user,
            membership=actor.membership,
            session=SessionRecord(
                id="directory-session",
                user_id=actor.user.id,
                active_organization_id=current_organization_id,
                token_hash="token",
                csrf_token_hash="csrf",
                expires_at=now,
                revoked_at=None,
                created_at=now,
            ),
        )
        page = DirectoryService(
            repository=SqlAlchemyDirectoryRepository(),
            cursor_secret="test-directory-cursor-secret",
        )
        first = await page.search_users(
            context=context, query="analyst", limit=2, cursor=None
        )
        second = await page.search_users(
            context=context, query="analyst", limit=2, cursor=first.next_cursor
        )

        assert [item.display_name for item in first.items] == [
            "Analyst One",
            "Analyst Three",
        ]
        assert [item.display_name for item in second.items] == ["Analyst Two"]
        assert registrations[1].user.id not in {
            item.user_id for item in first.items + second.items
        }
        assert registrations[2].user.id not in {
            item.user_id for item in first.items + second.items
        }
        member_context = replace(
            context,
            membership=replace(context.membership, role=MembershipRole.MEMBER),
        )
        member_page = await page.search_users(
            context=member_context, query="analyst", limit=10, cursor=None
        )
        assert [item.display_name for item in member_page.items] == ["Analyst Member"]
    finally:
        user_ids = [registration.user.id for registration in registrations]
        organization_ids = [
            registration.organization.id for registration in registrations
        ]
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    "ALTER TABLE auth_audit_events "
                    "DISABLE TRIGGER auth_audit_events_no_truncate"
                )
            )
            await session.execute(text("TRUNCATE TABLE auth_audit_events"))
            await session.execute(
                text(
                    "ALTER TABLE auth_audit_events "
                    "ENABLE TRIGGER auth_audit_events_no_truncate"
                )
            )
            await session.execute(
                delete(MembershipModel).where(MembershipModel.user_id.in_(user_ids))
            )
            await session.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))
            await session.execute(
                delete(OrganizationModel).where(
                    OrganizationModel.id.in_(organization_ids)
                )
            )
            await session.commit()
