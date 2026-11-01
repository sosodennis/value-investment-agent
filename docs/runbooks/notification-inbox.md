# Notification Inbox Runbook

Issues #207 and #208 own the durable recipient-private notification service and
its transactional outbox. The public
API is implemented by `finance-agent-core/src/notifications/interface/routes.py`;
future invitation use cases publish through `NotificationService` instead of
writing inbox rows directly.

## Data Model

- `notification_events` stores one durable event per opaque `event_key`.
- `notification_inbox_items` stores one recipient delivery per event and
  recipient pair.
- `notification_outbox` stores one in-app delivery attempt per event and
  recipient. The source transaction commits the event and pending outbox rows
  together; the worker claims rows with a PostgreSQL lease before calling the
  in-app adapter.
- `organization_id` is optional metadata. It never grants access to an inbox.
- `read_at` is recipient-owned state. Events whose delivery has expired are
  excluded from list, unread count, and mark-read results. Invitation events
  clear their delivery expiry when they reach a terminal outcome so the
  recipient can still see the final accepted, declined, expired, or revoked
  result in the inbox.
- Payloads are bounded JSON objects. Credential-like keys such as token,
  secret, password, cookie, credential, authorization, and API key are rejected.
  Credential-bearing values, bearer strings, provider-key prefixes, and URLs
  with credential query parameters are rejected too.
- Invitation action references contain an opaque `action_type` and
  `action_ref`; both use the safe identifier alphabet and cannot contain
  invitation tokens, URLs, or query material.
- Event timestamps are aware UTC values. Public responses always carry a UTC
  offset, and naive timestamps are rejected at the application boundary.

The event key, outbox idempotency key, and `(event_id, recipient_user_id)`
uniqueness constraints make retries and replay idempotent. Reusing an event
key with different event data is rejected as a conflict. Leases expire back to
pending, retry delays use bounded exponential backoff, and terminal failures
become inspectable dead letters. Replaying a dead letter resets only its
delivery state; the inbox uniqueness constraint prevents duplicate items. Read
updates use `COALESCE(read_at, now)` under a database row update, so concurrent
mark-read calls converge on one read state.

Dead-letter listing and replay are internal operations capabilities, not
recipient-facing routes. `list_dead_letters` returns only the delivery identity,
status, attempt count, safe error code, and timestamps; it never returns event
payload or action metadata. Any future operations endpoint must add an explicit
operator authorization contract before exposing these capabilities.

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
surfaces. The current `InAppNotificationDeliveryAdapter` writes the durable
inbox and is the only supported delivery surface. The worker runs from the
FastAPI lifespan with bounded batches and leases. Do not add SMTP, email, SMS,
browser push, or provider calls to this capability without a separate
contract and issue.

## Verification

Run from `finance-agent-core/`:

```bash
uv run pytest tests/notifications/test_service.py tests/notifications/test_routes.py -q
NOTIFICATION_POSTGRES_TEST=1 uv run pytest tests/notifications/test_sql_repository.py -q
uv run pytest tests/notifications/test_outbox.py -q
uv run ruff check src/notifications tests/notifications
uv run ruff format --check src/notifications tests/notifications
```

The PostgreSQL test must use the isolated disposable Compose database. It
covers recipient isolation, organization metadata, duplicate event delivery,
concurrent workers and read updates, retry/dead-letter/replay, unread counts,
and expired delivery filtering. Invitation integration tests additionally
verify that terminal invitation outcomes remain visible in the recipient's
inbox. CI runs the same test through the dedicated
`notification-postgres-integration` job.

Update this runbook and the OpenAPI contract when notification types, payload
redaction rules, action references, routes, retention semantics, or delivery
adapter behavior changes. Add contract, authorization, and concurrency tests
with each such change. Retention jobs are owned by #211; invitation lifecycle
and acceptance are owned by #209.
