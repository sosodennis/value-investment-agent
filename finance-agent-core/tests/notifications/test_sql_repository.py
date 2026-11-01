from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, text

from src.audit.infrastructure.models import AuditEventModel
from src.auth.infrastructure.models import UserModel
from src.auth.infrastructure.repositories import SqlAlchemyUserRepository
from src.infrastructure.database import AsyncSessionLocal, init_db
from src.notifications.application.service import NotificationService
from src.notifications.application.wiring import InAppNotificationDeliveryAdapter
from src.notifications.application.worker import NotificationOutboxWorker
from src.notifications.domain.entities import NotificationAction, NotificationType
from src.notifications.domain.errors import (
    NotificationDeliveryError,
    NotificationEventConflictError,
    NotificationOutboxLeaseError,
)
from src.notifications.infrastructure.models import (
    NotificationEventModel,
    NotificationInboxItemModel,
    NotificationOutboxModel,
)
from src.notifications.infrastructure.repository import (
    SqlAlchemyNotificationRepository,
    SqlAlchemyNotificationTransaction,
)

pytestmark = pytest.mark.skipif(
    os.getenv("NOTIFICATION_POSTGRES_TEST") != "1",
    reason="requires the isolated PostgreSQL notification test database",
)


class _FailingDeliveryAdapter:
    async def deliver(self, *, delivery):
        raise NotificationDeliveryError(
            "token=https://sensitive.example/?token=secret-value",
            safe_code="adapter_unavailable",
        )


async def _cleanup(user_ids: set[str], event_keys: set[str]) -> None:
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
        event_ids = set(
            (
                await session.scalars(
                    select(NotificationEventModel.id).where(
                        NotificationEventModel.event_key.in_(event_keys)
                    )
                )
            ).all()
        )
        if event_ids:
            await session.execute(
                delete(NotificationInboxItemModel).where(
                    NotificationInboxItemModel.event_id.in_(event_ids)
                )
            )
            await session.execute(
                delete(NotificationEventModel).where(
                    NotificationEventModel.id.in_(event_ids)
                )
            )
        await session.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))
        await session.commit()


@pytest.mark.asyncio
async def test_notification_repository_isolates_recipients_deduplicates_events_and_expires_items() -> (
    None
):
    await init_db()
    users = SqlAlchemyUserRepository()
    repository = SqlAlchemyNotificationRepository()
    worker = NotificationOutboxWorker(
        repository=repository,
        adapter=InAppNotificationDeliveryAdapter(repository=repository),
        base_backoff_seconds=1,
        max_backoff_seconds=4,
    )
    user_a = await users.create_with_default_organization(
        email=f"notification-a-{uuid.uuid4()}@example.test",
        password_hash="hash",
        display_name="Notification A",
        display_name_normalized="notification a",
    )
    user_b = await users.create_with_default_organization(
        email=f"notification-b-{uuid.uuid4()}@example.test",
        password_hash="hash",
        display_name="Notification B",
        display_name_normalized="notification b",
    )
    user_c = await users.create_with_default_organization(
        email=f"notification-c-{uuid.uuid4()}@example.test",
        password_hash="hash",
        display_name="Notification C",
        display_name_normalized="notification c",
    )
    now = datetime.now(UTC)
    event_key = f"organization.invitation:{uuid.uuid4()}"
    expired_key = f"system.expired:{uuid.uuid4()}"
    try:
        first = await repository.enqueue(
            event_key=event_key,
            correlation_id="notification-correlation-1",
            notification_type=NotificationType.ORGANIZATION_INVITATION,
            organization_id=user_a.organization.id,
            payload={"organization_name": "Alpha"},
            action=NotificationAction(
                action_type="organization.invitation", action_ref="invitation-1"
            ),
            recipient_user_ids=(user_a.user.id,),
            occurred_at=now,
            expires_at=now + timedelta(days=7),
        )
        assert len(first.deliveries) == 1
        assert first.deliveries[0].organization_id == user_a.organization.id
        assert first.deliveries[0].correlation_id == "notification-correlation-1"
        concurrent_runs = await asyncio.gather(
            worker.run_once(now=now, worker_id="worker-a"),
            worker.run_once(now=now, worker_id="worker-b"),
        )
        assert sum(result.claimed for result in concurrent_runs) == 1
        assert sum(result.delivered for result in concurrent_runs) == 1
        async with AsyncSessionLocal() as session:
            event = await session.get(NotificationEventModel, first.event_id)
            assert event is not None
            assert event.correlation_id == "notification-correlation-1"
            delivered_audit = (
                await session.scalars(
                    select(AuditEventModel).where(
                        AuditEventModel.action == "notification.in_app.delivered",
                        AuditEventModel.target_id == first.event_id,
                    )
                )
            ).first()
            assert delivered_audit is not None
            assert delivered_audit.correlation_id == "notification-correlation-1"
        assert (
            await repository.list_for_recipient(
                recipient_user_id=user_b.user.id, limit=50, now=now
            )
            == []
        )

        duplicate = await repository.enqueue(
            event_key=event_key,
            notification_type=NotificationType.ORGANIZATION_INVITATION,
            organization_id=user_a.organization.id,
            payload={"organization_name": "Alpha"},
            action=NotificationAction(
                action_type="organization.invitation", action_ref="invitation-1"
            ),
            recipient_user_ids=(user_a.user.id, user_b.user.id),
            occurred_at=now,
            expires_at=now + timedelta(days=7),
        )
        assert {item.recipient_user_id for item in duplicate.deliveries} == {
            user_a.user.id,
            user_b.user.id,
        }
        assert (await worker.run_once(now=now, worker_id="worker-a")).delivered == 1
        assert (
            await repository.unread_count(recipient_user_id=user_a.user.id, now=now)
            == 1
        )
        assert (
            await repository.unread_count(recipient_user_id=user_b.user.id, now=now)
            == 1
        )

        with pytest.raises(NotificationEventConflictError, match="different event"):
            await repository.enqueue(
                event_key=event_key,
                notification_type=NotificationType.ORGANIZATION_INVITATION,
                organization_id=user_a.organization.id,
                payload={"organization_name": "Changed"},
                action=NotificationAction(
                    action_type="organization.invitation", action_ref="invitation-1"
                ),
                recipient_user_ids=(user_a.user.id,),
                occurred_at=now,
                expires_at=now + timedelta(days=7),
            )

        active_items = await repository.list_for_recipient(
            recipient_user_id=user_a.user.id, limit=50, now=now
        )
        first_inbox_id = next(
            item.id for item in active_items if item.event_id == first.event_id
        )
        read_results = await asyncio.gather(
            repository.mark_read(
                recipient_user_id=user_a.user.id,
                item_id=first_inbox_id,
                now=now,
            ),
            repository.mark_read(
                recipient_user_id=user_a.user.id,
                item_id=first_inbox_id,
                now=now,
            ),
        )
        assert all(
            item is not None and item.read_at is not None for item in read_results
        )
        assert (
            await repository.mark_read(
                recipient_user_id=user_c.user.id, item_id=first_inbox_id, now=now
            )
            is None
        )
        assert (
            await repository.unread_count(recipient_user_id=user_a.user.id, now=now)
            == 0
        )

        await repository.enqueue(
            event_key=expired_key,
            notification_type=NotificationType.SYSTEM,
            organization_id=None,
            payload={"message": "expired"},
            action=None,
            recipient_user_ids=(user_a.user.id,),
            occurred_at=now - timedelta(days=2),
            expires_at=now - timedelta(days=1),
        )
        assert (await worker.run_once(now=now, worker_id="worker-a")).delivered == 1
        visible_items = await repository.list_for_recipient(
            recipient_user_id=user_a.user.id, limit=50, now=now
        )
        assert [item.event_id for item in visible_items] == [first.event_id]
        assert all(
            item.expires_at is None or item.expires_at > now for item in visible_items
        )
        assert (
            await repository.unread_count(recipient_user_id=user_a.user.id, now=now)
            == 0
        )
    finally:
        await _cleanup(
            {user_a.user.id, user_b.user.id, user_c.user.id}, {event_key, expired_key}
        )


@pytest.mark.asyncio
async def test_notification_outbox_retry_dead_letter_replay_and_idempotent_inbox() -> (
    None
):
    await init_db()
    users = SqlAlchemyUserRepository()
    repository = SqlAlchemyNotificationRepository()
    user = await users.create_with_default_organization(
        email=f"notification-replay-{uuid.uuid4()}@example.test",
        password_hash="hash",
        display_name="Notification Replay",
        display_name_normalized="notification replay",
    )
    now = datetime.now(UTC)
    event_key = f"system.replay:{uuid.uuid4()}"
    try:
        enqueued = await repository.enqueue(
            event_key=event_key,
            correlation_id="notification-failure-correlation",
            notification_type=NotificationType.SYSTEM,
            organization_id=None,
            payload={"message": "safe"},
            action=None,
            recipient_user_ids=(user.user.id,),
            occurred_at=now,
            expires_at=None,
        )
        failing_worker = NotificationOutboxWorker(
            repository=repository,
            adapter=_FailingDeliveryAdapter(),
            max_attempts=1,
        )
        failed = await failing_worker.run_once(now=now, worker_id="worker-fail")
        assert failed.dead_lettered == 1
        dead_letters = await repository.list_dead_letters(limit=10)
        assert [item.id for item in dead_letters] == [enqueued.deliveries[0].id]
        assert dead_letters[0].last_error == "adapter_unavailable"
        assert not hasattr(dead_letters[0], "payload")
        assert not hasattr(dead_letters[0], "action")
        assert await repository.replay_dead_letter(
            delivery_id=dead_letters[0].id, now=now + timedelta(seconds=1)
        )

        successful_worker = NotificationOutboxWorker(
            repository=repository,
            adapter=InAppNotificationDeliveryAdapter(repository=repository),
        )
        assert (
            await successful_worker.run_once(
                now=now + timedelta(seconds=1), worker_id="worker-replay"
            )
        ).delivered == 1
        assert (
            await successful_worker.run_once(
                now=now + timedelta(seconds=2), worker_id="worker-replay"
            )
        ).claimed == 0
        assert (
            len(
                await repository.list_for_recipient(
                    recipient_user_id=user.user.id, limit=10, now=now
                )
            )
            == 1
        )
    finally:
        await _cleanup({user.user.id}, {event_key})


@pytest.mark.asyncio
async def test_notification_transaction_rolls_back_event_and_outbox_together() -> None:
    await init_db()
    users = SqlAlchemyUserRepository()
    repository = SqlAlchemyNotificationRepository()
    service = NotificationService(repository=repository)
    user = await users.create_with_default_organization(
        email=f"notification-transaction-{uuid.uuid4()}@example.test",
        password_hash="hash",
        display_name="Notification Transaction",
        display_name_normalized="notification transaction",
    )
    event_key = f"organization.transaction:{uuid.uuid4()}"
    now = datetime.now(UTC)
    try:
        async with AsyncSessionLocal() as session:
            with pytest.raises(RuntimeError, match="source transaction failure"):
                async with session.begin():
                    source_event = AuditEventModel(
                        organization_id=user.organization.id,
                        actor_type="user",
                        actor_user_id=user.user.id,
                        action="organization.invitation.created",
                        outcome="success",
                        correlation_id=event_key,
                        payload={"notification_event_key": event_key},
                        occurred_at=now,
                    )
                    session.add(source_event)
                    await session.flush()
                    transaction = SqlAlchemyNotificationTransaction(
                        session=session, repository=repository
                    )
                    await service.publish(
                        event_key=event_key,
                        notification_type=NotificationType.ORGANIZATION_INVITATION,
                        organization_id=user.organization.id,
                        payload={"organization_name": "Atomic"},
                        action=None,
                        recipient_user_ids=(user.user.id,),
                        occurred_at=now,
                        expires_at=None,
                        transaction=transaction,
                    )
                    raise RuntimeError("source transaction failure")

        async with AsyncSessionLocal() as session:
            assert (
                await session.scalar(
                    select(NotificationEventModel.id).where(
                        NotificationEventModel.event_key == event_key
                    )
                )
                is None
            )
            assert (
                await session.scalar(
                    select(NotificationOutboxModel.id).where(
                        NotificationOutboxModel.recipient_user_id == user.user.id
                    )
                )
                is None
            )
            assert (
                await session.scalar(
                    select(AuditEventModel.id).where(
                        AuditEventModel.action == "organization.invitation.created"
                    )
                )
                is None
            )
    finally:
        await _cleanup({user.user.id}, {event_key})


@pytest.mark.asyncio
async def test_expired_lease_cannot_be_completed_or_failed() -> None:
    await init_db()
    users = SqlAlchemyUserRepository()
    repository = SqlAlchemyNotificationRepository()
    user = await users.create_with_default_organization(
        email=f"notification-lease-{uuid.uuid4()}@example.test",
        password_hash="hash",
        display_name="Notification Lease",
        display_name_normalized="notification lease",
    )
    event_keys = {
        f"system.lease:{uuid.uuid4()}",
        f"system.lease:{uuid.uuid4()}",
    }
    now = datetime.now(UTC)
    try:
        deliveries = []
        for event_key in event_keys:
            result = await repository.enqueue(
                event_key=event_key,
                notification_type=NotificationType.SYSTEM,
                organization_id=None,
                payload={"message": "lease"},
                action=None,
                recipient_user_ids=(user.user.id,),
                occurred_at=now,
                expires_at=None,
            )
            deliveries.extend(result.deliveries)
        claimed = await repository.claim_ready(
            worker_id="worker-expired", now=now, lease_seconds=1, limit=2
        )
        assert {item.id for item in claimed} == {item.id for item in deliveries}
        reclaimed = await repository.claim_ready(
            worker_id="worker-reclaimer",
            now=now + timedelta(seconds=2),
            lease_seconds=1,
            limit=2,
        )
        assert {item.id for item in reclaimed} == {item.id for item in deliveries}
        with pytest.raises(NotificationOutboxLeaseError):
            await repository.mark_delivered(
                delivery_id=claimed[0].id,
                worker_id="worker-expired",
                now=now + timedelta(seconds=2),
            )
        with pytest.raises(NotificationOutboxLeaseError):
            await repository.mark_failed(
                delivery_id=claimed[1].id,
                worker_id="worker-expired",
                now=now + timedelta(seconds=2),
                error="adapter_unavailable",
                retryable=True,
                max_attempts=3,
                base_backoff_seconds=1,
                max_backoff_seconds=4,
            )
    finally:
        await _cleanup({user.user.id}, event_keys)
