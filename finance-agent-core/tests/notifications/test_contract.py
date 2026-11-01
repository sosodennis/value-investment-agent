from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from api.server import app
from src.notifications.domain.entities import (
    NotificationAction,
    NotificationInboxItem,
    NotificationType,
)
from src.notifications.interface.routes import _response


def test_checked_in_openapi_matches_notification_runtime_paths() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    checked_in = json.loads(
        (repository_root / "contracts" / "openapi.json").read_text(encoding="utf-8")
    )
    runtime = app.openapi()
    paths = {
        "/api/v1/notifications",
        "/api/v1/notifications/unread-count",
        "/api/v1/notifications/{notification_id}/read",
    }
    assert {path: runtime["paths"][path] for path in paths} == {
        path: checked_in["paths"][path] for path in paths
    }


def test_notification_response_serializes_utc_offset() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    response = _response(
        NotificationInboxItem(
            id="inbox-1",
            event_id="event-1",
            recipient_user_id="user-1",
            notification_type=NotificationType.SYSTEM,
            organization_id=None,
            payload={"message": "safe"},
            action=NotificationAction(
                action_type="system.notice", action_ref="opaque-reference"
            ),
            read_at=None,
            created_at=timestamp,
            expires_at=timestamp + timedelta(days=1),
        )
    )
    assert response.model_dump(mode="json")["created_at"].endswith("Z")
