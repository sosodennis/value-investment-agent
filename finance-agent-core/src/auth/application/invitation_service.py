from __future__ import annotations

from datetime import datetime, timedelta

from src.auth.application.authorization_service import AuthorizationService
from src.auth.application.invitation_errors import InvitationValidationError
from src.auth.application.invitation_ports import InvitationRepository
from src.auth.domain.authorization import (
    AuthorizationContext,
    AuthorizationResource,
    OrganizationPermission,
)
from src.auth.domain.entities import (
    AuthenticatedActorContext,
    AuthenticatedContext,
    MembershipRole,
)
from src.auth.domain.invitations import (
    InvitationOperation,
    InvitationRecord,
    require_utc,
)


class InvitationService:
    def __init__(
        self,
        *,
        repository: InvitationRepository,
        authorization: AuthorizationService,
    ) -> None:
        self._repository = repository
        self._authorization = authorization

    async def create(
        self,
        *,
        context: AuthenticatedContext,
        organization_id: str,
        recipient_user_id: str,
        requested_role: MembershipRole,
        idempotency_key: str,
        now: datetime,
    ) -> InvitationRecord:
        self._require_organization(
            context=context,
            permission=OrganizationPermission.INVITATION_CREATE,
            organization_id=organization_id,
            requested_role=requested_role,
        )
        key = self._idempotency_key(idempotency_key)
        now = require_utc(now, field_name="now")
        return await self._repository.create(
            organization_id=organization_id,
            inviter_user_id=context.user.id,
            recipient_user_id=self._user_id(recipient_user_id),
            requested_role=requested_role.value,
            idempotency_key=key,
            now=now,
            expires_at=now + timedelta(days=7),
        )

    async def list_for_organization(
        self, *, context: AuthenticatedContext, organization_id: str, now: datetime
    ) -> list[InvitationRecord]:
        self._require_organization(
            context=context,
            permission=OrganizationPermission.INVITATION_READ,
            organization_id=organization_id,
        )
        return await self._repository.list_for_organization(
            organization_id=organization_id, now=now
        )

    async def get_for_actor(
        self,
        *,
        actor: AuthenticatedActorContext,
        organization_id: str,
        invitation_id: str,
        now: datetime,
    ) -> InvitationRecord:
        invitation = await self._repository.get_for_actor(
            organization_id=organization_id,
            invitation_id=invitation_id,
            actor_user_id=actor.user.id,
            now=now,
        )
        if invitation is None:
            from src.auth.application.invitation_errors import InvitationNotFoundError

            raise InvitationNotFoundError("invitation not found")
        return invitation

    async def transition_for_recipient(
        self,
        *,
        actor: AuthenticatedActorContext,
        organization_id: str,
        invitation_id: str,
        operation: InvitationOperation,
        idempotency_key: str,
        now: datetime,
    ) -> InvitationRecord:
        if operation not in {InvitationOperation.ACCEPT, InvitationOperation.DECLINE}:
            raise InvitationValidationError("recipient operation is invalid")
        return await self._repository.transition(
            organization_id=organization_id,
            invitation_id=invitation_id,
            actor_user_id=actor.user.id,
            operation=operation,
            idempotency_key=self._idempotency_key(idempotency_key),
            now=now,
        )

    async def transition_for_manager(
        self,
        *,
        context: AuthenticatedContext,
        organization_id: str,
        invitation_id: str,
        operation: InvitationOperation,
        idempotency_key: str,
        now: datetime,
    ) -> InvitationRecord:
        if operation not in {InvitationOperation.REVOKE, InvitationOperation.RESEND}:
            raise InvitationValidationError("manager operation is invalid")
        self._require_organization(
            context=context,
            permission=OrganizationPermission.INVITATION_REVOKE,
            organization_id=organization_id,
        )
        return await self._repository.transition(
            organization_id=organization_id,
            invitation_id=invitation_id,
            actor_user_id=context.user.id,
            operation=operation,
            idempotency_key=self._idempotency_key(idempotency_key),
            now=now,
        )

    def _require_organization(
        self,
        *,
        context: AuthenticatedContext,
        permission: OrganizationPermission,
        organization_id: str,
        requested_role: MembershipRole | None = None,
    ) -> None:
        self._authorization.require(
            context=AuthorizationContext.from_authenticated_context(context),
            permission=permission,
            resource=AuthorizationResource(
                organization_id=organization_id, requested_role=requested_role
            ),
        )

    @staticmethod
    def _idempotency_key(value: str) -> str:
        key = value.strip()
        if not 8 <= len(key) <= 255:
            raise InvitationValidationError(
                "Idempotency-Key must be between 8 and 255 characters"
            )
        return key

    @staticmethod
    def _user_id(value: str) -> str:
        user_id = value.strip()
        if not user_id:
            raise InvitationValidationError("recipient user is required")
        return user_id
