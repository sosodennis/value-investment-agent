from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.application.ports import AuditRepository
from src.audit.domain.entities import AuditEventDraft, AuditOutcome
from src.audit.infrastructure.repository import SqlAlchemyAuditRepository
from src.auth.application.errors import (
    InvalidMembershipTransitionError,
    MembershipInvariantError,
    MembershipNotFoundError,
    OrganizationMutationConflictError,
    OrganizationNotFoundError,
)
from src.auth.domain.entities import (
    MembershipRecord,
    MembershipRole,
    MembershipStatus,
    OrganizationMember,
    OrganizationMembership,
    OrganizationRecord,
    UserRecord,
)
from src.auth.domain.events import OrganizationLifecycleEventDraft
from src.auth.domain.membership_policy import is_allowed_membership_status_transition
from src.auth.infrastructure.models import (
    MembershipModel,
    OrganizationModel,
    UserModel,
)
from src.infrastructure.database import AsyncSessionLocal


class SqlAlchemyOrganizationLifecycleRepository:
    def __init__(self, *, audit_repository: AuditRepository | None = None) -> None:
        self._audit = audit_repository or SqlAlchemyAuditRepository()

    async def create_organization(
        self,
        *,
        owner_user_id: str,
        name: str,
        now: datetime,
        event: OrganizationLifecycleEventDraft,
    ) -> OrganizationMembership:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                user = await session.get(UserModel, owner_user_id)
                if user is None:
                    raise MembershipNotFoundError("owner user not found")
                organization = OrganizationModel(name=name, created_at=now)
                session.add(organization)
                await session.flush()
                membership = MembershipModel(
                    organization_id=organization.id,
                    user_id=owner_user_id,
                    role=MembershipRole.OWNER.value,
                    status=MembershipStatus.ACTIVE.value,
                    created_at=now,
                    updated_at=now,
                )
                session.add(membership)
                await session.flush()
                await self._add_event(
                    session,
                    organization_id=organization.id,
                    event=event,
                )
            return OrganizationMembership(
                organization=self._organization_record(organization),
                membership=self._membership_record(membership),
            )

    async def list_for_user(self, *, user_id: str) -> list[OrganizationMembership]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(OrganizationModel, MembershipModel)
                .join(
                    MembershipModel,
                    MembershipModel.organization_id == OrganizationModel.id,
                )
                .where(MembershipModel.user_id == user_id)
                .where(MembershipModel.status != MembershipStatus.REMOVED.value)
                .order_by(MembershipModel.created_at, MembershipModel.id)
            )
            rows = result.all()
        return [
            OrganizationMembership(
                organization=self._organization_record(organization),
                membership=self._membership_record(membership),
            )
            for organization, membership in rows
        ]

    async def get_organization(
        self, *, organization_id: str
    ) -> OrganizationRecord | None:
        async with AsyncSessionLocal() as session:
            organization = await session.get(OrganizationModel, organization_id)
        return self._organization_record(organization) if organization else None

    async def rename_organization(
        self,
        *,
        organization_id: str,
        name: str,
        actor_user_id: str,
        expected_actor: MembershipRecord,
        now: datetime,
        event: OrganizationLifecycleEventDraft,
    ) -> OrganizationRecord:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                organization = await session.scalar(
                    select(OrganizationModel)
                    .where(OrganizationModel.id == organization_id)
                    .with_for_update()
                )
                if organization is None:
                    raise OrganizationNotFoundError("organization not found")
                actor = await self._lock_membership(
                    session,
                    organization_id=organization_id,
                    user_id=actor_user_id,
                )
                self._assert_membership_snapshot(actor, expected_actor)
                organization.name = name
                await session.flush()
                await self._add_event(
                    session,
                    organization_id=organization_id,
                    event=event,
                )
            return self._organization_record(organization)

    async def list_members(self, *, organization_id: str) -> list[OrganizationMember]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserModel, MembershipModel)
                .join(MembershipModel, MembershipModel.user_id == UserModel.id)
                .where(MembershipModel.organization_id == organization_id)
                .order_by(MembershipModel.created_at, MembershipModel.id)
            )
            rows = result.all()
        return [
            OrganizationMember(
                user=self._user_record(user),
                membership=self._membership_record(membership),
            )
            for user, membership in rows
        ]

    async def get_member(
        self, *, organization_id: str, user_id: str
    ) -> OrganizationMember | None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserModel, MembershipModel)
                .join(MembershipModel, MembershipModel.user_id == UserModel.id)
                .where(MembershipModel.organization_id == organization_id)
                .where(MembershipModel.user_id == user_id)
            )
            row = result.first()
        if row is None:
            return None
        user, membership = row
        return OrganizationMember(
            user=self._user_record(user),
            membership=self._membership_record(membership),
        )

    async def change_membership(
        self,
        *,
        organization_id: str,
        user_id: str,
        role: str | None,
        status: str | None,
        expected_actor: MembershipRecord,
        expected_target: MembershipRecord,
        now: datetime,
        event: OrganizationLifecycleEventDraft,
    ) -> OrganizationMember:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                organization = await self._lock_organization(
                    session, organization_id=organization_id
                )
                actor = await self._lock_membership(
                    session,
                    organization_id=organization_id,
                    user_id=expected_actor.user_id,
                )
                membership = await self._lock_membership(
                    session, organization_id=organization_id, user_id=user_id
                )
                self._assert_membership_snapshot(actor, expected_actor)
                self._assert_membership_snapshot(membership, expected_target)
                user = await session.get(UserModel, user_id)
                if user is None:
                    raise MembershipNotFoundError("membership not found")
                await self._validate_mutation(
                    session=session,
                    organization=organization,
                    membership=membership,
                    role=role,
                    status=status,
                )
                if role is not None:
                    membership.role = role
                if status is not None:
                    membership.status = status
                membership.updated_at = now
                await session.flush()
                await self._add_event(
                    session,
                    organization_id=organization_id,
                    event=event,
                )
            return OrganizationMember(
                user=self._user_record(user),
                membership=self._membership_record(membership),
            )

    async def transfer_ownership(
        self,
        *,
        organization_id: str,
        current_owner_user_id: str,
        target_user_id: str,
        expected_current_owner: MembershipRecord,
        expected_target: MembershipRecord,
        now: datetime,
        event: OrganizationLifecycleEventDraft,
    ) -> OrganizationMember:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await self._lock_organization(session, organization_id=organization_id)
                source = await self._lock_membership(
                    session,
                    organization_id=organization_id,
                    user_id=current_owner_user_id,
                )
                target = await self._lock_membership(
                    session, organization_id=organization_id, user_id=target_user_id
                )
                self._assert_membership_snapshot(source, expected_current_owner)
                self._assert_membership_snapshot(target, expected_target)
                user = await session.get(UserModel, target_user_id)
                if MembershipRole(source.role) is not MembershipRole.OWNER:
                    raise MembershipInvariantError("current member is not an owner")
                if MembershipStatus(source.status) is not MembershipStatus.ACTIVE:
                    raise MembershipInvariantError("current owner is not active")
                if MembershipStatus(target.status) is not MembershipStatus.ACTIVE:
                    raise MembershipInvariantError("target member is not active")
                source.role = MembershipRole.MEMBER.value
                target.role = MembershipRole.OWNER.value
                source.updated_at = now
                target.updated_at = now
                await session.flush()
                await self._add_event(
                    session,
                    organization_id=organization_id,
                    event=event,
                )
            if user is None:
                raise MembershipNotFoundError("membership not found")
            return OrganizationMember(
                user=self._user_record(user),
                membership=self._membership_record(target),
            )

    async def _add_event(
        self,
        session: AsyncSession,
        *,
        organization_id: str,
        event: OrganizationLifecycleEventDraft,
    ) -> None:
        await self._audit.append_in_session(
            session,
            event=AuditEventDraft(
                organization_id=organization_id,
                actor_user_id=event.actor_user_id,
                action=event.event_type.value,
                outcome=AuditOutcome.SUCCESS,
                target_type="user" if event.target_user_id else None,
                target_id=event.target_user_id,
                payload=event.payload,
                occurred_at=event.occurred_at,
            ),
        )

    @staticmethod
    def _assert_membership_snapshot(
        actual: MembershipModel, expected: MembershipRecord
    ) -> None:
        if (
            actual.id != expected.id
            or actual.organization_id != expected.organization_id
            or actual.user_id != expected.user_id
            or actual.role != expected.role.value
            or actual.status != expected.status.value
        ):
            raise OrganizationMutationConflictError(
                "organization membership changed; retry the operation"
            )

    @staticmethod
    async def _lock_organization(
        session: AsyncSession, *, organization_id: str
    ) -> OrganizationModel:
        organization = await session.scalar(
            select(OrganizationModel)
            .where(OrganizationModel.id == organization_id)
            .with_for_update()
        )
        if organization is None:
            raise OrganizationNotFoundError("organization not found")
        return organization

    @staticmethod
    async def _lock_membership(
        session: AsyncSession, *, organization_id: str, user_id: str
    ) -> MembershipModel:
        membership = await session.scalar(
            select(MembershipModel)
            .where(MembershipModel.organization_id == organization_id)
            .where(MembershipModel.user_id == user_id)
            .with_for_update()
        )
        if membership is None:
            raise MembershipNotFoundError("membership not found")
        return membership

    @classmethod
    async def _active_owner_count(
        cls, session: AsyncSession, *, organization_id: str
    ) -> int:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(MembershipModel)
                .where(MembershipModel.organization_id == organization_id)
                .where(MembershipModel.role == MembershipRole.OWNER.value)
                .where(MembershipModel.status == MembershipStatus.ACTIVE.value)
            )
            or 0
        )

    @classmethod
    async def _validate_mutation(
        cls,
        *,
        session: AsyncSession,
        organization: OrganizationModel,
        membership: MembershipModel,
        role: str | None,
        status: str | None,
    ) -> None:
        if role is not None:
            try:
                requested_role = MembershipRole(role)
            except ValueError as exc:
                raise MembershipInvariantError("invalid membership role") from exc
            if requested_role is MembershipRole.OWNER:
                raise MembershipInvariantError(
                    "ownership transfer is a separate operation"
                )
            if (
                membership.role == MembershipRole.OWNER.value
                and requested_role is not MembershipRole.OWNER
                and membership.status == MembershipStatus.ACTIVE.value
                and await cls._active_owner_count(
                    session, organization_id=organization.id
                )
                <= 1
            ):
                raise MembershipInvariantError("the last active owner is protected")
        if status is not None:
            try:
                requested_status = MembershipStatus(status)
                current_status = MembershipStatus(membership.status)
            except ValueError as exc:
                raise InvalidMembershipTransitionError(
                    "invalid membership status"
                ) from exc
            if not is_allowed_membership_status_transition(
                current=current_status, requested=requested_status
            ):
                raise InvalidMembershipTransitionError(
                    "membership status transition is not allowed"
                )
            if (
                requested_status
                in {MembershipStatus.SUSPENDED, MembershipStatus.REMOVED}
                and membership.role == MembershipRole.OWNER.value
                and membership.status == MembershipStatus.ACTIVE.value
                and await cls._active_owner_count(
                    session, organization_id=organization.id
                )
                <= 1
            ):
                raise MembershipInvariantError("the last active owner is protected")

    @staticmethod
    def _organization_record(model: OrganizationModel) -> OrganizationRecord:
        return OrganizationRecord(
            id=model.id, name=model.name, created_at=model.created_at
        )

    @staticmethod
    def _user_record(model: UserModel) -> UserRecord:
        return UserRecord(
            id=model.id,
            email=model.email,
            password_hash=model.password_hash,
            created_at=model.created_at,
            display_name=model.display_name,
        )

    @staticmethod
    def _membership_record(model: MembershipModel) -> MembershipRecord:
        return MembershipRecord(
            id=model.id,
            organization_id=model.organization_id,
            user_id=model.user_id,
            role=MembershipRole(model.role),
            status=MembershipStatus(model.status),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
