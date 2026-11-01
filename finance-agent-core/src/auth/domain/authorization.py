from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.auth.domain.entities import (
    AuthenticatedActorContext,
    AuthenticatedContext,
    MembershipRole,
    MembershipStatus,
)


class OrganizationPermission(str, Enum):
    ORGANIZATION_CREATE = "organization.create"
    ORGANIZATION_READ = "organization.read"
    ORGANIZATION_UPDATE = "organization.update"
    ORGANIZATION_DELETE = "organization.delete"
    ORGANIZATION_ARCHIVE = "organization.archive"
    MEMBERSHIP_READ = "membership.read"
    MEMBERSHIP_REMOVE = "membership.remove"
    MEMBERSHIP_LEAVE = "membership.leave"
    MEMBERSHIP_ROLE_CHANGE = "membership.role.change"
    MEMBERSHIP_OWNER_TRANSFER = "membership.owner.transfer"
    INVITATION_CREATE = "invitation.create"
    INVITATION_READ = "invitation.read"
    INVITATION_REVOKE = "invitation.revoke"
    NOTIFICATION_INBOX_READ = "notification.inbox.read"
    NOTIFICATION_INBOX_MUTATE = "notification.inbox.mutate"
    DIRECTORY_SEARCH = "directory.search"
    PROVIDER_CONFIG_READ = "provider.config.read"
    PROVIDER_CONFIG_WRITE = "provider.config.write"
    ORGANIZATION_AUDIT_READ = "organization.audit.read"


class AuthorizationFailureCode(str, Enum):
    AUTHENTICATION_REQUIRED = "authentication_required"
    ORGANIZATION_CONTEXT_REQUIRED = "organization_context_required"
    RESOURCE_NOT_FOUND = "resource_not_found"
    PERMISSION_DENIED = "permission_denied"
    INVALID_RESOURCE_CONTEXT = "invalid_resource_context"
    LAST_OWNER_PROTECTED = "last_owner_protected"
    SELF_REMOVAL_NOT_ALLOWED = "self_removal_not_allowed"
    ROLE_TRANSITION_NOT_ALLOWED = "role_transition_not_allowed"


@dataclass(frozen=True, slots=True)
class AuthorizationContext:
    actor_user_id: str
    organization_id: str | None
    membership_id: str | None
    role: MembershipRole | None
    membership_status: MembershipStatus | None

    @classmethod
    def from_authenticated_context(
        cls, context: AuthenticatedContext
    ) -> AuthorizationContext:
        return cls(
            actor_user_id=context.user.id,
            organization_id=context.membership.organization_id,
            membership_id=context.membership.id,
            role=context.membership.role,
            membership_status=context.membership.status,
        )

    @classmethod
    def from_actor_context(
        cls, context: AuthenticatedActorContext
    ) -> AuthorizationContext:
        return cls(
            actor_user_id=context.user.id,
            organization_id=None,
            membership_id=None,
            role=None,
            membership_status=None,
        )

    @property
    def has_active_membership(self) -> bool:
        return (
            self.organization_id is not None
            and self.role is not None
            and self.membership_status is MembershipStatus.ACTIVE
        )


@dataclass(frozen=True, slots=True)
class AuthorizationResource:
    organization_id: str | None = None
    target_user_id: str | None = None
    target_role: MembershipRole | None = None
    requested_role: MembershipRole | None = None
    owner_count: int | None = None
    recipient_user_id: str | None = None


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    failure_code: AuthorizationFailureCode | None = None

    @classmethod
    def allow(cls) -> PolicyDecision:
        return cls(allowed=True)

    @classmethod
    def deny(cls, code: AuthorizationFailureCode) -> PolicyDecision:
        return cls(allowed=False, failure_code=code)


ROLE_PERMISSION_MATRIX: dict[MembershipRole, frozenset[OrganizationPermission]] = {
    MembershipRole.OWNER: frozenset(OrganizationPermission),
    MembershipRole.ADMIN: frozenset(
        {
            OrganizationPermission.ORGANIZATION_CREATE,
            OrganizationPermission.ORGANIZATION_READ,
            OrganizationPermission.ORGANIZATION_UPDATE,
            OrganizationPermission.MEMBERSHIP_READ,
            OrganizationPermission.MEMBERSHIP_REMOVE,
            OrganizationPermission.MEMBERSHIP_LEAVE,
            OrganizationPermission.MEMBERSHIP_ROLE_CHANGE,
            OrganizationPermission.INVITATION_CREATE,
            OrganizationPermission.INVITATION_READ,
            OrganizationPermission.INVITATION_REVOKE,
            OrganizationPermission.NOTIFICATION_INBOX_READ,
            OrganizationPermission.NOTIFICATION_INBOX_MUTATE,
            OrganizationPermission.DIRECTORY_SEARCH,
            OrganizationPermission.PROVIDER_CONFIG_READ,
            OrganizationPermission.PROVIDER_CONFIG_WRITE,
            OrganizationPermission.ORGANIZATION_AUDIT_READ,
        }
    ),
    MembershipRole.MEMBER: frozenset(
        {
            OrganizationPermission.ORGANIZATION_CREATE,
            OrganizationPermission.ORGANIZATION_READ,
            OrganizationPermission.MEMBERSHIP_READ,
            OrganizationPermission.MEMBERSHIP_LEAVE,
            OrganizationPermission.NOTIFICATION_INBOX_READ,
            OrganizationPermission.NOTIFICATION_INBOX_MUTATE,
            OrganizationPermission.DIRECTORY_SEARCH,
            OrganizationPermission.PROVIDER_CONFIG_READ,
        }
    ),
}

_RECIPIENT_ONLY_PERMISSIONS = frozenset(
    {
        OrganizationPermission.NOTIFICATION_INBOX_READ,
        OrganizationPermission.NOTIFICATION_INBOX_MUTATE,
    }
)


class OrganizationAuthorizationPolicy:
    """Pure organization authorization rules.

    Resource existence and membership records are loaded by the owning
    application service. This policy only evaluates typed context and the
    relationship/resource facts supplied by that service.
    """

    @staticmethod
    def evaluate(
        *,
        context: AuthorizationContext,
        permission: OrganizationPermission,
        resource: AuthorizationResource | None = None,
    ) -> PolicyDecision:
        resource = resource or AuthorizationResource()
        if not context.actor_user_id:
            return PolicyDecision.deny(AuthorizationFailureCode.AUTHENTICATION_REQUIRED)

        if permission is OrganizationPermission.ORGANIZATION_CREATE:
            if resource.organization_id is not None:
                return PolicyDecision.deny(
                    AuthorizationFailureCode.INVALID_RESOURCE_CONTEXT
                )
            return PolicyDecision.allow()

        if permission in _RECIPIENT_ONLY_PERMISSIONS:
            return OrganizationAuthorizationPolicy._recipient_decision(
                context=context, resource=resource
            )

        if permission is OrganizationPermission.INVITATION_READ:
            if resource.recipient_user_id == context.actor_user_id:
                return PolicyDecision.allow()

        if not context.has_active_membership:
            return PolicyDecision.deny(
                AuthorizationFailureCode.ORGANIZATION_CONTEXT_REQUIRED
            )
        if resource.organization_id is None:
            return PolicyDecision.deny(
                AuthorizationFailureCode.INVALID_RESOURCE_CONTEXT
            )
        if resource.organization_id != context.organization_id:
            return PolicyDecision.deny(AuthorizationFailureCode.RESOURCE_NOT_FOUND)

        if permission not in ROLE_PERMISSION_MATRIX[context.role]:
            return PolicyDecision.deny(AuthorizationFailureCode.PERMISSION_DENIED)

        return OrganizationAuthorizationPolicy._relationship_decision(
            context=context, permission=permission, resource=resource
        )

    @staticmethod
    def _recipient_decision(
        *, context: AuthorizationContext, resource: AuthorizationResource
    ) -> PolicyDecision:
        if resource.recipient_user_id is None:
            return PolicyDecision.deny(
                AuthorizationFailureCode.INVALID_RESOURCE_CONTEXT
            )
        if resource.recipient_user_id != context.actor_user_id:
            return PolicyDecision.deny(AuthorizationFailureCode.RESOURCE_NOT_FOUND)
        return PolicyDecision.allow()

    @staticmethod
    def _relationship_decision(
        *,
        context: AuthorizationContext,
        permission: OrganizationPermission,
        resource: AuthorizationResource,
    ) -> PolicyDecision:
        if permission is OrganizationPermission.MEMBERSHIP_REMOVE:
            if resource.target_user_id is None:
                return PolicyDecision.deny(
                    AuthorizationFailureCode.INVALID_RESOURCE_CONTEXT
                )
            if resource.target_user_id == context.actor_user_id:
                return PolicyDecision.deny(
                    AuthorizationFailureCode.SELF_REMOVAL_NOT_ALLOWED
                )
            if resource.target_role is MembershipRole.OWNER:
                if resource.owner_count is None:
                    return PolicyDecision.deny(
                        AuthorizationFailureCode.INVALID_RESOURCE_CONTEXT
                    )
                if resource.owner_count <= 1:
                    return PolicyDecision.deny(
                        AuthorizationFailureCode.LAST_OWNER_PROTECTED
                    )

        if permission is OrganizationPermission.MEMBERSHIP_LEAVE:
            if resource.target_user_id != context.actor_user_id:
                return PolicyDecision.deny(
                    AuthorizationFailureCode.INVALID_RESOURCE_CONTEXT
                )
            if context.role is MembershipRole.OWNER:
                if resource.owner_count is None:
                    return PolicyDecision.deny(
                        AuthorizationFailureCode.INVALID_RESOURCE_CONTEXT
                    )
                if resource.owner_count <= 1:
                    return PolicyDecision.deny(
                        AuthorizationFailureCode.LAST_OWNER_PROTECTED
                    )
            return PolicyDecision.allow()

        if permission is OrganizationPermission.MEMBERSHIP_ROLE_CHANGE:
            if resource.target_user_id is None or resource.requested_role is None:
                return PolicyDecision.deny(
                    AuthorizationFailureCode.INVALID_RESOURCE_CONTEXT
                )
            if resource.requested_role is MembershipRole.OWNER:
                return PolicyDecision.deny(
                    AuthorizationFailureCode.ROLE_TRANSITION_NOT_ALLOWED
                )
            if (
                context.role is MembershipRole.ADMIN
                and resource.target_role is MembershipRole.OWNER
            ):
                return PolicyDecision.deny(
                    AuthorizationFailureCode.ROLE_TRANSITION_NOT_ALLOWED
                )
            if (
                context.role is MembershipRole.ADMIN
                and resource.requested_role is MembershipRole.ADMIN
            ):
                return PolicyDecision.deny(
                    AuthorizationFailureCode.ROLE_TRANSITION_NOT_ALLOWED
                )
            if resource.target_role is MembershipRole.OWNER:
                if resource.owner_count is None:
                    return PolicyDecision.deny(
                        AuthorizationFailureCode.INVALID_RESOURCE_CONTEXT
                    )
                if resource.owner_count <= 1:
                    return PolicyDecision.deny(
                        AuthorizationFailureCode.LAST_OWNER_PROTECTED
                    )
            if (
                resource.target_user_id == context.actor_user_id
                and context.role is MembershipRole.OWNER
            ):
                return PolicyDecision.deny(
                    AuthorizationFailureCode.SELF_REMOVAL_NOT_ALLOWED
                )

        if permission is OrganizationPermission.MEMBERSHIP_OWNER_TRANSFER:
            if (
                resource.target_user_id is None
                or resource.target_user_id == context.actor_user_id
                or resource.requested_role is not MembershipRole.OWNER
            ):
                return PolicyDecision.deny(
                    AuthorizationFailureCode.ROLE_TRANSITION_NOT_ALLOWED
                )

        if permission is OrganizationPermission.INVITATION_CREATE:
            if resource.requested_role is None:
                return PolicyDecision.deny(
                    AuthorizationFailureCode.INVALID_RESOURCE_CONTEXT
                )
            if resource.requested_role is MembershipRole.OWNER:
                return PolicyDecision.deny(
                    AuthorizationFailureCode.ROLE_TRANSITION_NOT_ALLOWED
                )
            if (
                context.role is MembershipRole.ADMIN
                and resource.requested_role is MembershipRole.ADMIN
            ):
                return PolicyDecision.deny(
                    AuthorizationFailureCode.ROLE_TRANSITION_NOT_ALLOWED
                )

        return PolicyDecision.allow()
