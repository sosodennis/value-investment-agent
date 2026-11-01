from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from src.auth.domain.entities import (
    AuthenticatedActorContext,
    SessionRecord,
    UserRecord,
)
from src.auth.interface.dependencies import (
    current_actor,
    require_current_actor_mutation,
)
from src.notifications.application.wiring import get_notification_service
from src.notifications.domain.entities import (
    NotificationAction,
    NotificationInboxItem,
    NotificationType,
)
from src.notifications.domain.errors import NotificationNotFoundError
from src.notifications.interface.dependencies import (
    current_notification_recipient,
    current_notification_recipient_mutation,
)
from src.notifications.interface.routes import router


def _actor(user_id: str = "user-recipient") -> AuthenticatedActorContext:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return AuthenticatedActorContext(
        user=UserRecord(
            id=user_id,
            email=f"{user_id}@example.test",
            password_hash="unused",
            created_at=now,
            display_name="Recipient",
        ),
        session=SessionRecord(
            id="session-1",
            user_id=user_id,
            active_organization_id="organization-1",
            token_hash="token",
            csrf_token_hash="csrf",
            expires_at=now + timedelta(hours=1),
            revoked_at=None,
            created_at=now,
        ),
    )


def _item(item_id: str = "inbox-1") -> NotificationInboxItem:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return NotificationInboxItem(
        id=item_id,
        event_id="event-1",
        recipient_user_id="user-recipient",
        notification_type=NotificationType.ORGANIZATION_INVITATION,
        organization_id="organization-1",
        payload={"organization_name": "Alpha team"},
        action=NotificationAction(
            action_type="organization.invitation", action_ref="invitation-1"
        ),
        read_at=None,
        created_at=now,
        expires_at=now + timedelta(days=7),
    )


class StubNotificationService:
    def __init__(self) -> None:
        self.recipient_ids: list[str] = []
        self.marked: list[tuple[str, str]] = []
        self.item = _item()

    async def list_for_recipient(self, *, recipient_user_id, limit, now):
        self.recipient_ids.append(recipient_user_id)
        return [self.item]

    async def unread_count(self, *, recipient_user_id, now):
        self.recipient_ids.append(recipient_user_id)
        return 1

    async def mark_read(self, *, recipient_user_id, item_id, now):
        self.marked.append((recipient_user_id, item_id))
        if item_id != self.item.id:
            raise NotificationNotFoundError("notification not found")
        return self.item


@pytest.mark.asyncio
async def test_notification_routes_bind_recipient_and_keep_action_reference_opaque() -> (
    None
):
    service = StubNotificationService()
    actor = _actor()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_notification_service] = lambda: service
    app.dependency_overrides[current_notification_recipient] = lambda: actor
    app.dependency_overrides[current_notification_recipient_mutation] = lambda: actor
    app.dependency_overrides[current_actor] = lambda: actor
    app.dependency_overrides[require_current_actor_mutation] = lambda: actor

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        listing = await client.get("/api/v1/notifications")
        unread = await client.get("/api/v1/notifications/unread-count")
        marked = await client.patch("/api/v1/notifications/inbox-1/read")

    assert listing.status_code == 200
    assert listing.json()["items"][0]["action"] == {
        "action_type": "organization.invitation",
        "action_ref": "invitation-1",
    }
    assert "recipient_user_id" not in listing.json()["items"][0]
    assert unread.json() == {"unread_count": 1}
    assert marked.status_code == 200
    assert service.recipient_ids == [
        "user-recipient",
        "user-recipient",
        "user-recipient",
    ]
    assert service.marked == [("user-recipient", "inbox-1")]


@pytest.mark.asyncio
async def test_notification_routes_return_404_for_an_unowned_or_unknown_item() -> None:
    service = StubNotificationService()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_notification_recipient_mutation] = lambda: _actor()

    app.dependency_overrides[get_notification_service] = lambda: service

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.patch("/api/v1/notifications/foreign/read")

    assert response.status_code == 404
    assert response.json() == {"detail": "notification_not_found"}


@pytest.mark.asyncio
async def test_notification_routes_require_authentication() -> None:
    app = FastAPI()
    app.include_router(router)

    def unauthenticated() -> AuthenticatedActorContext:
        raise HTTPException(status_code=401, detail="authentication is required")

    app.dependency_overrides[current_notification_recipient] = unauthenticated
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/v1/notifications")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_notification_routes_use_real_recipient_only_policy() -> None:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_actor] = lambda: _actor("user-recipient")
    app.dependency_overrides[get_notification_service] = (
        lambda: StubNotificationService()
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/v1/notifications")

    assert response.status_code == 200
    assert response.json()["items"][0]["notification_id"] == "inbox-1"
