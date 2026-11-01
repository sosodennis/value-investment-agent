# Notification Inbox Runbook

Issue #207 owns the durable recipient-private notification service. The public
API is implemented by `finance-agent-core/src/notifications/interface/routes.py`;
future invitation use cases publish through `NotificationService` instead of
writing inbox rows directly.

## Data Model

- `notification_events` stores one durable event per opaque `event_key`.
- `notification_inbox_items` stores one recipient delivery per event and
  recipient pair.
- `organization_id` is optional metadata. It never grants access to an inbox.
- `read_at` is recipient-owned state. Expired events remain durable for
  inspection but are excluded from list, unread count, and mark-read results.
- Payloads are bounded JSON objects. Credential-like keys such as token,
  secret, password, cookie, credential, authorization, and API key are rejected.
  Credential-bearing values, bearer strings, provider-key prefixes, and URLs
  with credential query parameters are rejected too.
- Invitation action references contain an opaque `action_type` and
  `action_ref`; both use the safe identifier alphabet and cannot contain
  invitation tokens, URLs, or query material.
- Event timestamps are aware UTC values. Public responses always carry a UTC
  offset, and naive timestamps are rejected at the application boundary.

The event key and `(event_id, recipient_user_id)` uniqueness constraints make
retries idempotent. Reusing an event key with different event data is rejected
as a conflict. Read updates use `COALESCE(read_at, now)` under a database row
update, so concurrent mark-read calls converge on one read state.

## API

| Method | Route | Contract |
| --- | --- | --- |
| `GET` | `/api/v1/notifications?limit=50` | Recipient's active inbox items and unread count |
| `GET` | `/api/v1/notifications/unread-count` | Recipient's current unread count |
| `PATCH` | `/api/v1/notifications/{notification_id}/read` | Idempotently mark one recipient-owned item read |

Read routes authenticate the session and bind the recipient to the server
resolved user ID. Mutations also require CSRF proof. A foreign or expired item
returns the same `404 notification_not_found` response as an unknown item.

## Delivery Boundary

`NotificationDeliveryAdapter` is the extension point for future delivery
surfaces. The current `InAppNotificationDeliveryAdapter` deliberately has no
external side effect because the durable inbox is the only supported delivery
surface. Do not add SMTP, email, SMS, browser push, or provider calls to this
capability without a separate contract and issue.

## Verification

Run from `finance-agent-core/`:

```bash
uv run pytest tests/notifications/test_service.py tests/notifications/test_routes.py -q
NOTIFICATION_POSTGRES_TEST=1 uv run pytest tests/notifications/test_sql_repository.py -q
uv run ruff check src/notifications tests/notifications
uv run ruff format --check src/notifications tests/notifications
```

The PostgreSQL test must use the isolated disposable Compose database. It
covers recipient isolation, organization metadata, duplicate event delivery,
concurrent read updates, unread counts, and expired inbox items.

Update this runbook and the OpenAPI contract when notification types, payload
redaction rules, action references, routes, retention semantics, or delivery
adapter behavior changes. Add contract, authorization, and concurrency tests
with each such change. Retention jobs are owned by #211; invitation lifecycle
and acceptance are owned by #209.
