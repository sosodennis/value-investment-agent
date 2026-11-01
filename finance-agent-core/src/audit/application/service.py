from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.application.ports import AuditRepository
from src.audit.domain.entities import AuditEvent, AuditEventDraft
from src.auth.application.authorization_service import AuthorizationService
from src.auth.domain.authorization import (
    AuthorizationContext,
    AuthorizationResource,
    OrganizationPermission,
)
from src.auth.domain.entities import AuthenticatedContext


@dataclass(frozen=True, slots=True)
class AuditQueryResult:
    items: tuple[AuditEvent, ...]
    next_cursor: str | None


class AuditCursorError(ValueError):
    """Raised when a pagination cursor is malformed or tampered with."""


class AuditService:
    def __init__(
        self,
        *,
        repository: AuditRepository,
        authorization: AuthorizationService,
        cursor_secret: str,
    ) -> None:
        if not cursor_secret:
            raise ValueError("audit cursor secret is required")
        self._repository = repository
        self._authorization = authorization
        self._cursor_secret = cursor_secret.encode("utf-8")

    async def append(self, *, event: AuditEventDraft) -> AuditEvent:
        return await self._repository.append(event=event)

    async def append_in_session(
        self, session: AsyncSession, *, event: AuditEventDraft
    ) -> AuditEvent:
        return await self._repository.append_in_session(session, event=event)

    async def list_for_context(
        self,
        *,
        context: AuthenticatedContext,
        organization_id: str,
        limit: int,
        cursor: str | None,
    ) -> AuditQueryResult:
        self._authorization.require(
            context=AuthorizationContext.from_authenticated_context(context),
            permission=OrganizationPermission.ORGANIZATION_AUDIT_READ,
            resource=AuthorizationResource(organization_id=organization_id),
        )
        decoded_cursor = self._decode_cursor(cursor) if cursor else None
        page = await self._repository.list_for_organization(
            organization_id=organization_id,
            limit=limit,
            cursor=decoded_cursor,
        )
        next_cursor = (
            self._encode_cursor(page.next_cursor) if page.next_cursor else None
        )
        return AuditQueryResult(items=page.items, next_cursor=next_cursor)

    def _encode_cursor(self, cursor: tuple[datetime, str]) -> str:
        timestamp, event_id = cursor
        payload = json.dumps(
            {"occurred_at": _utc(timestamp).isoformat(), "id": event_id},
            separators=(",", ":"),
        ).encode("utf-8")
        encoded = _b64encode(payload)
        signature = hmac.new(self._cursor_secret, encoded.encode(), hashlib.sha256)
        return f"{encoded}.{_b64encode(signature.digest())}"

    def _decode_cursor(self, value: str) -> tuple[datetime, str]:
        try:
            encoded, signature = value.split(".", 1)
            expected = hmac.new(
                self._cursor_secret, encoded.encode(), hashlib.sha256
            ).digest()
            if not hmac.compare_digest(_b64decode(signature), expected):
                raise AuditCursorError("invalid audit cursor")
            data = json.loads(_b64decode(encoded))
            occurred_at = datetime.fromisoformat(str(data["occurred_at"]))
            event_id = str(data["id"])
            if not event_id or len(event_id) > 128:
                raise AuditCursorError("invalid audit cursor")
            return _utc(occurred_at), event_id
        except (
            AuditCursorError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            if isinstance(error, AuditCursorError):
                raise
            raise AuditCursorError("invalid audit cursor") from error


def audit_cursor_secret() -> str:
    configured = os.getenv("AUDIT_CURSOR_SECRET", "").strip()
    if configured:
        return configured
    environment = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "production")).lower()
    if environment in {"development", "dev", "test"}:
        return "local-development-only-audit-cursor-secret"
    raise RuntimeError("AUDIT_CURSOR_SECRET is required")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
