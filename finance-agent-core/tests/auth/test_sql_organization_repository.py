from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from src.auth.application.authorization_service import AuthorizationService
from src.auth.application.errors import (
    AuthorizationDeniedError,
    MembershipInvariantError,
    OrganizationMutationConflictError,
)
from src.auth.application.organization_service import OrganizationService
from src.auth.application.service import AuthService, hash_secret
from src.auth.domain.entities import (
    AuthenticatedContext,
    MembershipRecord,
    MembershipRole,
    MembershipStatus,
    OrganizationMembership,
    RegistrationRecord,
    SessionRecord,
)
from src.auth.domain.events import (
    OrganizationLifecycleEventDraft,
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
from src.auth.infrastructure.passwords import Argon2PasswordHasher
from src.auth.infrastructure.repositories import (
    SqlAlchemyOrganizationRepository,
    SqlAlchemySessionRepository,
    SqlAlchemyUserRepository,
)
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
        email=owner_email,
        password_hash="hash",
        display_name="Owner One",
        display_name_normalized="owner one",
    )
    target = await users.create_with_default_organization(
        email=target_email,
        password_hash="hash",
        display_name="Target One",
        display_name_normalized="target one",
    )
    organization = await repository.create_organization(
        owner_user_id=owner.user.id,
        name="Alpha",
        now=now,
        event=OrganizationLifecycleEventDraft(
            event_type=OrganizationLifecycleEventType.ORGANIZATION_CREATED,
            actor_user_id=owner.user.id,
            target_user_id=owner.user.id,
            payload={"name": "Alpha"},
            occurred_at=now,
        ),
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

        target_member = await repository.get_member(
            organization_id=organization_id, user_id=target.user.id
        )
        assert target_member is not None
        owner_member = await repository.get_member(
            organization_id=organization_id, user_id=owner.user.id
        )
        assert owner_member is not None
        transfer_event = OrganizationLifecycleEventDraft(
            event_type=OrganizationLifecycleEventType.OWNERSHIP_TRANSFERRED,
            actor_user_id=owner.user.id,
            target_user_id=target.user.id,
            payload={"from_owner_user_id": owner.user.id},
            occurred_at=now,
        )

        results = await asyncio.gather(
            repository.transfer_ownership(
                organization_id=organization_id,
                current_owner_user_id=owner.user.id,
                target_user_id=target.user.id,
                expected_current_owner=owner_member.membership,
                expected_target=target_member.membership,
                now=now,
                event=transfer_event,
            ),
            repository.transfer_ownership(
                organization_id=organization_id,
                current_owner_user_id=owner.user.id,
                target_user_id=target.user.id,
                expected_current_owner=owner_member.membership,
                expected_target=target_member.membership,
                now=now,
                event=transfer_event,
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
        assert await session_count_events(organization_id=organization_id) == 2

        with pytest.raises(MembershipInvariantError):
            transferred_target = await repository.get_member(
                organization_id=organization_id, user_id=target.user.id
            )
            transferred_source = await repository.get_member(
                organization_id=organization_id, user_id=owner.user.id
            )
            assert transferred_target is not None
            assert transferred_source is not None
            await repository.change_membership(
                organization_id=organization_id,
                user_id=target.user.id,
                role=None,
                status=MembershipStatus.SUSPENDED.value,
                expected_actor=transferred_source.membership,
                expected_target=transferred_target.membership,
                now=now,
                event=OrganizationLifecycleEventDraft(
                    event_type=OrganizationLifecycleEventType.MEMBERSHIP_STATUS_CHANGED,
                    actor_user_id=owner.user.id,
                    target_user_id=target.user.id,
                    payload={"from_status": "active", "to_status": "suspended"},
                    occurred_at=now,
                ),
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


async def _create_organization_fixture() -> (
    tuple[
        SqlAlchemyUserRepository,
        SqlAlchemyOrganizationLifecycleRepository,
        RegistrationRecord,
        RegistrationRecord,
        OrganizationMembership,
        datetime,
    ]
):
    users = SqlAlchemyUserRepository()
    repository = SqlAlchemyOrganizationLifecycleRepository()
    now = datetime.utcnow()
    owner = await users.create_with_default_organization(
        email=f"owner-{uuid.uuid4()}@example.test",
        password_hash="hash",
        display_name="Owner Two",
        display_name_normalized="owner two",
    )
    target = await users.create_with_default_organization(
        email=f"target-{uuid.uuid4()}@example.test",
        password_hash="hash",
        display_name="Target Two",
        display_name_normalized="target two",
    )
    organization = await repository.create_organization(
        owner_user_id=owner.user.id,
        name="Acceptance organization",
        now=now,
        event=OrganizationLifecycleEventDraft(
            event_type=OrganizationLifecycleEventType.ORGANIZATION_CREATED,
            actor_user_id=owner.user.id,
            target_user_id=owner.user.id,
            payload={"name": "Acceptance organization"},
            occurred_at=now,
        ),
    )
    async with AsyncSessionLocal() as session:
        session.add(
            MembershipModel(
                organization_id=organization.organization.id,
                user_id=target.user.id,
                role=MembershipRole.MEMBER.value,
                status=MembershipStatus.ACTIVE.value,
            )
        )
        await session.commit()
    return users, repository, owner, target, organization, now


def _event(
    *,
    event_type: OrganizationLifecycleEventType,
    actor_user_id: str,
    target_user_id: str | None,
    payload: dict[str, str],
    occurred_at: datetime,
) -> OrganizationLifecycleEventDraft:
    return OrganizationLifecycleEventDraft(
        event_type=event_type,
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        payload=payload,
        occurred_at=occurred_at,
    )


async def _member_snapshots(
    repository: SqlAlchemyOrganizationLifecycleRepository,
    *,
    organization_id: str,
    owner_id: str,
    target_id: str,
) -> tuple[MembershipRecord, MembershipRecord]:
    owner = await repository.get_member(
        organization_id=organization_id, user_id=owner_id
    )
    target = await repository.get_member(
        organization_id=organization_id, user_id=target_id
    )
    assert owner is not None
    assert target is not None
    return owner.membership, target.membership


@pytest.mark.asyncio
async def test_concurrent_role_changes_revalidate_target_and_emit_one_event() -> None:
    await init_db()
    (
        users,
        repository,
        owner,
        target,
        organization,
        now,
    ) = await _create_organization_fixture()
    organization_id = organization.organization.id
    owner_membership, target_membership = await _member_snapshots(
        repository,
        organization_id=organization_id,
        owner_id=owner.user.id,
        target_id=target.user.id,
    )
    try:
        results = await asyncio.gather(
            repository.change_membership(
                organization_id=organization_id,
                user_id=target.user.id,
                role=MembershipRole.ADMIN.value,
                status=None,
                expected_actor=owner_membership,
                expected_target=target_membership,
                now=now,
                event=_event(
                    event_type=OrganizationLifecycleEventType.MEMBERSHIP_ROLE_CHANGED,
                    actor_user_id=owner.user.id,
                    target_user_id=target.user.id,
                    payload={"from_role": "member", "to_role": "admin"},
                    occurred_at=now,
                ),
            ),
            repository.change_membership(
                organization_id=organization_id,
                user_id=target.user.id,
                role=MembershipRole.ADMIN.value,
                status=None,
                expected_actor=owner_membership,
                expected_target=target_membership,
                now=now,
                event=_event(
                    event_type=OrganizationLifecycleEventType.MEMBERSHIP_ROLE_CHANGED,
                    actor_user_id=owner.user.id,
                    target_user_id=target.user.id,
                    payload={"from_role": "member", "to_role": "admin"},
                    occurred_at=now,
                ),
            ),
            return_exceptions=True,
        )
        assert sum(not isinstance(result, Exception) for result in results) == 1
        assert (
            sum(
                isinstance(result, OrganizationMutationConflictError)
                for result in results
            )
            == 1
        )
        assert await session_count_events(organization_id=organization_id) == 2
    finally:
        await _cleanup(
            user_ids={owner.user.id, target.user.id},
            organization_ids={
                owner.organization.id,
                target.organization.id,
                organization_id,
            },
        )


@pytest.mark.asyncio
async def test_concurrent_status_changes_revalidate_target_and_emit_one_event() -> None:
    await init_db()
    (
        users,
        repository,
        owner,
        target,
        organization,
        now,
    ) = await _create_organization_fixture()
    organization_id = organization.organization.id
    owner_membership, target_membership = await _member_snapshots(
        repository,
        organization_id=organization_id,
        owner_id=owner.user.id,
        target_id=target.user.id,
    )
    try:
        results = await asyncio.gather(
            repository.change_membership(
                organization_id=organization_id,
                user_id=target.user.id,
                role=None,
                status=MembershipStatus.SUSPENDED.value,
                expected_actor=owner_membership,
                expected_target=target_membership,
                now=now,
                event=_event(
                    event_type=OrganizationLifecycleEventType.MEMBERSHIP_STATUS_CHANGED,
                    actor_user_id=owner.user.id,
                    target_user_id=target.user.id,
                    payload={"from_status": "active", "to_status": "suspended"},
                    occurred_at=now,
                ),
            ),
            repository.change_membership(
                organization_id=organization_id,
                user_id=target.user.id,
                role=None,
                status=MembershipStatus.REMOVED.value,
                expected_actor=owner_membership,
                expected_target=target_membership,
                now=now,
                event=_event(
                    event_type=OrganizationLifecycleEventType.MEMBERSHIP_STATUS_CHANGED,
                    actor_user_id=owner.user.id,
                    target_user_id=target.user.id,
                    payload={"from_status": "active", "to_status": "removed"},
                    occurred_at=now,
                ),
            ),
            return_exceptions=True,
        )
        assert sum(not isinstance(result, Exception) for result in results) == 1
        assert (
            sum(
                isinstance(result, OrganizationMutationConflictError)
                for result in results
            )
            == 1
        )
        assert await session_count_events(organization_id=organization_id) == 2
    finally:
        await _cleanup(
            user_ids={owner.user.id, target.user.id},
            organization_ids={
                owner.organization.id,
                target.organization.id,
                organization_id,
            },
        )


@pytest.mark.asyncio
async def test_stale_actor_and_target_snapshots_are_rejected() -> None:
    await init_db()
    (
        users,
        repository,
        owner,
        target,
        organization,
        now,
    ) = await _create_organization_fixture()
    organization_id = organization.organization.id
    owner_membership, target_membership = await _member_snapshots(
        repository,
        organization_id=organization_id,
        owner_id=owner.user.id,
        target_id=target.user.id,
    )
    try:
        await repository.change_membership(
            organization_id=organization_id,
            user_id=target.user.id,
            role=MembershipRole.ADMIN.value,
            status=None,
            expected_actor=owner_membership,
            expected_target=target_membership,
            now=now,
            event=_event(
                event_type=OrganizationLifecycleEventType.MEMBERSHIP_ROLE_CHANGED,
                actor_user_id=owner.user.id,
                target_user_id=target.user.id,
                payload={"from_role": "member", "to_role": "admin"},
                occurred_at=now,
            ),
        )
        with pytest.raises(OrganizationMutationConflictError):
            await repository.change_membership(
                organization_id=organization_id,
                user_id=target.user.id,
                role=MembershipRole.MEMBER.value,
                status=None,
                expected_actor=owner_membership,
                expected_target=target_membership,
                now=now,
                event=_event(
                    event_type=OrganizationLifecycleEventType.MEMBERSHIP_ROLE_CHANGED,
                    actor_user_id=owner.user.id,
                    target_user_id=target.user.id,
                    payload={"from_role": "admin", "to_role": "member"},
                    occurred_at=now,
                ),
            )
        current_target = await repository.get_member(
            organization_id=organization_id, user_id=target.user.id
        )
        assert current_target is not None
        with pytest.raises(OrganizationMutationConflictError):
            await repository.change_membership(
                organization_id=organization_id,
                user_id=target.user.id,
                role=MembershipRole.MEMBER.value,
                status=None,
                expected_actor=replace_membership(
                    owner_membership, role=MembershipRole.MEMBER
                ),
                expected_target=current_target.membership,
                now=now,
                event=_event(
                    event_type=OrganizationLifecycleEventType.MEMBERSHIP_ROLE_CHANGED,
                    actor_user_id=owner.user.id,
                    target_user_id=target.user.id,
                    payload={"from_role": "admin", "to_role": "member"},
                    occurred_at=now,
                ),
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


@pytest.mark.asyncio
async def test_lifecycle_event_failure_rolls_back_the_membership_mutation() -> None:
    await init_db()
    users = SqlAlchemyUserRepository()
    repository = SqlAlchemyOrganizationLifecycleRepository()
    now = datetime.utcnow()
    owner = await users.create_with_default_organization(
        email=f"owner-{uuid.uuid4()}@example.test",
        password_hash="hash",
        display_name="Owner Three",
        display_name_normalized="owner three",
    )
    async with AsyncSessionLocal() as session:
        before = int(
            await session.scalar(select(func.count()).select_from(OrganizationModel))
            or 0
        )
    try:
        with pytest.raises(IntegrityError):
            await repository.create_organization(
                owner_user_id=owner.user.id,
                name="must rollback",
                now=now,
                event=_event(
                    event_type=OrganizationLifecycleEventType.ORGANIZATION_CREATED,
                    actor_user_id="missing-actor",
                    target_user_id=owner.user.id,
                    payload={"name": "must rollback"},
                    occurred_at=now,
                ),
            )
        async with AsyncSessionLocal() as session:
            after = int(
                await session.scalar(
                    select(func.count()).select_from(OrganizationModel)
                )
                or 0
            )
        assert after == before
    finally:
        await _cleanup(
            user_ids={owner.user.id},
            organization_ids={owner.organization.id},
        )


@pytest.mark.asyncio
async def test_membership_event_failure_rolls_back_the_membership_mutation() -> None:
    await init_db()
    (
        users,
        repository,
        owner,
        target,
        organization,
        now,
    ) = await _create_organization_fixture()
    organization_id = organization.organization.id
    owner_membership, target_membership = await _member_snapshots(
        repository,
        organization_id=organization_id,
        owner_id=owner.user.id,
        target_id=target.user.id,
    )
    try:
        with pytest.raises(IntegrityError):
            await repository.change_membership(
                organization_id=organization_id,
                user_id=target.user.id,
                role=MembershipRole.ADMIN.value,
                status=None,
                expected_actor=owner_membership,
                expected_target=target_membership,
                now=now,
                event=_event(
                    event_type=OrganizationLifecycleEventType.MEMBERSHIP_ROLE_CHANGED,
                    actor_user_id="missing-actor",
                    target_user_id=target.user.id,
                    payload={"from_role": "member", "to_role": "admin"},
                    occurred_at=now,
                ),
            )
        current = await repository.get_member(
            organization_id=organization_id, user_id=target.user.id
        )
        assert current is not None
        assert current.membership.role is MembershipRole.MEMBER
        assert await session_count_events(organization_id=organization_id) == 1
    finally:
        await _cleanup(
            user_ids={owner.user.id, target.user.id},
            organization_ids={
                owner.organization.id,
                target.organization.id,
                organization_id,
            },
        )


def replace_membership(
    membership: MembershipRecord, *, role: MembershipRole
) -> MembershipRecord:
    return MembershipRecord(
        id=membership.id,
        organization_id=membership.organization_id,
        user_id=membership.user_id,
        role=role,
        status=membership.status,
        created_at=membership.created_at,
        updated_at=membership.updated_at,
    )


@pytest.mark.asyncio
async def test_active_session_is_rejected_after_suspension_and_removal() -> None:
    await init_db()
    (
        users,
        repository,
        owner,
        target,
        organization,
        now,
    ) = await _create_organization_fixture()
    organization_id = organization.organization.id
    session_repository = SqlAlchemySessionRepository()
    auth = AuthService(
        users=users,
        organizations=SqlAlchemyOrganizationRepository(),
        sessions=session_repository,
        password_hasher=Argon2PasswordHasher(),
    )
    token = f"session-{uuid.uuid4()}"
    await session_repository.create(
        user_id=target.user.id,
        active_organization_id=organization_id,
        token_hash=hash_secret(token),
        csrf_token_hash=hash_secret("csrf"),
        expires_at=now.replace(year=now.year + 1),
    )
    owner_membership, target_membership = await _member_snapshots(
        repository,
        organization_id=organization_id,
        owner_id=owner.user.id,
        target_id=target.user.id,
    )
    try:
        assert await auth.authenticate(session_token=token, now=now) is not None
        await repository.change_membership(
            organization_id=organization_id,
            user_id=target.user.id,
            role=None,
            status=MembershipStatus.SUSPENDED.value,
            expected_actor=owner_membership,
            expected_target=target_membership,
            now=now,
            event=_event(
                event_type=OrganizationLifecycleEventType.MEMBERSHIP_STATUS_CHANGED,
                actor_user_id=owner.user.id,
                target_user_id=target.user.id,
                payload={"from_status": "active", "to_status": "suspended"},
                occurred_at=now,
            ),
        )
        assert await auth.authenticate(session_token=token, now=now) is None

        owner_membership, target_membership = await _member_snapshots(
            repository,
            organization_id=organization_id,
            owner_id=owner.user.id,
            target_id=target.user.id,
        )
        await repository.change_membership(
            organization_id=organization_id,
            user_id=target.user.id,
            role=None,
            status=MembershipStatus.ACTIVE.value,
            expected_actor=owner_membership,
            expected_target=target_membership,
            now=now,
            event=_event(
                event_type=OrganizationLifecycleEventType.MEMBERSHIP_STATUS_CHANGED,
                actor_user_id=owner.user.id,
                target_user_id=target.user.id,
                payload={"from_status": "suspended", "to_status": "active"},
                occurred_at=now,
            ),
        )
        assert await auth.authenticate(session_token=token, now=now) is not None

        owner_membership, target_membership = await _member_snapshots(
            repository,
            organization_id=organization_id,
            owner_id=owner.user.id,
            target_id=target.user.id,
        )
        await repository.change_membership(
            organization_id=organization_id,
            user_id=target.user.id,
            role=None,
            status=MembershipStatus.REMOVED.value,
            expected_actor=owner_membership,
            expected_target=target_membership,
            now=now,
            event=_event(
                event_type=OrganizationLifecycleEventType.MEMBERSHIP_STATUS_CHANGED,
                actor_user_id=owner.user.id,
                target_user_id=target.user.id,
                payload={"from_status": "active", "to_status": "removed"},
                occurred_at=now,
            ),
        )
        assert await auth.authenticate(session_token=token, now=now) is None
    finally:
        await _cleanup(
            user_ids={owner.user.id, target.user.id},
            organization_ids={
                owner.organization.id,
                target.organization.id,
                organization_id,
            },
        )


@pytest.mark.asyncio
async def test_organization_service_cannot_mutate_a_member_in_another_organization() -> (
    None
):
    await init_db()
    users = SqlAlchemyUserRepository()
    repository = SqlAlchemyOrganizationLifecycleRepository()
    now = datetime.utcnow()
    first = await users.create_with_default_organization(
        email=f"first-{uuid.uuid4()}@example.test",
        password_hash="hash",
        display_name="First User",
        display_name_normalized="first user",
    )
    second = await users.create_with_default_organization(
        email=f"second-{uuid.uuid4()}@example.test",
        password_hash="hash",
        display_name="Second User",
        display_name_normalized="second user",
    )
    organization = await repository.create_organization(
        owner_user_id=first.user.id,
        name="First organization",
        now=now,
        event=_event(
            event_type=OrganizationLifecycleEventType.ORGANIZATION_CREATED,
            actor_user_id=first.user.id,
            target_user_id=first.user.id,
            payload={"name": "First organization"},
            occurred_at=now,
        ),
    )
    context = AuthenticatedContext(
        user=first.user,
        session=SessionRecord(
            id=f"session-{uuid.uuid4()}",
            user_id=first.user.id,
            active_organization_id=organization.organization.id,
            token_hash="token",
            csrf_token_hash="csrf",
            expires_at=now.replace(year=now.year + 1),
            revoked_at=None,
            created_at=now,
        ),
        membership=organization.membership,
    )
    service = OrganizationService(
        repository=repository,
        authorization=AuthorizationService(),
    )
    try:
        with pytest.raises(AuthorizationDeniedError):
            await service.change_role(
                context=context,
                organization_id=second.organization.id,
                target_user_id=second.user.id,
                requested_role=MembershipRole.ADMIN,
                now=now,
            )
        second_member = await repository.get_member(
            organization_id=second.organization.id, user_id=second.user.id
        )
        assert second_member is not None
        assert second_member.membership.role is MembershipRole.OWNER
    finally:
        await _cleanup(
            user_ids={first.user.id, second.user.id},
            organization_ids={
                first.organization.id,
                second.organization.id,
                organization.organization.id,
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
