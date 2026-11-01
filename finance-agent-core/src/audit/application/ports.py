from __future__ import annotations

from collections.abc import Awaitable
from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.domain.entities import AuditEvent, AuditEventDraft, AuditEventPage


class AuditRepository(Protocol):
    async def append(self, *, event: AuditEventDraft) -> AuditEvent: ...

    def append_in_session(
        self, session: AsyncSession, *, event: AuditEventDraft
    ) -> Awaitable[AuditEvent]: ...

    async def list_for_organization(
        self,
        *,
        organization_id: str,
        limit: int,
        cursor: tuple[datetime, str] | None,
    ) -> AuditEventPage: ...
