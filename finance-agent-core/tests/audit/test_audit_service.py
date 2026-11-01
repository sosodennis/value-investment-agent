from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.audit.application.service import AuditCursorError, AuditService
from src.audit.domain.entities import (
    AuditActorType,
    AuditEvent,
    AuditEventDraft,
    AuditEventPage,
    AuditOutcome,
)
from src.audit.domain.redaction import REDACTED, redact_payload
from src.auth.application.authorization_service import AuthorizationService
from src.auth.application.errors import AuthorizationDeniedError
from src.auth.domain.entities import (
    AuthenticatedContext,
    MembershipRecord,
    MembershipRole,
    MembershipStatus,
    SessionRecord,
    UserRecord,
)


class MemoryAuditRepository:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def append(self, *, event: AuditEventDraft) -> AuditEvent:
        item = AuditEvent(
            id=f"event-{len(self.events) + 1}",
            organization_id=event.organization_id,
            actor_type=AuditActorType.USER
            if event.actor_user_id
            else AuditActorType.SYSTEM,
            actor_user_id=event.actor_user_id,
            actor_system=event.actor_system,
            action=event.action,
            target_type=event.target_type,
            target_id=event.target_id,
            outcome=event.outcome,
            correlation_id=event.correlation_id or f"corr-{len(self.events) + 1}",
            payload=event.payload,
            occurred_at=event.occurred_at or datetime.now(UTC),
        )
        self.events.append(item)
        return item

    async def append_in_session(self, session, *, event: AuditEventDraft) -> AuditEvent:
        return await self.append(event=event)

    async def list_for_organization(self, *, organization_id, limit, cursor):
        items = [
            item for item in self.events if item.organization_id == organization_id
        ]
        items.sort(key=lambda item: (item.occurred_at, item.id), reverse=True)
        if cursor:
            items = [item for item in items if (item.occurred_at, item.id) < cursor]
        page = items[: limit + 1]
        has_more = len(page) > limit
        page = page[:limit]
        return AuditEventPage(
            items=tuple(page),
            next_cursor=(page[-1].occurred_at, page[-1].id) if has_more else None,
        )


def _context(*, role: MembershipRole = MembershipRole.OWNER) -> AuthenticatedContext:
    now = datetime.now(UTC)
    user = UserRecord("user-1", "owner@example.test", "hash", now, "Owner")
    return AuthenticatedContext(
        user=user,
        session=SessionRecord(
            "session-1",
            user.id,
            "org-1",
            "token",
            "csrf",
            now + timedelta(hours=1),
            None,
            now,
        ),
        membership=MembershipRecord(
            "membership-1", "org-1", user.id, role, MembershipStatus.ACTIVE, now, now
        ),
    )


@pytest.mark.asyncio
async def test_audit_query_is_bounded_ordered_and_cursor_signed() -> None:
    repository = MemoryAuditRepository()
    service = AuditService(
        repository=repository,
        authorization=AuthorizationService(),
        cursor_secret="test-secret",
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(3):
        await service.append(
            event=AuditEventDraft(
                organization_id="org-1",
                actor_user_id="user-1",
                action=f"membership.change.{index}",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now + timedelta(minutes=index),
            )
        )
    first = await service.list_for_context(
        context=_context(), organization_id="org-1", limit=2, cursor=None
    )
    assert [item.action for item in first.items] == [
        "membership.change.2",
        "membership.change.1",
    ]
    assert first.next_cursor
    second = await service.list_for_context(
        context=_context(), organization_id="org-1", limit=2, cursor=first.next_cursor
    )
    assert [item.action for item in second.items] == ["membership.change.0"]
    with pytest.raises(AuditCursorError):
        await service.list_for_context(
            context=_context(),
            organization_id="org-1",
            limit=2,
            cursor=first.next_cursor[:-1] + "x",
        )


@pytest.mark.asyncio
async def test_members_cannot_read_audit_events() -> None:
    service = AuditService(
        repository=MemoryAuditRepository(),
        authorization=AuthorizationService(),
        cursor_secret="test-secret",
    )
    with pytest.raises(AuthorizationDeniedError):
        await service.list_for_context(
            context=_context(role=MembershipRole.MEMBER),
            organization_id="org-1",
            limit=10,
            cursor=None,
        )


@pytest.mark.asyncio
async def test_owner_cannot_read_a_different_organization() -> None:
    service = AuditService(
        repository=MemoryAuditRepository(),
        authorization=AuthorizationService(),
        cursor_secret="test-secret",
    )
    with pytest.raises(AuthorizationDeniedError):
        await service.list_for_context(
            context=_context(),
            organization_id="org-2",
            limit=10,
            cursor=None,
        )


def test_audit_payload_redaction_removes_credentials_and_action_material() -> None:
    payload = redact_payload(
        {
            "provider_api_key": "secret",
            "invitation_action_ref": "opaque-token",
            "nested": {"password": "secret", "status": "accepted"},
            "safe": "value",
        }
    )
    assert payload["provider_api_key"] == REDACTED
    assert payload["invitation_action_ref"] == REDACTED
    assert payload["nested"]["password"] == REDACTED
    assert payload["nested"]["status"] == "accepted"
