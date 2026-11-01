from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.application.ports import AuditRepository
from src.audit.domain.entities import AuditEventDraft, AuditOutcome
from src.audit.infrastructure.repository import SqlAlchemyAuditRepository
from src.auth.application.invitation_errors import (
    InvitationConflictError,
    InvitationMutationConflictError,
    InvitationNotFoundError,
)
from src.auth.domain.entities import MembershipRole, MembershipStatus
from src.auth.domain.invitations import (
    InvitationOperation,
    InvitationRecord,
    InvitationStatus,
    require_utc,
)
from src.auth.infrastructure.models import (
    InvitationModel,
    InvitationOperationModel,
    MembershipModel,
    OrganizationModel,
    UserModel,
)
from src.infrastructure.database import AsyncSessionLocal
from src.notifications.infrastructure.models import NotificationEventModel
from src.notifications.infrastructure.repository import SqlAlchemyNotificationRepository


class SqlAlchemyInvitationRepository:
    def __init__(
        self,
        *,
        notification_repository: SqlAlchemyNotificationRepository | None = None,
        audit_repository: AuditRepository | None = None,
    ) -> None:
        self._notifications = (
            notification_repository or SqlAlchemyNotificationRepository()
        )
        self._audit = audit_repository or SqlAlchemyAuditRepository()

    async def create(
        self,
        *,
        organization_id: str,
        inviter_user_id: str,
        recipient_user_id: str,
        requested_role: str,
        idempotency_key: str,
        now: datetime,
        expires_at: datetime,
    ) -> InvitationRecord:
        now = require_utc(now, field_name="now")
        expires_at = require_utc(expires_at, field_name="expires_at")
        async with AsyncSessionLocal() as session:
            try:
                async with session.begin():
                    existing_operation = await self._find_operation(
                        session,
                        actor_user_id=inviter_user_id,
                        operation=InvitationOperation.CREATE,
                        idempotency_key=idempotency_key,
                    )
                    if existing_operation is not None:
                        invitation = await self._lock_invitation(
                            session,
                            organization_id=organization_id,
                            invitation_id=existing_operation.invitation_id,
                        )
                        return await self._record(session, invitation)

                    organization = await self._lock_organization(
                        session, organization_id=organization_id
                    )
                    inviter = await self._lock_membership(
                        session,
                        organization_id=organization_id,
                        user_id=inviter_user_id,
                    )
                    self._assert_inviter_can_request(inviter, requested_role)
                    if recipient_user_id == inviter_user_id:
                        raise InvitationConflictError("self_invitation")
                    recipient = await session.get(UserModel, recipient_user_id)
                    if recipient is None:
                        raise InvitationNotFoundError("recipient user not found")
                    existing_membership = await self._get_membership(
                        session,
                        organization_id=organization_id,
                        user_id=recipient_user_id,
                        for_update=True,
                    )
                    if (
                        existing_membership is not None
                        and existing_membership.status != MembershipStatus.REMOVED.value
                    ):
                        raise InvitationConflictError("already_member")
                    invitation = await session.scalar(
                        select(InvitationModel)
                        .where(InvitationModel.organization_id == organization_id)
                        .where(InvitationModel.recipient_user_id == recipient_user_id)
                        .with_for_update()
                    )
                    if invitation is not None:
                        if invitation.status == InvitationStatus.PENDING.value:
                            raise InvitationConflictError("invitation_pending")
                        if invitation.status == InvitationStatus.ACCEPTED.value:
                            raise InvitationConflictError("invitation_accepted")
                        invitation.status = InvitationStatus.PENDING.value
                        invitation.inviter_user_id = inviter_user_id
                        invitation.updated_at = now
                        invitation.expires_at = expires_at
                        invitation.requested_role = requested_role
                        invitation.revision += 1
                    else:
                        invitation = InvitationModel(
                            organization_id=organization_id,
                            inviter_user_id=inviter_user_id,
                            recipient_user_id=recipient_user_id,
                            requested_role=requested_role,
                            status=InvitationStatus.PENDING.value,
                            created_at=now,
                            updated_at=now,
                            expires_at=expires_at,
                            revision=1,
                            notification_event_id="pending",
                        )
                        session.add(invitation)
                    await session.flush()
                    event_key = (
                        f"organization.invitation:{invitation.id}:{invitation.revision}"
                    )
                    notification = await self._notifications.publish_in_session(
                        session,
                        event_key=event_key,
                        organization_id=organization_id,
                        payload=self._payload(
                            invitation=invitation,
                            organization_name=organization.name,
                            inviter_display_name=(
                                await session.scalar(
                                    select(UserModel.display_name).where(
                                        UserModel.id == inviter_user_id
                                    )
                                )
                            )
                            or "Organization administrator",
                            recipient_display_name=recipient.display_name,
                        ),
                        recipient_user_id=recipient_user_id,
                        expires_at=expires_at,
                        action_ref=invitation.id,
                        now=now,
                    )
                    invitation.notification_event_id = notification.event_id
                    session.add(
                        InvitationOperationModel(
                            invitation_id=invitation.id,
                            organization_id=organization_id,
                            actor_user_id=inviter_user_id,
                            operation=InvitationOperation.CREATE.value,
                            idempotency_key=idempotency_key,
                            created_at=now,
                        )
                    )
                    await self._add_event(
                        session,
                        organization_id=organization_id,
                        actor_user_id=inviter_user_id,
                        operation=InvitationOperation.CREATE,
                        invitation=invitation,
                        now=now,
                    )
                    await session.flush()
                    return await self._record(session, invitation)
            except (IntegrityError, OperationalError) as error:
                raise InvitationMutationConflictError(
                    "invitation_conflict", "the invitation changed; retry the operation"
                ) from error

    async def list_for_organization(
        self, *, organization_id: str, now: datetime
    ) -> list[InvitationRecord]:
        now = require_utc(now, field_name="now")
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await self._expire_pending(
                    session, organization_id=organization_id, now=now
                )
                rows = (
                    (
                        await session.execute(
                            select(InvitationModel)
                            .where(InvitationModel.organization_id == organization_id)
                            .order_by(
                                InvitationModel.updated_at.desc(),
                                InvitationModel.id.desc(),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                return [await self._record(session, item) for item in rows]

    async def get_for_actor(
        self,
        *,
        organization_id: str,
        invitation_id: str,
        actor_user_id: str,
        now: datetime,
    ) -> InvitationRecord | None:
        now = require_utc(now, field_name="now")
        async with AsyncSessionLocal() as session:
            async with session.begin():
                invitation = await session.scalar(
                    select(InvitationModel)
                    .where(InvitationModel.id == invitation_id)
                    .where(InvitationModel.organization_id == organization_id)
                    .where(
                        (InvitationModel.recipient_user_id == actor_user_id)
                        | (InvitationModel.inviter_user_id == actor_user_id)
                    )
                    .with_for_update()
                )
                if invitation is None:
                    return None
                if invitation.inviter_user_id == actor_user_id:
                    manager = await self._get_membership(
                        session,
                        organization_id=organization_id,
                        user_id=actor_user_id,
                        for_update=False,
                    )
                    if (
                        manager is None
                        or manager.status != MembershipStatus.ACTIVE.value
                        or manager.role
                        not in {
                            MembershipRole.OWNER.value,
                            MembershipRole.ADMIN.value,
                        }
                    ):
                        return None
                await self._expire_if_needed(session, invitation=invitation, now=now)
                return await self._record(session, invitation)

    async def transition(
        self,
        *,
        organization_id: str,
        invitation_id: str,
        actor_user_id: str,
        operation: InvitationOperation,
        idempotency_key: str,
        now: datetime,
    ) -> InvitationRecord:
        now = require_utc(now, field_name="now")
        async with AsyncSessionLocal() as session:
            try:
                async with session.begin():
                    existing_operation = await self._find_operation(
                        session,
                        actor_user_id=actor_user_id,
                        operation=operation,
                        idempotency_key=idempotency_key,
                    )
                    if existing_operation is not None:
                        if existing_operation.invitation_id != invitation_id:
                            raise InvitationConflictError("idempotency_key_reused")
                        invitation = await self._lock_invitation(
                            session,
                            organization_id=organization_id,
                            invitation_id=existing_operation.invitation_id,
                        )
                        if (
                            invitation.recipient_user_id != actor_user_id
                            and invitation.inviter_user_id != actor_user_id
                        ):
                            raise InvitationNotFoundError("invitation not found")
                        return await self._record(session, invitation)

                    await self._lock_organization(
                        session, organization_id=organization_id
                    )
                    invitation = await self._lock_invitation(
                        session,
                        organization_id=organization_id,
                        invitation_id=invitation_id,
                    )
                    if actor_user_id not in {
                        invitation.recipient_user_id,
                        invitation.inviter_user_id,
                    } and operation not in {
                        InvitationOperation.REVOKE,
                        InvitationOperation.RESEND,
                    }:
                        raise InvitationNotFoundError("invitation not found")
                    await self._expire_if_needed(
                        session, invitation=invitation, now=now
                    )

                    if operation in {
                        InvitationOperation.ACCEPT,
                        InvitationOperation.DECLINE,
                    }:
                        if actor_user_id != invitation.recipient_user_id:
                            raise InvitationNotFoundError("invitation not found")
                        if invitation.status != InvitationStatus.PENDING.value:
                            raise InvitationConflictError(
                                f"invitation_{invitation.status}"
                            )
                        if operation is InvitationOperation.ACCEPT:
                            await self._accept(session, invitation=invitation, now=now)
                        else:
                            invitation.status = InvitationStatus.DECLINED.value
                            invitation.updated_at = now
                            await self._update_notification(
                                session,
                                invitation=invitation,
                                status=InvitationStatus.DECLINED,
                            )
                    elif operation is InvitationOperation.REVOKE:
                        manager = await self._lock_membership(
                            session,
                            organization_id=organization_id,
                            user_id=actor_user_id,
                        )
                        self._assert_manager_can_manage(manager)
                        if invitation.status == InvitationStatus.PENDING.value:
                            invitation.status = InvitationStatus.REVOKED.value
                            invitation.updated_at = now
                            await self._update_notification(
                                session,
                                invitation=invitation,
                                status=InvitationStatus.REVOKED,
                            )
                        elif invitation.status == InvitationStatus.EXPIRED.value:
                            raise InvitationConflictError("invitation_expired")
                        elif invitation.status not in {
                            InvitationStatus.REVOKED.value,
                            InvitationStatus.DECLINED.value,
                        }:
                            raise InvitationConflictError(
                                f"invitation_{invitation.status}"
                            )
                    elif operation is InvitationOperation.RESEND:
                        manager = await self._lock_membership(
                            session,
                            organization_id=organization_id,
                            user_id=actor_user_id,
                        )
                        self._assert_manager_can_manage(manager)
                        if invitation.status == InvitationStatus.PENDING.value:
                            raise InvitationConflictError("invitation_pending")
                        if invitation.status == InvitationStatus.ACCEPTED.value:
                            raise InvitationConflictError("invitation_accepted")
                        organization = await session.get(
                            OrganizationModel, organization_id
                        )
                        if organization is None:
                            raise InvitationNotFoundError("organization not found")
                        self._assert_inviter_can_request(
                            manager, invitation.requested_role
                        )
                        recipient = await session.get(
                            UserModel, invitation.recipient_user_id
                        )
                        if recipient is None:
                            raise InvitationNotFoundError("recipient user not found")
                        invitation.status = InvitationStatus.PENDING.value
                        invitation.inviter_user_id = actor_user_id
                        invitation.updated_at = now
                        invitation.expires_at = now + timedelta(days=7)
                        invitation.revision += 1
                        notification = await self._notifications.publish_in_session(
                            session,
                            event_key=f"organization.invitation:{invitation.id}:{invitation.revision}",
                            organization_id=organization_id,
                            payload=self._payload(
                                invitation=invitation,
                                organization_name=organization.name,
                                inviter_display_name=(
                                    await session.scalar(
                                        select(UserModel.display_name).where(
                                            UserModel.id == actor_user_id
                                        )
                                    )
                                )
                                or "Organization administrator",
                                recipient_display_name=recipient.display_name,
                            ),
                            recipient_user_id=invitation.recipient_user_id,
                            expires_at=invitation.expires_at,
                            action_ref=invitation.id,
                            now=now,
                        )
                        invitation.notification_event_id = notification.event_id
                    else:
                        raise InvitationConflictError("unsupported_operation")

                    session.add(
                        InvitationOperationModel(
                            invitation_id=invitation.id,
                            organization_id=organization_id,
                            actor_user_id=actor_user_id,
                            operation=operation.value,
                            idempotency_key=idempotency_key,
                            created_at=now,
                        )
                    )
                    await self._add_event(
                        session,
                        organization_id=organization_id,
                        actor_user_id=actor_user_id,
                        operation=operation,
                        invitation=invitation,
                        now=now,
                    )
                    await session.flush()
                    return await self._record(session, invitation)
            except (IntegrityError, OperationalError) as error:
                raise InvitationMutationConflictError(
                    "invitation_conflict", "the invitation changed; retry the operation"
                ) from error

    async def _accept(
        self, session: AsyncSession, *, invitation: InvitationModel, now: datetime
    ) -> None:
        await self._lock_organization(
            session, organization_id=invitation.organization_id
        )
        inviter = await self._lock_membership(
            session,
            organization_id=invitation.organization_id,
            user_id=invitation.inviter_user_id,
        )
        self._assert_inviter_can_request(inviter, invitation.requested_role)
        membership = await self._get_membership(
            session,
            organization_id=invitation.organization_id,
            user_id=invitation.recipient_user_id,
            for_update=True,
        )
        if (
            membership is not None
            and membership.status != MembershipStatus.REMOVED.value
        ):
            raise InvitationConflictError("already_member")
        if membership is None:
            membership = MembershipModel(
                organization_id=invitation.organization_id,
                user_id=invitation.recipient_user_id,
                role=invitation.requested_role,
                status=MembershipStatus.ACTIVE.value,
                created_at=now.replace(tzinfo=None),
                updated_at=now.replace(tzinfo=None),
            )
            session.add(membership)
        else:
            membership.role = invitation.requested_role
            membership.status = MembershipStatus.ACTIVE.value
            membership.updated_at = now.replace(tzinfo=None)
        invitation.status = InvitationStatus.ACCEPTED.value
        invitation.updated_at = now
        await self._update_notification(
            session, invitation=invitation, status=InvitationStatus.ACCEPTED
        )

    async def _expire_pending(
        self, session: AsyncSession, *, organization_id: str, now: datetime
    ) -> None:
        rows = (
            (
                await session.execute(
                    select(InvitationModel)
                    .where(InvitationModel.organization_id == organization_id)
                    .where(InvitationModel.status == InvitationStatus.PENDING.value)
                    .where(InvitationModel.expires_at <= now)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for invitation in rows:
            await self._expire_if_needed(session, invitation=invitation, now=now)

    async def _expire_if_needed(
        self, session: AsyncSession, *, invitation: InvitationModel, now: datetime
    ) -> None:
        if (
            invitation.status == InvitationStatus.PENDING.value
            and invitation.expires_at <= now
        ):
            invitation.status = InvitationStatus.EXPIRED.value
            invitation.updated_at = now
            await self._update_notification(
                session, invitation=invitation, status=InvitationStatus.EXPIRED
            )

    async def _update_notification(
        self,
        session: AsyncSession,
        *,
        invitation: InvitationModel,
        status: InvitationStatus,
    ) -> None:
        event = await session.get(
            NotificationEventModel, invitation.notification_event_id
        )
        if event is None:
            return
        payload = dict(event.payload)
        payload["status"] = status.value
        payload["outcome"] = status.value
        await session.execute(
            update(NotificationEventModel)
            .where(NotificationEventModel.id == event.id)
            .values(
                payload=payload,
                expires_at=(
                    invitation.expires_at
                    if status is InvitationStatus.PENDING
                    else None
                ),
            )
        )

    async def _record(
        self, session: AsyncSession, invitation: InvitationModel
    ) -> InvitationRecord:
        organization = await session.get(OrganizationModel, invitation.organization_id)
        inviter = await session.get(UserModel, invitation.inviter_user_id)
        recipient = await session.get(UserModel, invitation.recipient_user_id)
        if organization is None or inviter is None or recipient is None:
            raise InvitationNotFoundError("invitation not found")
        return InvitationRecord(
            id=invitation.id,
            organization_id=invitation.organization_id,
            organization_name=organization.name,
            inviter_user_id=invitation.inviter_user_id,
            inviter_display_name=inviter.display_name,
            recipient_user_id=invitation.recipient_user_id,
            recipient_display_name=recipient.display_name,
            requested_role=invitation.requested_role,
            status=InvitationStatus(invitation.status),
            created_at=invitation.created_at,
            updated_at=invitation.updated_at,
            expires_at=invitation.expires_at,
            revision=invitation.revision,
            notification_event_id=invitation.notification_event_id,
        )

    @staticmethod
    async def _find_operation(
        session: AsyncSession,
        *,
        actor_user_id: str,
        operation: InvitationOperation,
        idempotency_key: str,
    ) -> InvitationOperationModel | None:
        return await session.scalar(
            select(InvitationOperationModel)
            .where(InvitationOperationModel.actor_user_id == actor_user_id)
            .where(InvitationOperationModel.operation == operation.value)
            .where(InvitationOperationModel.idempotency_key == idempotency_key)
        )

    @staticmethod
    async def _lock_invitation(
        session: AsyncSession, *, organization_id: str, invitation_id: str
    ) -> InvitationModel:
        invitation = await session.scalar(
            select(InvitationModel)
            .where(InvitationModel.organization_id == organization_id)
            .where(InvitationModel.id == invitation_id)
            .with_for_update()
        )
        if invitation is None:
            raise InvitationNotFoundError("invitation not found")
        return invitation

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
            raise InvitationNotFoundError("organization not found")
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
            raise InvitationNotFoundError("organization membership not found")
        return membership

    @staticmethod
    async def _get_membership(
        session: AsyncSession,
        *,
        organization_id: str,
        user_id: str,
        for_update: bool,
    ) -> MembershipModel | None:
        statement = (
            select(MembershipModel)
            .where(MembershipModel.organization_id == organization_id)
            .where(MembershipModel.user_id == user_id)
        )
        if for_update:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    @staticmethod
    def _assert_inviter_can_request(
        membership: MembershipModel, requested_role: str
    ) -> None:
        if membership.status != MembershipStatus.ACTIVE.value:
            raise InvitationConflictError("inviter_not_active")
        if membership.role not in {
            MembershipRole.OWNER.value,
            MembershipRole.ADMIN.value,
        }:
            raise InvitationConflictError("inviter_not_authorized")
        if requested_role not in {
            MembershipRole.ADMIN.value,
            MembershipRole.MEMBER.value,
        }:
            raise InvitationConflictError("role_not_assignable")
        if (
            membership.role == MembershipRole.ADMIN.value
            and requested_role == MembershipRole.ADMIN.value
        ):
            raise InvitationConflictError("role_not_assignable")

    @staticmethod
    def _assert_manager_can_manage(membership: MembershipModel) -> None:
        if (
            membership.status != MembershipStatus.ACTIVE.value
            or membership.role
            not in {
                MembershipRole.OWNER.value,
                MembershipRole.ADMIN.value,
            }
        ):
            raise InvitationNotFoundError("invitation not found")

    @staticmethod
    def _payload(
        *,
        invitation: InvitationModel,
        organization_name: str,
        inviter_display_name: str,
        recipient_display_name: str,
    ) -> dict[str, object]:
        return {
            "organization_name": organization_name,
            "inviter_display_name": inviter_display_name,
            "recipient_display_name": recipient_display_name,
            "requested_role": invitation.requested_role,
            "status": invitation.status,
            "outcome": invitation.status,
        }

    async def _add_event(
        self,
        session: AsyncSession,
        *,
        organization_id: str,
        actor_user_id: str,
        operation: InvitationOperation,
        invitation: InvitationModel,
        now: datetime,
    ) -> None:
        await self._audit.append_in_session(
            session,
            event=AuditEventDraft(
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                action=f"organization.invitation.{operation.value}",
                outcome=AuditOutcome.SUCCESS,
                target_type="invitation",
                target_id=invitation.id,
                payload={
                    "status": invitation.status,
                    "requested_role": invitation.requested_role,
                },
                occurred_at=now,
            ),
        )
