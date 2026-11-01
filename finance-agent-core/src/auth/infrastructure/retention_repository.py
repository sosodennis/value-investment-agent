from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select

from src.audit.domain.entities import AuditEventDraft, AuditOutcome
from src.audit.infrastructure.repository import SqlAlchemyAuditRepository
from src.auth.application.invitation_ports import InvitationRetentionRepository
from src.auth.infrastructure.models import InvitationModel
from src.infrastructure.database import AsyncSessionLocal
from src.notifications.infrastructure.models import NotificationEventModel


class SqlAlchemyInvitationRetentionRepository(InvitationRetentionRepository):
    def __init__(self, *, batch_limit: int = 100) -> None:
        if not 1 <= batch_limit <= 1_000:
            raise ValueError("invitation retention batch size is invalid")
        self._batch_limit = batch_limit
        self._audit = SqlAlchemyAuditRepository()

    async def expire_and_purge(
        self,
        *,
        now: datetime,
        terminal_before: datetime,
        limit: int,
    ) -> tuple[int, int]:
        bounded_limit = min(limit, self._batch_limit)
        if not 1 <= bounded_limit <= 1_000:
            raise ValueError("invitation retention batch size is invalid")
        async with AsyncSessionLocal() as session:
            async with session.begin():
                pending = list(
                    (
                        await session.scalars(
                            select(InvitationModel)
                            .where(InvitationModel.status == "pending")
                            .where(InvitationModel.expires_at <= now)
                            .order_by(InvitationModel.expires_at, InvitationModel.id)
                            .limit(bounded_limit)
                            .with_for_update(skip_locked=True)
                        )
                    ).all()
                )
                for invitation in pending:
                    invitation.status = "expired"
                    invitation.updated_at = now
                    event = await session.get(
                        NotificationEventModel, invitation.notification_event_id
                    )
                    correlation_id = None
                    if event is not None:
                        payload = dict(event.payload)
                        payload.update({"status": "expired", "outcome": "expired"})
                        event.payload = payload
                        event.expires_at = None
                        correlation_id = event.correlation_id
                    await self._audit.append_in_session(
                        session,
                        event=AuditEventDraft(
                            organization_id=invitation.organization_id,
                            actor_system="invitation-retention-worker",
                            action="invitation.expired",
                            outcome=AuditOutcome.SUCCESS,
                            target_type="invitation",
                            target_id=invitation.id,
                            payload={"status": "expired"},
                            correlation_id=correlation_id,
                            occurred_at=now,
                        ),
                    )
                terminal_ids = list(
                    await session.scalars(
                        select(InvitationModel.id)
                        .where(
                            InvitationModel.status.in_(
                                ("accepted", "declined", "expired", "revoked")
                            )
                        )
                        .where(InvitationModel.updated_at <= terminal_before)
                        .order_by(InvitationModel.updated_at, InvitationModel.id)
                        .limit(bounded_limit)
                        .with_for_update(skip_locked=True)
                    )
                )
                purged = 0
                if terminal_ids:
                    result = await session.execute(
                        delete(InvitationModel).where(
                            InvitationModel.id.in_(terminal_ids)
                        )
                    )
                    purged = int(result.rowcount or 0)
            return len(pending), purged
