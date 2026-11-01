from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select, text

from src.audit.infrastructure.models import AuditEventModel
from src.auth.application.invitation_errors import InvitationNotFoundError
from src.auth.domain.invitations import InvitationOperation
from src.auth.infrastructure.invitation_repository import SqlAlchemyInvitationRepository
from src.auth.infrastructure.models import (
    InvitationModel,
    InvitationOperationModel,
    MembershipModel,
    UserModel,
)
from src.auth.infrastructure.repositories import SqlAlchemyUserRepository
from src.infrastructure.database import AsyncSessionLocal, init_db
from src.notifications.application.wiring import InAppNotificationDeliveryAdapter
from src.notifications.application.worker import NotificationOutboxWorker
from src.notifications.infrastructure.repository import SqlAlchemyNotificationRepository

pytestmark = pytest.mark.skipif(
    os.getenv("INVITATION_POSTGRES_TEST") != "1",
    reason="requires the isolated PostgreSQL invitation test database",
)


async def _cleanup(user_ids: set[str], organization_id: str) -> None:
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
        invitation_ids = set(
            (
                await session.scalars(
                    select(InvitationModel.id).where(
                        InvitationModel.organization_id == organization_id
                    )
                )
            ).all()
        )
        if invitation_ids:
            await session.execute(
                delete(InvitationOperationModel).where(
                    InvitationOperationModel.invitation_id.in_(invitation_ids)
                )
            )
            await session.execute(
                delete(InvitationModel).where(InvitationModel.id.in_(invitation_ids))
            )
        await session.execute(
            delete(MembershipModel).where(
                MembershipModel.organization_id == organization_id
            )
        )
        await session.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))
        await session.commit()


@pytest.mark.asyncio
async def test_invitation_lifecycle_is_recipient_bound_idempotent_and_exactly_once() -> (
    None
):
    await init_db()
    users = SqlAlchemyUserRepository()
    owner = await users.create_with_default_organization(
        email=f"invite-owner-{uuid.uuid4()}@example.test",
        password_hash="hash",
        display_name="Owner",
        display_name_normalized="owner",
    )
    recipient = await users.create_with_default_organization(
        email=f"invite-recipient-{uuid.uuid4()}@example.test",
        password_hash="hash",
        display_name="Recipient",
        display_name_normalized="recipient",
    )
    manager = await users.create_with_default_organization(
        email=f"invite-manager-{uuid.uuid4()}@example.test",
        password_hash="hash",
        display_name="Manager",
        display_name_normalized="manager",
    )
    second_recipient = await users.create_with_default_organization(
        email=f"invite-second-recipient-{uuid.uuid4()}@example.test",
        password_hash="hash",
        display_name="Second Recipient",
        display_name_normalized="second recipient",
    )
    async with AsyncSessionLocal() as session:
        session.add(
            MembershipModel(
                organization_id=owner.organization.id,
                user_id=manager.user.id,
                role="admin",
                status="active",
                created_at=datetime.now(UTC).replace(tzinfo=None),
                updated_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        await session.commit()
    repository = SqlAlchemyInvitationRepository()
    now = datetime.now(UTC)
    try:
        invitation = await repository.create(
            organization_id=owner.organization.id,
            inviter_user_id=owner.user.id,
            recipient_user_id=recipient.user.id,
            requested_role="member",
            idempotency_key="create-invitation-1",
            now=now,
            expires_at=now + timedelta(days=7),
        )
        assert invitation.status.value == "pending"

        notification_repository = SqlAlchemyNotificationRepository()
        worker = NotificationOutboxWorker(
            repository=notification_repository,
            adapter=InAppNotificationDeliveryAdapter(
                repository=notification_repository
            ),
        )
        assert (
            await worker.run_once(now=now, worker_id="invitation-worker")
        ).delivered == 1
        inbox = await notification_repository.list_for_recipient(
            recipient_user_id=recipient.user.id, limit=10, now=now
        )
        assert inbox[0].payload["status"] == "pending"

        with pytest.raises(InvitationNotFoundError):
            await repository.transition(
                organization_id=owner.organization.id,
                invitation_id=invitation.id,
                actor_user_id=owner.user.id,
                operation=InvitationOperation.ACCEPT,
                idempotency_key="wrong-recipient-1",
                now=now,
            )

        accepted = await repository.transition(
            organization_id=owner.organization.id,
            invitation_id=invitation.id,
            actor_user_id=recipient.user.id,
            operation=InvitationOperation.ACCEPT,
            idempotency_key="accept-invitation-1",
            now=now,
        )
        repeated = await repository.transition(
            organization_id=owner.organization.id,
            invitation_id=invitation.id,
            actor_user_id=recipient.user.id,
            operation=InvitationOperation.ACCEPT,
            idempotency_key="accept-invitation-1",
            now=now,
        )
        assert accepted.status.value == repeated.status.value == "accepted"

        async with AsyncSessionLocal() as session:
            membership_count = await session.scalar(
                select(func.count())
                .select_from(MembershipModel)
                .where(MembershipModel.organization_id == owner.organization.id)
                .where(MembershipModel.user_id == recipient.user.id)
            )
        assert membership_count == 1
        async with AsyncSessionLocal() as session:
            audit_payloads = (
                await session.scalars(
                    select(AuditEventModel.payload).where(
                        AuditEventModel.target_id == invitation.id
                    )
                )
            ).all()
        assert audit_payloads
        assert all("invitation_id" not in payload for payload in audit_payloads)
        updated_inbox = await notification_repository.list_for_recipient(
            recipient_user_id=recipient.user.id, limit=10, now=now
        )
        assert updated_inbox[0].payload["status"] == "accepted"

        second = await repository.create(
            organization_id=owner.organization.id,
            inviter_user_id=owner.user.id,
            recipient_user_id=second_recipient.user.id,
            requested_role="member",
            idempotency_key="create-second-1",
            now=now,
            expires_at=now + timedelta(days=7),
        )
        revoked = await repository.transition(
            organization_id=owner.organization.id,
            invitation_id=second.id,
            actor_user_id=manager.user.id,
            operation=InvitationOperation.REVOKE,
            idempotency_key="revoke-second-1",
            now=now,
        )
        resent = await repository.transition(
            organization_id=owner.organization.id,
            invitation_id=second.id,
            actor_user_id=manager.user.id,
            operation=InvitationOperation.RESEND,
            idempotency_key="resend-second-1",
            now=now,
        )
        assert revoked.status.value == "revoked"
        assert resent.status.value == "pending" and resent.revision == 2
    finally:
        await _cleanup(
            {
                owner.user.id,
                recipient.user.id,
                manager.user.id,
                second_recipient.user.id,
            },
            owner.organization.id,
        )


@pytest.mark.asyncio
async def test_invitation_create_rolls_back_when_notification_enqueue_fails() -> None:
    await init_db()
    users = SqlAlchemyUserRepository()
    owner = await users.create_with_default_organization(
        email=f"invite-atomic-owner-{uuid.uuid4()}@example.test",
        password_hash="hash",
        display_name="Owner",
        display_name_normalized="owner",
    )
    recipient = await users.create_with_default_organization(
        email=f"invite-atomic-recipient-{uuid.uuid4()}@example.test",
        password_hash="hash",
        display_name="Recipient",
        display_name_normalized="recipient",
    )

    class FailingNotifications:
        async def publish_in_session(self, *_args, **_kwargs):
            raise RuntimeError("notification enqueue failed")

    repository = SqlAlchemyInvitationRepository(
        notification_repository=FailingNotifications()
    )  # type: ignore[arg-type]
    try:
        with pytest.raises(RuntimeError, match="notification enqueue failed"):
            await repository.create(
                organization_id=owner.organization.id,
                inviter_user_id=owner.user.id,
                recipient_user_id=recipient.user.id,
                requested_role="member",
                idempotency_key="create-atomic-1",
                now=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        async with AsyncSessionLocal() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(InvitationModel)
                .where(InvitationModel.organization_id == owner.organization.id)
            )
        assert count == 0
    finally:
        await _cleanup({owner.user.id, recipient.user.id}, owner.organization.id)


@pytest.mark.asyncio
async def test_expiry_keeps_final_outcome_in_private_inbox() -> None:
    await init_db()
    users = SqlAlchemyUserRepository()
    owner = await users.create_with_default_organization(
        email=f"invite-expiry-owner-{uuid.uuid4()}@example.test",
        password_hash="hash",
        display_name="Owner",
        display_name_normalized="owner",
    )
    recipient = await users.create_with_default_organization(
        email=f"invite-expiry-recipient-{uuid.uuid4()}@example.test",
        password_hash="hash",
        display_name="Recipient",
        display_name_normalized="recipient",
    )
    repository = SqlAlchemyInvitationRepository()
    notifications = SqlAlchemyNotificationRepository()
    now = datetime.now(UTC)
    try:
        invitation = await repository.create(
            organization_id=owner.organization.id,
            inviter_user_id=owner.user.id,
            recipient_user_id=recipient.user.id,
            requested_role="member",
            idempotency_key="create-expired-1",
            now=now - timedelta(days=2),
            expires_at=now - timedelta(days=1),
        )
        worker = NotificationOutboxWorker(
            repository=notifications,
            adapter=InAppNotificationDeliveryAdapter(repository=notifications),
        )
        await worker.run_once(now=now, worker_id="expiry-worker")
        expired = await repository.get_for_actor(
            organization_id=owner.organization.id,
            invitation_id=invitation.id,
            actor_user_id=recipient.user.id,
            now=now,
        )
        assert expired is not None and expired.status.value == "expired"
        inbox = await notifications.list_for_recipient(
            recipient_user_id=recipient.user.id, limit=10, now=now
        )
        assert inbox[0].payload["status"] == "expired"
    finally:
        await _cleanup({owner.user.id, recipient.user.id}, owner.organization.id)
