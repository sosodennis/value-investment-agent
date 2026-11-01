from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.auth.domain.invitations import InvitationOperation, InvitationRecord


class InvitationRepository(Protocol):
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
    ) -> InvitationRecord: ...

    async def list_for_organization(
        self, *, organization_id: str, now: datetime
    ) -> list[InvitationRecord]: ...

    async def get_for_actor(
        self,
        *,
        organization_id: str,
        invitation_id: str,
        actor_user_id: str,
        now: datetime,
    ) -> InvitationRecord | None: ...

    async def transition(
        self,
        *,
        organization_id: str,
        invitation_id: str,
        actor_user_id: str,
        operation: InvitationOperation,
        idempotency_key: str,
        now: datetime,
    ) -> InvitationRecord: ...


class InvitationRetentionRepository(Protocol):
    async def expire_and_purge(
        self,
        *,
        now: datetime,
        terminal_before: datetime,
        limit: int,
    ) -> tuple[int, int]: ...
