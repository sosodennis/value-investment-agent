from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime

import httpx
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from api.server import app
from src.auth.application.errors import (
    InvalidOrganizationContextError,
    RegistrationConflictError,
)
from src.auth.application.service import AuthService
from src.auth.application.wiring import get_auth_service, reset_auth_wiring
from src.auth.infrastructure.models import (
    MembershipModel,
    OrganizationModel,
    SessionModel,
    UserModel,
)
from src.auth.infrastructure.passwords import Argon2PasswordHasher
from src.auth.infrastructure.repositories import (
    SqlAlchemyOrganizationRepository,
    SqlAlchemySessionRepository,
    SqlAlchemyUserRepository,
)
from src.auth.interface.dependencies import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
)
from src.infrastructure.database import AsyncSessionLocal, init_db

pytestmark = pytest.mark.skipif(
    os.getenv("AUTH_POSTGRES_TEST") != "1",
    reason="requires the isolated PostgreSQL integration project",
)


async def _cleanup_user(email: str) -> None:
    async with AsyncSessionLocal() as session:
        user_id = await session.scalar(
            select(UserModel.id).where(UserModel.email == email)
        )
        if user_id is None:
            return
        organization_ids = set(
            (
                await session.scalars(
                    select(MembershipModel.organization_id).where(
                        MembershipModel.user_id == user_id
                    )
                )
            ).all()
        )
        await session.execute(
            delete(SessionModel).where(SessionModel.user_id == user_id)
        )
        await session.execute(
            delete(MembershipModel).where(MembershipModel.user_id == user_id)
        )
        if organization_ids:
            await session.execute(
                delete(OrganizationModel).where(
                    OrganizationModel.id.in_(organization_ids)
                )
            )
        await session.execute(delete(UserModel).where(UserModel.id == user_id))
        await session.commit()


@pytest.mark.asyncio
async def test_concurrent_registration_is_atomic_and_membership_is_unique() -> None:
    await init_db()
    email = f"auth-{uuid.uuid4()}@example.test"
    repository = SqlAlchemyUserRepository()
    try:
        results = await asyncio.gather(
            repository.create_with_default_organization(
                email=email, password_hash="hash-a"
            ),
            repository.create_with_default_organization(
                email=email, password_hash="hash-b"
            ),
            return_exceptions=True,
        )

        registrations = [
            result for result in results if not isinstance(result, Exception)
        ]
        assert len(registrations) == 1
        assert (
            sum(isinstance(result, RegistrationConflictError) for result in results)
            == 1
        )
        registration = registrations[0]

        async with AsyncSessionLocal() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(UserModel)
                    .where(UserModel.email == email)
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(OrganizationModel)
                    .where(OrganizationModel.id == registration.organization.id)
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(MembershipModel)
                    .where(MembershipModel.user_id == registration.user.id)
                )
                == 1
            )

            session.add(
                MembershipModel(
                    organization_id=registration.organization.id,
                    user_id=registration.user.id,
                    role="owner",
                    status="active",
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

            session.add(
                MembershipModel(
                    organization_id=registration.organization.id,
                    user_id=registration.user.id,
                    role="member",
                    status="unknown",
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
    finally:
        await _cleanup_user(email)


@pytest.mark.asyncio
async def test_only_active_membership_selects_context_and_revocation_invalidates_it() -> (
    None
):
    await init_db()
    email = f"auth-{uuid.uuid4()}@example.test"
    users = SqlAlchemyUserRepository()
    service = AuthService(
        users=users,
        organizations=SqlAlchemyOrganizationRepository(),
        sessions=SqlAlchemySessionRepository(),
        password_hasher=Argon2PasswordHasher(),
    )
    now = datetime.utcnow()
    try:
        registered = await service.register(
            email=email, password="correct-horse-battery", now=now
        )
        active_org_id = str(uuid.uuid4())
        pending_org_id = str(uuid.uuid4())
        suspended_org_id = str(uuid.uuid4())
        removed_org_id = str(uuid.uuid4())
        async with AsyncSessionLocal() as session:
            session.add_all(
                [
                    OrganizationModel(id=active_org_id, name="Active team"),
                    OrganizationModel(id=pending_org_id, name="Pending team"),
                    OrganizationModel(id=suspended_org_id, name="Suspended team"),
                    OrganizationModel(id=removed_org_id, name="Removed team"),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    MembershipModel(
                        organization_id=active_org_id,
                        user_id=registered.user.id,
                        role="member",
                        status="active",
                    ),
                    MembershipModel(
                        organization_id=pending_org_id,
                        user_id=registered.user.id,
                        role="member",
                        status="pending",
                    ),
                    MembershipModel(
                        organization_id=suspended_org_id,
                        user_id=registered.user.id,
                        role="member",
                        status="suspended",
                    ),
                    MembershipModel(
                        organization_id=removed_org_id,
                        user_id=registered.user.id,
                        role="member",
                        status="removed",
                    ),
                ]
            )
            await session.commit()

        selected = await service.select_active_organization(
            session_token=registered.session_token,
            organization_id=active_org_id,
            now=now,
        )
        assert selected.membership.organization_id == active_org_id
        authenticated = await service.authenticate(
            session_token=registered.session_token, now=now
        )
        assert authenticated is not None
        assert authenticated.membership.organization_id == active_org_id

        for organization_id in (pending_org_id, suspended_org_id, removed_org_id):
            with pytest.raises(InvalidOrganizationContextError):
                await service.select_active_organization(
                    session_token=registered.session_token,
                    organization_id=organization_id,
                    now=now,
                )

        await service.logout(session_token=registered.session_token, now=now)
        assert (
            await service.authenticate(session_token=registered.session_token, now=now)
            is None
        )
    finally:
        await _cleanup_user(email)


@pytest.mark.asyncio
async def test_http_selector_rejects_untrusted_organization_scope() -> None:
    await init_db()
    email = f"auth-{uuid.uuid4()}@example.test"
    reset_auth_wiring()
    service = get_auth_service()
    now = datetime.utcnow()
    try:
        registered = await service.register(
            email=email, password="correct-horse-battery", now=now
        )
        active_org_id = str(uuid.uuid4())
        foreign_org_id = str(uuid.uuid4())
        recovery_org_id = str(uuid.uuid4())
        async with AsyncSessionLocal() as session:
            session.add_all(
                [
                    OrganizationModel(id=active_org_id, name="Active team"),
                    OrganizationModel(id=recovery_org_id, name="Recovery team"),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    MembershipModel(
                        organization_id=active_org_id,
                        user_id=registered.user.id,
                        role="member",
                        status="active",
                    ),
                    MembershipModel(
                        organization_id=recovery_org_id,
                        user_id=registered.user.id,
                        role="member",
                        status="active",
                    ),
                ]
            )
            session.add(OrganizationModel(id=foreign_org_id, name="Foreign team"))
            await session.commit()

        cookies = {
            SESSION_COOKIE_NAME: registered.session_token,
            CSRF_COOKIE_NAME: registered.csrf_token,
        }
        headers = {
            CSRF_HEADER_NAME: registered.csrf_token,
            "X-Organization-ID": foreign_org_id,
        }
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            cookies=cookies,
        ) as client:
            selected = await client.put(
                "/api/v1/auth/session/organization",
                json={"organization_id": active_org_id},
                headers=headers,
            )
            rejected = await client.put(
                "/api/v1/auth/session/organization",
                json={"organization_id": foreign_org_id},
                headers=headers,
            )
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(MembershipModel)
                    .where(MembershipModel.organization_id == active_org_id)
                    .where(MembershipModel.user_id == registered.user.id)
                    .values(status="suspended")
                )
                await session.commit()
            recovered = await client.put(
                "/api/v1/auth/session/organization",
                json={"organization_id": recovery_org_id},
                headers=headers,
            )

        assert selected.status_code == 200
        assert selected.json()["organization_id"] == active_org_id
        assert rejected.status_code == 404
        assert recovered.status_code == 200
        assert recovered.json()["organization_id"] == recovery_org_id
    finally:
        reset_auth_wiring()
        await _cleanup_user(email)
