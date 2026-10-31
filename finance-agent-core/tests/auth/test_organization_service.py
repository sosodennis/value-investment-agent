from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from src.auth.application.authorization_service import AuthorizationService
from src.auth.application.errors import (
    AuthorizationDeniedError,
    InvalidMembershipTransitionError,
)
from src.auth.application.organization_service import OrganizationService
from src.auth.domain.entities import (
    AuthenticatedContext,
    MembershipRecord,
    MembershipRole,
    MembershipStatus,
    OrganizationMember,
    OrganizationMembership,
    OrganizationRecord,
    SessionRecord,
    UserRecord,
)
from src.auth.domain.events import OrganizationLifecycleEvent


class MemoryOrganizationRepository:
    def __init__(self, *, actor: UserRecord) -> None:
        now = actor.created_at
        organization = OrganizationRecord(
            id="organization-a", name="Alpha", created_at=now
        )
        owner = MembershipRecord(
            id="membership-owner",
            organization_id=organization.id,
            user_id=actor.id,
            role=MembershipRole.OWNER,
            status=MembershipStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        self.organizations = {organization.id: organization}
        self.members: dict[tuple[str, str], OrganizationMember] = {
            (organization.id, actor.id): OrganizationMember(
                user=actor, membership=owner
            )
        }

    async def create_organization(
        self, *, owner_user_id: str, name: str, now: datetime
    ) -> OrganizationMembership:
        user = next(
            member.user
            for member in self.members.values()
            if member.user.id == owner_user_id
        )
        organization = OrganizationRecord(
            id=f"organization-{len(self.organizations) + 1}",
            name=name,
            created_at=now,
        )
        membership = MembershipRecord(
            id=f"membership-{len(self.members) + 1}",
            organization_id=organization.id,
            user_id=user.id,
            role=MembershipRole.OWNER,
            status=MembershipStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        self.organizations[organization.id] = organization
        self.members[(organization.id, user.id)] = OrganizationMember(
            user=user, membership=membership
        )
        return OrganizationMembership(organization=organization, membership=membership)

    async def list_for_user(self, *, user_id: str) -> list[OrganizationMembership]:
        return [
            OrganizationMembership(
                organization=self.organizations[member.membership.organization_id],
                membership=member.membership,
            )
            for member in self.members.values()
            if member.user.id == user_id
            and member.membership.status is not MembershipStatus.REMOVED
        ]

    async def get_organization(
        self, *, organization_id: str
    ) -> OrganizationRecord | None:
        return self.organizations.get(organization_id)

    async def rename_organization(
        self, *, organization_id: str, name: str, now: datetime
    ) -> OrganizationRecord:
        organization = replace(self.organizations[organization_id], name=name)
        self.organizations[organization_id] = organization
        return organization

    async def list_members(self, *, organization_id: str) -> list[OrganizationMember]:
        return [
            member
            for (current_organization_id, _), member in self.members.items()
            if current_organization_id == organization_id
        ]

    async def get_member(
        self, *, organization_id: str, user_id: str
    ) -> OrganizationMember | None:
        return self.members.get((organization_id, user_id))

    async def change_membership(
        self,
        *,
        organization_id: str,
        user_id: str,
        role: str | None,
        status: str | None,
        now: datetime,
    ) -> OrganizationMember:
        current = self.members[(organization_id, user_id)]
        membership = current.membership
        if role is not None:
            membership = replace(membership, role=MembershipRole(role))
        if status is not None:
            membership = replace(membership, status=MembershipStatus(status))
        membership = replace(membership, updated_at=now)
        updated = OrganizationMember(user=current.user, membership=membership)
        self.members[(organization_id, user_id)] = updated
        return updated

    async def transfer_ownership(
        self,
        *,
        organization_id: str,
        current_owner_user_id: str,
        target_user_id: str,
        now: datetime,
    ) -> OrganizationMember:
        source = self.members[(organization_id, current_owner_user_id)]
        target = self.members[(organization_id, target_user_id)]
        self.members[(organization_id, current_owner_user_id)] = OrganizationMember(
            user=source.user,
            membership=replace(
                source.membership,
                role=MembershipRole.MEMBER,
                updated_at=now,
            ),
        )
        updated = OrganizationMember(
            user=target.user,
            membership=replace(
                target.membership,
                role=MembershipRole.OWNER,
                updated_at=now,
            ),
        )
        self.members[(organization_id, target_user_id)] = updated
        return updated

    async def append_event(self, event: OrganizationLifecycleEvent) -> None:
        self.events.append(event)

    events: list[OrganizationLifecycleEvent] = []


class MemoryEvents:
    def __init__(self) -> None:
        self.events: list[OrganizationLifecycleEvent] = []

    async def publish(self, event: OrganizationLifecycleEvent) -> None:
        self.events.append(event)


def _context(
    *,
    user_id: str = "user-owner",
    role: MembershipRole = MembershipRole.OWNER,
    organization_id: str = "organization-a",
) -> AuthenticatedContext:
    now = datetime(2026, 1, 1)
    user = UserRecord(
        id=user_id,
        email=f"{user_id}@example.test",
        password_hash="unused",
        created_at=now,
    )
    membership = MembershipRecord(
        id=f"membership-{user_id}",
        organization_id=organization_id,
        user_id=user_id,
        role=role,
        status=MembershipStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    session = SessionRecord(
        id=f"session-{user_id}",
        user_id=user_id,
        active_organization_id=organization_id,
        token_hash="token",
        csrf_token_hash="csrf",
        expires_at=now + timedelta(hours=1),
        revoked_at=None,
        created_at=now,
    )
    return AuthenticatedContext(user=user, session=session, membership=membership)


def _service(
    context: AuthenticatedContext,
) -> tuple[OrganizationService, MemoryOrganizationRepository, MemoryEvents]:
    repository = MemoryOrganizationRepository(actor=context.user)
    events = MemoryEvents()
    return (
        OrganizationService(
            repository=repository,
            authorization=AuthorizationService(),
            events=events,
        ),
        repository,
        events,
    )


@pytest.mark.asyncio
async def test_create_rename_list_and_emit_lifecycle_events() -> None:
    context = _context()
    service, repository, events = _service(context)
    now = datetime(2026, 1, 2)

    created = await service.create_organization(context=context, name=" Beta ", now=now)
    renamed = await service.rename_organization(
        context=context,
        organization_id="organization-a",
        name="Beta team",
        now=now,
    )
    organizations = await service.list_organizations(context=context)

    assert renamed.name == "Beta team"
    assert {item.organization.id for item in organizations} == {
        "organization-a",
        created.organization.id,
    }
    assert [event.event_type.value for event in events.events] == [
        "organization.created",
        "organization.renamed",
    ]
    assert repository.organizations["organization-a"].name == "Beta team"


@pytest.mark.asyncio
async def test_member_administration_enforces_roles_status_and_last_owner() -> None:
    context = _context()
    service, repository, _events = _service(context)
    member_user = UserRecord(
        id="user-member",
        email="member@example.test",
        password_hash="unused",
        created_at=context.user.created_at,
    )
    repository.members[("organization-a", member_user.id)] = OrganizationMember(
        user=member_user,
        membership=MembershipRecord(
            id="membership-member",
            organization_id="organization-a",
            user_id=member_user.id,
            role=MembershipRole.MEMBER,
            status=MembershipStatus.ACTIVE,
            created_at=context.user.created_at,
            updated_at=context.user.created_at,
        ),
    )

    promoted = await service.change_role(
        context=context,
        organization_id="organization-a",
        target_user_id=member_user.id,
        requested_role=MembershipRole.ADMIN,
        now=datetime(2026, 1, 2),
    )
    suspended = await service.change_status(
        context=context,
        organization_id="organization-a",
        target_user_id=member_user.id,
        requested_status=MembershipStatus.SUSPENDED,
        now=datetime(2026, 1, 3),
    )
    reactivated = await service.change_status(
        context=context,
        organization_id="organization-a",
        target_user_id=member_user.id,
        requested_status=MembershipStatus.ACTIVE,
        now=datetime(2026, 1, 4),
    )
    removed = await service.change_status(
        context=context,
        organization_id="organization-a",
        target_user_id=member_user.id,
        requested_status=MembershipStatus.REMOVED,
        now=datetime(2026, 1, 5),
    )

    assert promoted.membership.role is MembershipRole.ADMIN
    assert suspended.membership.status is MembershipStatus.SUSPENDED
    assert reactivated.membership.status is MembershipStatus.ACTIVE
    assert removed.membership.status is MembershipStatus.REMOVED
    with pytest.raises(InvalidMembershipTransitionError):
        await service.change_status(
            context=context,
            organization_id="organization-a",
            target_user_id=member_user.id,
            requested_status=MembershipStatus.ACTIVE,
            now=datetime(2026, 1, 6),
        )

    with pytest.raises(AuthorizationDeniedError):
        await service.change_status(
            context=context,
            organization_id="organization-a",
            target_user_id=context.user.id,
            requested_status=MembershipStatus.SUSPENDED,
            now=datetime(2026, 1, 6),
        )


@pytest.mark.asyncio
async def test_member_cannot_mutate_and_owner_transfer_is_atomic_in_domain_port() -> (
    None
):
    owner = _context()
    service, repository, _events = _service(owner)
    member = UserRecord(
        id="user-target",
        email="target@example.test",
        password_hash="unused",
        created_at=owner.user.created_at,
    )
    repository.members[("organization-a", member.id)] = OrganizationMember(
        user=member,
        membership=MembershipRecord(
            id="membership-target",
            organization_id="organization-a",
            user_id=member.id,
            role=MembershipRole.MEMBER,
            status=MembershipStatus.ACTIVE,
            created_at=owner.user.created_at,
            updated_at=owner.user.created_at,
        ),
    )
    transferred = await service.transfer_ownership(
        context=owner,
        organization_id="organization-a",
        target_user_id=member.id,
        now=datetime(2026, 1, 2),
    )
    assert transferred.membership.role is MembershipRole.OWNER
    assert (
        repository.members[("organization-a", owner.user.id)].membership.role
        is MembershipRole.MEMBER
    )

    with pytest.raises(AuthorizationDeniedError):
        await service.change_role(
            context=_context(role=MembershipRole.MEMBER),
            organization_id="organization-a",
            target_user_id=member.id,
            requested_role=MembershipRole.ADMIN,
            now=datetime(2026, 1, 3),
        )
