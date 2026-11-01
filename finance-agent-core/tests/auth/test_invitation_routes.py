from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI

from src.auth.application.errors import AuthorizationDeniedError
from src.auth.application.invitation_errors import InvitationNotFoundError
from src.auth.application.wiring import get_invitation_service
from src.auth.domain.entities import (
    AuthenticatedActorContext,
    AuthenticatedContext,
    MembershipRecord,
    MembershipRole,
    MembershipStatus,
    SessionRecord,
    UserRecord,
)
from src.auth.domain.invitations import (
    InvitationOperation,
    InvitationRecord,
    InvitationStatus,
)
from src.auth.interface.dependencies import (
    current_actor,
    require_current_actor_mutation,
    require_current_context_mutation,
)
from src.auth.interface.invitation_routes import router


def _user(user_id: str) -> UserRecord:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return UserRecord(
        id=user_id,
        email=f"{user_id}@example.test",
        password_hash="unused",
        created_at=now,
        display_name=user_id.title(),
    )


def _context(
    user_id: str = "owner", role: MembershipRole = MembershipRole.OWNER
) -> AuthenticatedContext:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    membership = MembershipRecord(
        id="membership-1",
        organization_id="organization-1",
        user_id=user_id,
        role=role,
        status=MembershipStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    return AuthenticatedContext(
        user=_user(user_id),
        membership=membership,
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


def _record(status: InvitationStatus = InvitationStatus.PENDING) -> InvitationRecord:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return InvitationRecord(
        id="invitation-1",
        organization_id="organization-1",
        organization_name="Alpha",
        inviter_user_id="owner",
        inviter_display_name="Owner",
        recipient_user_id="recipient",
        recipient_display_name="Recipient",
        requested_role="member",
        status=status,
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(days=7),
        revision=1,
        notification_event_id="event-1",
    )


class StubInvitationService:
    def __init__(self) -> None:
        self.created: list[tuple[str, str]] = []
        self.transitions: list[tuple[str, InvitationOperation, str]] = []

    async def create(
        self,
        *,
        context,
        organization_id,
        recipient_user_id,
        requested_role,
        idempotency_key,
        now,
    ):
        self.created.append((recipient_user_id, idempotency_key))
        return _record()

    async def list_for_organization(self, *, context, organization_id, now):
        return [_record()]

    async def get_for_actor(self, *, actor, organization_id, invitation_id, now):
        if actor.user.id != "recipient":
            raise InvitationNotFoundError("invitation not found")
        return _record()

    async def transition_for_recipient(
        self, *, actor, organization_id, invitation_id, operation, idempotency_key, now
    ):
        if actor.user.id != "recipient":
            raise InvitationNotFoundError("invitation not found")
        self.transitions.append((actor.user.id, operation, idempotency_key))
        return _record(
            InvitationStatus.ACCEPTED
            if operation is InvitationOperation.ACCEPT
            else InvitationStatus.DECLINED
        )


@pytest.mark.asyncio
async def test_invitation_routes_bind_manager_and_recipient_idempotency() -> None:
    service = StubInvitationService()
    context = _context()
    recipient = AuthenticatedActorContext(
        user=_user("recipient"), session=context.session
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_invitation_service] = lambda: service
    app.dependency_overrides[require_current_context_mutation] = lambda: context
    app.dependency_overrides[current_actor] = lambda: recipient
    app.dependency_overrides[require_current_actor_mutation] = lambda: recipient

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post(
            "/api/v1/organizations/organization-1/invitations",
            headers={"Idempotency-Key": "create-0001"},
            json={"recipient_user_id": "recipient", "role": "member"},
        )
        accepted = await client.post(
            "/api/v1/organizations/organization-1/invitations/invitation-1/accept",
            headers={"Idempotency-Key": "accept-0001"},
        )

    assert created.status_code == 201
    assert service.created == [("recipient", "create-0001")]
    assert accepted.status_code == 200
    assert service.transitions == [
        ("recipient", InvitationOperation.ACCEPT, "accept-0001")
    ]
    assert "recipient_user_id" in created.json()


@pytest.mark.asyncio
async def test_invitation_lookup_hides_non_recipient() -> None:
    service = StubInvitationService()
    context = _context()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_invitation_service] = lambda: service
    app.dependency_overrides[current_actor] = lambda: AuthenticatedActorContext(
        user=_user("other"), session=context.session
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/api/v1/organizations/organization-1/invitations/invitation-1"
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "invitation_not_found"}


@pytest.mark.asyncio
async def test_invitation_service_denial_records_verified_organization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = StubInvitationService()

    async def denied_create(**_kwargs):
        raise AuthorizationDeniedError("role_transition_not_allowed")

    service.create = denied_create  # type: ignore[method-assign]
    context = _context()
    denied_events: list[dict[str, object]] = []

    async def capture_denied_event(**kwargs: object) -> None:
        denied_events.append(kwargs)

    monkeypatch.setattr(
        "src.audit.application.recording.record_best_effort", capture_denied_event
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_invitation_service] = lambda: service
    app.dependency_overrides[require_current_context_mutation] = lambda: context

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/organizations/organization-1/invitations",
            headers={"Idempotency-Key": "create-denied-1"},
            json={"recipient_user_id": "recipient", "role": "member"},
        )

    assert response.status_code == 403
    assert denied_events[-1]["organization_id"] == "organization-1"
