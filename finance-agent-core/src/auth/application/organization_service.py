from __future__ import annotations

from datetime import datetime

from src.auth.application.authorization_service import AuthorizationService
from src.auth.application.errors import (
    InvalidMembershipTransitionError,
    MembershipInvariantError,
    MembershipNotFoundError,
    OrganizationNotFoundError,
)
from src.auth.application.ports import (
    OrganizationLifecycleRepository,
)
from src.auth.domain.authorization import (
    AuthorizationContext,
    AuthorizationResource,
    OrganizationPermission,
)
from src.auth.domain.entities import (
    AuthenticatedContext,
    MembershipRole,
    MembershipStatus,
    OrganizationMember,
    OrganizationMembership,
    OrganizationRecord,
)
from src.auth.domain.events import (
    OrganizationLifecycleEventDraft,
    OrganizationLifecycleEventType,
)
from src.auth.domain.membership_policy import (
    is_allowed_membership_status_transition,
    normalize_organization_name,
)


class OrganizationService:
    def __init__(
        self,
        *,
        repository: OrganizationLifecycleRepository,
        authorization: AuthorizationService,
    ) -> None:
        self._repository = repository
        self._authorization = authorization

    async def create_organization(
        self, *, context: AuthenticatedContext, name: str, now: datetime
    ) -> OrganizationMembership:
        self._require(
            context=context,
            permission=OrganizationPermission.ORGANIZATION_CREATE,
            resource=AuthorizationResource(),
        )
        normalized_name = normalize_organization_name(name)
        organization = await self._repository.create_organization(
            owner_user_id=context.user.id,
            name=normalized_name,
            now=now,
            event=OrganizationLifecycleEventDraft(
                event_type=OrganizationLifecycleEventType.ORGANIZATION_CREATED,
                actor_user_id=context.user.id,
                target_user_id=context.user.id,
                payload={"name": normalized_name},
                occurred_at=now,
            ),
        )
        return organization

    async def list_organizations(
        self, *, context: AuthenticatedContext
    ) -> list[OrganizationMembership]:
        if not context.user.id:
            raise MembershipNotFoundError("authenticated user is required")
        return await self._repository.list_for_user(user_id=context.user.id)

    async def get_organization(
        self, *, context: AuthenticatedContext, organization_id: str
    ) -> OrganizationRecord:
        self._require_organization(
            context=context,
            permission=OrganizationPermission.ORGANIZATION_READ,
            organization_id=organization_id,
        )
        organization = await self._repository.get_organization(
            organization_id=organization_id
        )
        if organization is None:
            raise OrganizationNotFoundError("organization not found")
        return organization

    async def rename_organization(
        self,
        *,
        context: AuthenticatedContext,
        organization_id: str,
        name: str,
        now: datetime,
    ) -> OrganizationRecord:
        self._require_organization(
            context=context,
            permission=OrganizationPermission.ORGANIZATION_UPDATE,
            organization_id=organization_id,
        )
        normalized_name = normalize_organization_name(name)
        organization = await self._repository.rename_organization(
            organization_id=organization_id,
            name=normalized_name,
            actor_user_id=context.user.id,
            expected_actor=context.membership,
            now=now,
            event=OrganizationLifecycleEventDraft(
                event_type=OrganizationLifecycleEventType.ORGANIZATION_RENAMED,
                actor_user_id=context.user.id,
                target_user_id=None,
                payload={"name": normalized_name},
                occurred_at=now,
            ),
        )
        return organization

    async def list_members(
        self, *, context: AuthenticatedContext, organization_id: str
    ) -> list[OrganizationMember]:
        self._require_organization(
            context=context,
            permission=OrganizationPermission.MEMBERSHIP_READ,
            organization_id=organization_id,
        )
        return await self._repository.list_members(organization_id=organization_id)

    async def change_role(
        self,
        *,
        context: AuthenticatedContext,
        organization_id: str,
        target_user_id: str,
        requested_role: MembershipRole,
        now: datetime,
    ) -> OrganizationMember:
        target, owner_count = await self._membership_facts(
            context=context,
            organization_id=organization_id,
            target_user_id=target_user_id,
        )
        self._require(
            context=context,
            permission=OrganizationPermission.MEMBERSHIP_ROLE_CHANGE,
            resource=AuthorizationResource(
                organization_id=organization_id,
                target_user_id=target_user_id,
                target_role=target.membership.role,
                requested_role=requested_role,
                owner_count=owner_count,
            ),
        )
        if target.membership.status is not MembershipStatus.ACTIVE:
            raise MembershipInvariantError("only an active member can change roles")
        if target.membership.role is requested_role:
            return target
        updated = await self._repository.change_membership(
            organization_id=organization_id,
            user_id=target_user_id,
            role=requested_role.value,
            status=None,
            expected_actor=context.membership,
            expected_target=target.membership,
            now=now,
            event=OrganizationLifecycleEventDraft(
                event_type=OrganizationLifecycleEventType.MEMBERSHIP_ROLE_CHANGED,
                actor_user_id=context.user.id,
                target_user_id=target_user_id,
                payload={
                    "from_role": target.membership.role.value,
                    "to_role": requested_role.value,
                },
                occurred_at=now,
            ),
        )
        return updated

    async def change_status(
        self,
        *,
        context: AuthenticatedContext,
        organization_id: str,
        target_user_id: str,
        requested_status: MembershipStatus,
        now: datetime,
    ) -> OrganizationMember:
        target, owner_count = await self._membership_facts(
            context=context,
            organization_id=organization_id,
            target_user_id=target_user_id,
        )
        if not is_allowed_membership_status_transition(
            current=target.membership.status, requested=requested_status
        ):
            raise InvalidMembershipTransitionError(
                "membership status transition is not allowed"
            )
        self._require(
            context=context,
            permission=OrganizationPermission.MEMBERSHIP_REMOVE,
            resource=AuthorizationResource(
                organization_id=organization_id,
                target_user_id=target_user_id,
                target_role=target.membership.role,
                owner_count=owner_count,
            ),
        )
        if target.membership.status is requested_status:
            return target
        updated = await self._repository.change_membership(
            organization_id=organization_id,
            user_id=target_user_id,
            role=None,
            status=requested_status.value,
            expected_actor=context.membership,
            expected_target=target.membership,
            now=now,
            event=OrganizationLifecycleEventDraft(
                event_type=OrganizationLifecycleEventType.MEMBERSHIP_STATUS_CHANGED,
                actor_user_id=context.user.id,
                target_user_id=target_user_id,
                payload={
                    "from_status": target.membership.status.value,
                    "to_status": requested_status.value,
                },
                occurred_at=now,
            ),
        )
        return updated

    async def transfer_ownership(
        self,
        *,
        context: AuthenticatedContext,
        organization_id: str,
        target_user_id: str,
        now: datetime,
    ) -> OrganizationMember:
        target, owner_count = await self._membership_facts(
            context=context,
            organization_id=organization_id,
            target_user_id=target_user_id,
        )
        self._require(
            context=context,
            permission=OrganizationPermission.MEMBERSHIP_OWNER_TRANSFER,
            resource=AuthorizationResource(
                organization_id=organization_id,
                target_user_id=target_user_id,
                target_role=target.membership.role,
                requested_role=MembershipRole.OWNER,
                owner_count=owner_count,
            ),
        )
        if target.membership.status is not MembershipStatus.ACTIVE:
            raise MembershipInvariantError(
                "only an active member can own an organization"
            )
        if target.membership.role is MembershipRole.OWNER:
            return target
        updated = await self._repository.transfer_ownership(
            organization_id=organization_id,
            current_owner_user_id=context.user.id,
            target_user_id=target_user_id,
            expected_current_owner=context.membership,
            expected_target=target.membership,
            now=now,
            event=OrganizationLifecycleEventDraft(
                event_type=OrganizationLifecycleEventType.OWNERSHIP_TRANSFERRED,
                actor_user_id=context.user.id,
                target_user_id=target_user_id,
                payload={"from_owner_user_id": context.user.id},
                occurred_at=now,
            ),
        )
        return updated

    async def leave_organization(
        self, *, context: AuthenticatedContext, organization_id: str, now: datetime
    ) -> OrganizationMember:
        target, owner_count = await self._membership_facts(
            context=context,
            organization_id=organization_id,
            target_user_id=context.user.id,
        )
        self._require(
            context=context,
            permission=OrganizationPermission.MEMBERSHIP_LEAVE,
            resource=AuthorizationResource(
                organization_id=organization_id,
                target_user_id=context.user.id,
                target_role=target.membership.role,
                owner_count=owner_count,
            ),
        )
        if target.membership.status is not MembershipStatus.ACTIVE:
            raise MembershipInvariantError("only an active member can leave")
        updated = await self._repository.change_membership(
            organization_id=organization_id,
            user_id=context.user.id,
            role=None,
            status=MembershipStatus.REMOVED.value,
            expected_actor=context.membership,
            expected_target=target.membership,
            now=now,
            event=OrganizationLifecycleEventDraft(
                event_type=OrganizationLifecycleEventType.MEMBERSHIP_STATUS_CHANGED,
                actor_user_id=context.user.id,
                target_user_id=context.user.id,
                payload={
                    "from_status": target.membership.status.value,
                    "to_status": "removed",
                },
                occurred_at=now,
            ),
        )
        return updated

    async def _membership_facts(
        self,
        *,
        context: AuthenticatedContext,
        organization_id: str,
        target_user_id: str,
    ) -> tuple[OrganizationMember, int]:
        self._require_organization(
            context=context,
            permission=OrganizationPermission.MEMBERSHIP_READ,
            organization_id=organization_id,
        )
        target = await self._repository.get_member(
            organization_id=organization_id, user_id=target_user_id
        )
        if target is None:
            raise MembershipNotFoundError("membership not found")
        members = await self._repository.list_members(organization_id=organization_id)
        owner_count = sum(
            member.membership.status is MembershipStatus.ACTIVE
            and member.membership.role is MembershipRole.OWNER
            for member in members
        )
        return target, owner_count

    def _require_organization(
        self,
        *,
        context: AuthenticatedContext,
        permission: OrganizationPermission,
        organization_id: str,
    ) -> None:
        self._require(
            context=context,
            permission=permission,
            resource=AuthorizationResource(organization_id=organization_id),
        )

    def _require(
        self,
        *,
        context: AuthenticatedContext,
        permission: OrganizationPermission,
        resource: AuthorizationResource,
    ) -> None:
        self._authorization.require(
            context=AuthorizationContext.from_authenticated_context(context),
            permission=permission,
            resource=resource,
        )
