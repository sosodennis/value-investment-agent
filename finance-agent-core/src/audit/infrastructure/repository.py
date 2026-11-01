from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.application.ports import AuditRepository
from src.audit.domain.entities import (
    AuditActorType,
    AuditEvent,
    AuditEventDraft,
    AuditEventPage,
    AuditOutcome,
)
from src.audit.domain.redaction import redact_payload
from src.auth.infrastructure.models import OrganizationModel, UserModel
from src.infrastructure.database import AsyncSessionLocal

from .models import AuditEventModel, utc_now


class SqlAlchemyAuditRepository(AuditRepository):
    async def append(self, *, event: AuditEventDraft) -> AuditEvent:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                return await self.append_in_session(session, event=event)

    async def append_in_session(
        self, session: AsyncSession, *, event: AuditEventDraft
    ) -> AuditEvent:
        actor_type, actor_user_id, actor_system = self._actor(event)
        organization_exists = await session.scalar(
            select(OrganizationModel.id).where(
                OrganizationModel.id == event.organization_id
            )
        )
        if organization_exists is None:
            raise ValueError("audit organization does not exist")
        if actor_user_id is not None:
            actor_exists = await session.scalar(
                select(UserModel.id).where(UserModel.id == actor_user_id)
            )
            if actor_exists is None:
                raise ValueError("audit actor user does not exist")
        occurred_at = _utc(event.occurred_at or utc_now())
        correlation_id = event.correlation_id or str(uuid.uuid4())
        if len(event.action) > 120 or not event.action.strip():
            raise ValueError(
                "audit action must be a non-empty value of at most 120 characters"
            )
        if len(correlation_id) > 128:
            raise ValueError("audit correlation_id is too long")
        model = AuditEventModel(
            id=str(uuid.uuid4()),
            organization_id=event.organization_id,
            actor_type=actor_type.value,
            actor_user_id=actor_user_id,
            actor_system=actor_system,
            action=event.action,
            target_type=event.target_type,
            target_id=event.target_id,
            outcome=event.outcome.value,
            correlation_id=correlation_id,
            payload=redact_payload(event.payload),
            occurred_at=occurred_at,
        )
        session.add(model)
        await session.flush()
        return self._to_event(model)

    async def list_for_organization(
        self,
        *,
        organization_id: str,
        limit: int,
        cursor: tuple[datetime, str] | None,
    ) -> AuditEventPage:
        if limit < 1 or limit > 100:
            raise ValueError("audit limit must be between 1 and 100")
        statement = (
            select(AuditEventModel)
            .where(AuditEventModel.organization_id == organization_id)
            .order_by(AuditEventModel.occurred_at.desc(), AuditEventModel.id.desc())
            .limit(limit + 1)
        )
        if cursor is not None:
            cursor_time, cursor_id = cursor
            statement = statement.where(
                or_(
                    AuditEventModel.occurred_at < cursor_time,
                    and_(
                        AuditEventModel.occurred_at == cursor_time,
                        AuditEventModel.id < cursor_id,
                    ),
                )
            )
        async with AsyncSessionLocal() as session:
            models = list((await session.scalars(statement)).all())
        has_more = len(models) > limit
        items = models[:limit]
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = _utc(last.occurred_at), last.id
        return AuditEventPage(
            items=tuple(self._to_event(item) for item in items),
            next_cursor=next_cursor,
        )

    @staticmethod
    def _actor(
        event: AuditEventDraft,
    ) -> tuple[AuditActorType, str | None, str | None]:
        has_user = bool(event.actor_user_id)
        has_system = bool(event.actor_system)
        if has_user == has_system:
            raise ValueError("audit event requires exactly one actor identity")
        if has_user:
            return AuditActorType.USER, event.actor_user_id, None
        return AuditActorType.SYSTEM, None, event.actor_system

    @staticmethod
    def _to_event(model: AuditEventModel) -> AuditEvent:
        return AuditEvent(
            id=model.id,
            organization_id=model.organization_id,
            actor_type=AuditActorType(model.actor_type),
            actor_user_id=model.actor_user_id,
            actor_system=model.actor_system,
            action=model.action,
            target_type=model.target_type,
            target_id=model.target_id,
            outcome=AuditOutcome(model.outcome),
            correlation_id=model.correlation_id,
            payload=dict(model.payload),
            occurred_at=_utc(model.occurred_at),
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
