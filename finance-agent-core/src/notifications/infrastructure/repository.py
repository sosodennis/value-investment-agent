from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from src.infrastructure.database import AsyncSessionLocal
from src.notifications.application.ports import NotificationRepository
from src.notifications.domain.entities import (
    JsonValue,
    NotificationAction,
    NotificationInboxItem,
    NotificationType,
)
from src.notifications.domain.errors import NotificationEventConflictError

from .models import NotificationEventModel, NotificationInboxItemModel


class SqlAlchemyNotificationRepository(NotificationRepository):
    async def publish(
        self,
        *,
        event_key: str,
        notification_type: NotificationType,
        organization_id: str | None,
        payload: dict[str, JsonValue],
        action: NotificationAction | None,
        recipient_user_ids: Sequence[str],
        occurred_at: datetime,
        expires_at: datetime | None,
    ) -> list[NotificationInboxItem]:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                event_insert = (
                    insert(NotificationEventModel)
                    .values(
                        event_key=event_key,
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

                inbox_values = [
                    {"event_id": event_id, "recipient_user_id": recipient_user_id}
                    for recipient_user_id in recipient_user_ids
                ]
                inbox_insert = insert(NotificationInboxItemModel).values(inbox_values)
                await session.execute(
                    inbox_insert.on_conflict_do_nothing(
                        index_elements=["event_id", "recipient_user_id"]
                    )
                )
                rows = (
                    await session.execute(
                        select(NotificationInboxItemModel, NotificationEventModel)
                        .join(
                            NotificationEventModel,
                            NotificationEventModel.id
                            == NotificationInboxItemModel.event_id,
                        )
                        .where(NotificationInboxItemModel.event_id == event_id)
                        .where(
                            NotificationInboxItemModel.recipient_user_id.in_(
                                recipient_user_ids
                            )
                        )
                    )
                ).all()
            return [self._to_item(item, event) for item, event in rows]

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
