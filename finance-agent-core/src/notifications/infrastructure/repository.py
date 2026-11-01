from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.domain.entities import AuditEventDraft, AuditOutcome
from src.audit.infrastructure.repository import SqlAlchemyAuditRepository
from src.infrastructure.database import AsyncSessionLocal
from src.notifications.application.ports import NotificationRepository
from src.notifications.domain.entities import (
    JsonValue,
    NotificationAction,
    NotificationDeadLetter,
    NotificationDelivery,
    NotificationDeliveryStatus,
    NotificationEnqueueResult,
    NotificationInboxItem,
    NotificationType,
)
from src.notifications.domain.errors import (
    NotificationEventConflictError,
    NotificationOutboxLeaseError,
)
from src.shared.kernel.correlation import resolve_correlation_id

from .models import (
    NotificationEventModel,
    NotificationInboxItemModel,
    NotificationOutboxModel,
)

_SAFE_ERROR_CODE_PATTERN: Final = r"^[a-z0-9][a-z0-9_.:-]{0,63}$"


class SqlAlchemyNotificationRepository(NotificationRepository):
    def __init__(
        self, *, audit_repository: SqlAlchemyAuditRepository | None = None
    ) -> None:
        self._audit = audit_repository or SqlAlchemyAuditRepository()

    async def publish_in_session(
        self,
        session: AsyncSession,
        *,
        event_key: str,
        correlation_id: str | None = None,
        organization_id: str,
        payload: dict[str, JsonValue],
        recipient_user_id: str,
        expires_at: datetime,
        action_ref: str,
        now: datetime,
    ) -> NotificationEnqueueResult:
        return await self.enqueue_in_session(
            session,
            event_key=event_key,
            correlation_id=resolve_correlation_id(correlation_id),
            notification_type=NotificationType.ORGANIZATION_INVITATION,
            organization_id=organization_id,
            payload=payload,
            action=NotificationAction(
                action_type="organization.invitation", action_ref=action_ref
            ),
            recipient_user_ids=(recipient_user_id,),
            occurred_at=now,
            expires_at=expires_at,
        )

    async def enqueue(
        self,
        *,
        event_key: str,
        correlation_id: str | None = None,
        notification_type: NotificationType,
        organization_id: str | None,
        payload: dict[str, JsonValue],
        action: NotificationAction | None,
        recipient_user_ids: Sequence[str],
        occurred_at: datetime,
        expires_at: datetime | None,
    ) -> NotificationEnqueueResult:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                result = await self.enqueue_in_session(
                    session,
                    event_key=event_key,
                    correlation_id=resolve_correlation_id(correlation_id),
                    notification_type=notification_type,
                    organization_id=organization_id,
                    payload=payload,
                    action=action,
                    recipient_user_ids=recipient_user_ids,
                    occurred_at=occurred_at,
                    expires_at=expires_at,
                )
            return result

    async def enqueue_in_session(
        self,
        session: AsyncSession,
        *,
        event_key: str,
        correlation_id: str,
        notification_type: NotificationType,
        organization_id: str | None,
        payload: dict[str, JsonValue],
        action: NotificationAction | None,
        recipient_user_ids: Sequence[str],
        occurred_at: datetime,
        expires_at: datetime | None,
    ) -> NotificationEnqueueResult:
        resolved_correlation_id = resolve_correlation_id(correlation_id)
        event_insert = (
            insert(NotificationEventModel)
            .values(
                event_key=event_key,
                correlation_id=resolved_correlation_id,
                notification_type=notification_type.value,
                organization_id=organization_id,
                payload=payload,
                action_type=action.action_type if action else None,
                action_ref=action.action_ref if action else None,
                occurred_at=occurred_at,
                expires_at=expires_at,
            )
            .on_conflict_do_nothing(index_elements=["event_key"])
            .returning(NotificationEventModel.id)
        )
        event_id = (await session.execute(event_insert)).scalar_one_or_none()
        if event_id is None:
            existing_event = await session.scalar(
                select(NotificationEventModel).where(
                    NotificationEventModel.event_key == event_key
                )
            )
            if existing_event is None:
                raise RuntimeError("notification event could not be persisted")
            if not self._event_matches(
                existing_event,
                notification_type=notification_type,
                organization_id=organization_id,
                payload=payload,
                action=action,
                occurred_at=occurred_at,
                expires_at=expires_at,
            ):
                raise NotificationEventConflictError(
                    "notification event key already identifies a different event"
                )
            event_id = existing_event.id
        if event_id is None:
            raise RuntimeError("notification event could not be persisted")

        outbox_values = [
            {
                "event_id": event_id,
                "recipient_user_id": recipient_user_id,
                "channel": "in_app",
                "idempotency_key": f"{event_id}:in_app:{recipient_user_id}",
                "status": NotificationDeliveryStatus.PENDING.value,
                "next_attempt_at": occurred_at,
            }
            for recipient_user_id in recipient_user_ids
        ]
        outbox_insert = insert(NotificationOutboxModel).values(outbox_values)
        await session.execute(
            outbox_insert.on_conflict_do_nothing(
                index_elements=[
                    "event_id",
                    "recipient_user_id",
                    "channel",
                ]
            )
        )
        rows = (
            await session.execute(
                select(NotificationOutboxModel, NotificationEventModel)
                .join(
                    NotificationEventModel,
                    NotificationEventModel.id == NotificationOutboxModel.event_id,
                )
                .where(NotificationOutboxModel.event_id == event_id)
                .where(
                    NotificationOutboxModel.recipient_user_id.in_(recipient_user_ids)
                )
                .order_by(NotificationOutboxModel.id)
            )
        ).all()
        return NotificationEnqueueResult(
            event_id=event_id,
            deliveries=tuple(
                self._to_delivery(outbox, event) for outbox, event in rows
            ),
        )

    @staticmethod
    def _event_matches(
        event: NotificationEventModel,
        *,
        notification_type: NotificationType,
        organization_id: str | None,
        payload: dict[str, JsonValue],
        action: NotificationAction | None,
        occurred_at: datetime,
        expires_at: datetime | None,
    ) -> bool:
        return (
            event.notification_type == notification_type.value
            and event.organization_id == organization_id
            and event.payload == payload
            and event.action_type == (action.action_type if action else None)
            and event.action_ref == (action.action_ref if action else None)
            and event.occurred_at == occurred_at
            and event.expires_at == expires_at
        )

    async def deliver_in_app(
        self, *, delivery: NotificationDelivery
    ) -> NotificationInboxItem | None:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                inbox_insert = insert(NotificationInboxItemModel).values(
                    event_id=delivery.event_id,
                    recipient_user_id=delivery.recipient_user_id,
                )
                await session.execute(
                    inbox_insert.on_conflict_do_nothing(
                        index_elements=["event_id", "recipient_user_id"]
                    )
                )
                row = (
                    await session.execute(
                        select(NotificationInboxItemModel, NotificationEventModel)
                        .join(
                            NotificationEventModel,
                            NotificationEventModel.id
                            == NotificationInboxItemModel.event_id,
                        )
                        .where(NotificationInboxItemModel.event_id == delivery.event_id)
                        .where(
                            NotificationInboxItemModel.recipient_user_id
                            == delivery.recipient_user_id
                        )
                    )
                ).first()
                if row and row[1].organization_id is not None:
                    await self._audit.append_in_session(
                        session,
                        event=AuditEventDraft(
                            organization_id=row[1].organization_id,
                            actor_system="notification-worker",
                            action="notification.in_app.delivered",
                            outcome=AuditOutcome.SUCCESS,
                            target_type="notification_event",
                            target_id=row[1].id,
                            payload={"notification_type": row[1].notification_type},
                            correlation_id=row[1].correlation_id,
                            occurred_at=delivery.occurred_at,
                        ),
                    )
            return self._to_item(*row) if row else None

    async def claim_ready(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
        limit: int,
    ) -> list[NotificationDelivery]:
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await session.execute(
                    update(NotificationOutboxModel)
                    .where(
                        NotificationOutboxModel.status
                        == NotificationDeliveryStatus.LEASED.value
                    )
                    .where(NotificationOutboxModel.lease_expires_at <= now)
                    .values(
                        status=NotificationDeliveryStatus.PENDING.value,
                        lease_owner=None,
                        lease_expires_at=None,
                    )
                )
                rows = (
                    await session.execute(
                        select(NotificationOutboxModel, NotificationEventModel)
                        .join(
                            NotificationEventModel,
                            NotificationEventModel.id
                            == NotificationOutboxModel.event_id,
                        )
                        .where(
                            NotificationOutboxModel.status
                            == NotificationDeliveryStatus.PENDING.value
                        )
                        .where(NotificationOutboxModel.next_attempt_at <= now)
                        .order_by(
                            NotificationOutboxModel.next_attempt_at,
                            NotificationOutboxModel.id,
                        )
                        .with_for_update(skip_locked=True)
                        .limit(limit)
                    )
                ).all()
                for outbox, _event in rows:
                    outbox.status = NotificationDeliveryStatus.LEASED.value
                    outbox.lease_owner = worker_id
                    outbox.lease_expires_at = lease_expires_at
                    outbox.attempts += 1
                await session.flush()
            return [self._to_delivery(outbox, event) for outbox, event in rows]

    async def mark_delivered(
        self, *, delivery_id: str, worker_id: str, now: datetime
    ) -> bool:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                result = await session.execute(
                    update(NotificationOutboxModel)
                    .where(NotificationOutboxModel.id == delivery_id)
                    .where(
                        NotificationOutboxModel.status
                        == NotificationDeliveryStatus.LEASED.value
                    )
                    .where(NotificationOutboxModel.lease_owner == worker_id)
                    .where(NotificationOutboxModel.lease_expires_at > now)
                    .values(
                        status=NotificationDeliveryStatus.DELIVERED.value,
                        lease_owner=None,
                        lease_expires_at=None,
                        delivered_at=now,
                        last_error=None,
                    )
                )
            if result.rowcount == 0:
                existing = await session.get(NotificationOutboxModel, delivery_id)
                if (
                    existing is not None
                    and existing.status == NotificationDeliveryStatus.DELIVERED.value
                ):
                    return True
                raise NotificationOutboxLeaseError("notification outbox lease lost")
            return True

    async def mark_failed(
        self,
        *,
        delivery_id: str,
        worker_id: str,
        now: datetime,
        error: str,
        retryable: bool,
        max_attempts: int,
        base_backoff_seconds: int,
        max_backoff_seconds: int,
    ) -> NotificationDelivery | None:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                delivery = await session.get(
                    NotificationOutboxModel,
                    delivery_id,
                    with_for_update=True,
                )
                if (
                    delivery is None
                    or delivery.status != NotificationDeliveryStatus.LEASED.value
                    or delivery.lease_owner != worker_id
                    or delivery.lease_expires_at is None
                    or delivery.lease_expires_at <= now
                ):
                    raise NotificationOutboxLeaseError("notification outbox lease lost")
                safe_error = self._safe_error_code(error)
                terminal = not retryable or delivery.attempts >= max_attempts
                delivery.status = (
                    NotificationDeliveryStatus.DEAD_LETTER.value
                    if terminal
                    else NotificationDeliveryStatus.PENDING.value
                )
                delivery.next_attempt_at = now + timedelta(
                    seconds=(
                        0
                        if terminal
                        else min(
                            max_backoff_seconds,
                            base_backoff_seconds * (2 ** max(0, delivery.attempts - 1)),
                        )
                    )
                )
                delivery.lease_owner = None
                delivery.lease_expires_at = None
                delivery.last_error = safe_error
                if terminal:
                    delivery.dead_lettered_at = now
                await session.flush()
                event = await session.get(NotificationEventModel, delivery.event_id)
                if event is not None and event.organization_id is not None:
                    await self._audit.append_in_session(
                        session,
                        event=AuditEventDraft(
                            organization_id=event.organization_id,
                            actor_system="notification-worker",
                            action="notification.in_app.delivery_failed",
                            outcome=AuditOutcome.FAILURE,
                            target_type="notification_event",
                            target_id=event.id,
                            payload={
                                "notification_type": event.notification_type,
                                "retryable": retryable,
                                "terminal": terminal,
                                "error_code": safe_error,
                            },
                            correlation_id=event.correlation_id,
                            occurred_at=now,
                        ),
                    )
            return self._to_delivery(delivery, event) if event else None

    async def list_dead_letters(self, *, limit: int) -> list[NotificationDeadLetter]:
        async with AsyncSessionLocal() as session:
            rows = (
                await session.execute(
                    select(NotificationOutboxModel)
                    .where(
                        NotificationOutboxModel.status
                        == NotificationDeliveryStatus.DEAD_LETTER.value
                    )
                    .where(NotificationOutboxModel.dead_lettered_at.is_not(None))
                    .order_by(
                        NotificationOutboxModel.dead_lettered_at,
                        NotificationOutboxModel.id,
                    )
                    .limit(limit)
                )
            ).all()
        return [self._to_dead_letter(outbox) for (outbox,) in rows]

    async def replay_dead_letter(self, *, delivery_id: str, now: datetime) -> bool:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                result = await session.execute(
                    update(NotificationOutboxModel)
                    .where(NotificationOutboxModel.id == delivery_id)
                    .where(
                        NotificationOutboxModel.status
                        == NotificationDeliveryStatus.DEAD_LETTER.value
                    )
                    .values(
                        status=NotificationDeliveryStatus.PENDING.value,
                        attempts=0,
                        next_attempt_at=now,
                        lease_owner=None,
                        lease_expires_at=None,
                        last_error=None,
                        dead_lettered_at=None,
                    )
                )
            return result.rowcount == 1

    async def list_for_recipient(
        self, *, recipient_user_id: str, limit: int, now: datetime
    ) -> list[NotificationInboxItem]:
        async with AsyncSessionLocal() as session:
            rows = (
                await session.execute(
                    select(NotificationInboxItemModel, NotificationEventModel)
                    .join(
                        NotificationEventModel,
                        NotificationEventModel.id
                        == NotificationInboxItemModel.event_id,
                    )
                    .where(
                        NotificationInboxItemModel.recipient_user_id
                        == recipient_user_id
                    )
                    .where(
                        (NotificationEventModel.expires_at.is_(None))
                        | (NotificationEventModel.expires_at > now)
                    )
                    .order_by(
                        NotificationInboxItemModel.created_at.desc(),
                        NotificationInboxItemModel.id.desc(),
                    )
                    .limit(limit)
                )
            ).all()
        return [self._to_item(item, event) for item, event in rows]

    async def unread_count(self, *, recipient_user_id: str, now: datetime) -> int:
        async with AsyncSessionLocal() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(NotificationInboxItemModel)
                .join(
                    NotificationEventModel,
                    NotificationEventModel.id == NotificationInboxItemModel.event_id,
                )
                .where(
                    NotificationInboxItemModel.recipient_user_id == recipient_user_id
                )
                .where(NotificationInboxItemModel.read_at.is_(None))
                .where(
                    (NotificationEventModel.expires_at.is_(None))
                    | (NotificationEventModel.expires_at > now)
                )
            )
        return int(count or 0)

    async def mark_read(
        self, *, recipient_user_id: str, item_id: str, now: datetime
    ) -> NotificationInboxItem | None:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                updated = await session.execute(
                    update(NotificationInboxItemModel)
                    .where(NotificationInboxItemModel.id == item_id)
                    .where(
                        NotificationInboxItemModel.recipient_user_id
                        == recipient_user_id
                    )
                    .where(
                        NotificationInboxItemModel.event_id.in_(
                            select(NotificationEventModel.id).where(
                                (NotificationEventModel.expires_at.is_(None))
                                | (NotificationEventModel.expires_at > now)
                            )
                        )
                    )
                    .values(
                        read_at=func.coalesce(NotificationInboxItemModel.read_at, now)
                    )
                )
                if updated.rowcount != 1:
                    return None
                row = (
                    await session.execute(
                        select(NotificationInboxItemModel, NotificationEventModel)
                        .join(
                            NotificationEventModel,
                            NotificationEventModel.id
                            == NotificationInboxItemModel.event_id,
                        )
                        .where(NotificationInboxItemModel.id == item_id)
                    )
                ).one()
            return self._to_item(*row)

    @staticmethod
    def _to_delivery(
        outbox: NotificationOutboxModel, event: NotificationEventModel
    ) -> NotificationDelivery:
        action = None
        if event.action_type is not None and event.action_ref is not None:
            action = NotificationAction(
                action_type=event.action_type,
                action_ref=event.action_ref,
            )
        return NotificationDelivery(
            id=outbox.id,
            event_id=event.id,
            event_key=event.event_key,
            correlation_id=event.correlation_id,
            recipient_user_id=outbox.recipient_user_id,
            channel=outbox.channel,
            idempotency_key=outbox.idempotency_key,
            notification_type=NotificationType(event.notification_type),
            organization_id=event.organization_id,
            payload=dict(event.payload),
            action=action,
            occurred_at=event.occurred_at,
            expires_at=event.expires_at,
            status=NotificationDeliveryStatus(outbox.status),
            attempts=outbox.attempts,
            next_attempt_at=outbox.next_attempt_at,
            lease_owner=outbox.lease_owner,
            lease_expires_at=outbox.lease_expires_at,
            last_error=outbox.last_error,
            delivered_at=outbox.delivered_at,
            dead_lettered_at=outbox.dead_lettered_at,
        )

    @staticmethod
    def _to_dead_letter(outbox: NotificationOutboxModel) -> NotificationDeadLetter:
        if outbox.dead_lettered_at is None:
            raise RuntimeError("dead-lettered notification is missing its timestamp")
        return NotificationDeadLetter(
            id=outbox.id,
            event_id=outbox.event_id,
            recipient_user_id=outbox.recipient_user_id,
            channel=outbox.channel,
            idempotency_key=outbox.idempotency_key,
            status=NotificationDeliveryStatus(outbox.status),
            attempts=outbox.attempts,
            last_error=outbox.last_error,
            dead_lettered_at=outbox.dead_lettered_at,
        )

    @staticmethod
    def _safe_error_code(error: str) -> str:
        candidate = error.strip().lower()
        if re.fullmatch(_SAFE_ERROR_CODE_PATTERN, candidate) and not any(
            part in candidate
            for part in (
                "api",
                "authorization",
                "credential",
                "key",
                "password",
                "secret",
                "token",
            )
        ):
            return candidate
        return "delivery_failed"

    @staticmethod
    def _to_item(
        item: NotificationInboxItemModel, event: NotificationEventModel
    ) -> NotificationInboxItem:
        action = None
        if event.action_type is not None and event.action_ref is not None:
            action = NotificationAction(
                action_type=event.action_type,
                action_ref=event.action_ref,
            )
        return NotificationInboxItem(
            id=item.id,
            event_id=event.id,
            recipient_user_id=item.recipient_user_id,
            notification_type=NotificationType(event.notification_type),
            organization_id=event.organization_id,
            payload=dict(event.payload),
            action=action,
            read_at=item.read_at,
            created_at=item.created_at,
            expires_at=event.expires_at,
        )


class SqlAlchemyNotificationTransaction:
    def __init__(
        self,
        *,
        session: AsyncSession,
        repository: SqlAlchemyNotificationRepository | None = None,
    ) -> None:
        self._session = session
        self._repository = repository or SqlAlchemyNotificationRepository()

    async def enqueue(self, **kwargs: object) -> NotificationEnqueueResult:
        return await self._repository.enqueue_in_session(self._session, **kwargs)
