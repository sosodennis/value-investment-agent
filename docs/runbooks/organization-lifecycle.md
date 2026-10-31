# Organization Lifecycle Runbook

Issue #204 owns organization lifecycle and member administration. The public
API is implemented by `finance-agent-core/src/auth/interface/organization_routes.py`
and the use cases live in `OrganizationService`.

## Ownership and Context

- Organization IDs and membership IDs are opaque server-generated identifiers.
- The active organization comes from the authenticated session and verified
  membership. A path organization ID is checked against that context before a
  use case reads or mutates data.
- Workflow runs, artifacts, history, and SSE resources remain user-owned.
- Organization creation creates an owner membership atomically. Selecting an
  organization continues to use the authenticated session endpoint.

## Membership Status Contract

| Current | Allowed next states | Notes |
| --- | --- | --- |
| `pending` | none | Invitation lifecycle owns pending state. |
| `active` | `suspended`, `removed` | Removing or suspending the last active owner is denied. |
| `suspended` | `active`, `removed` | Reactivation requires an owner/admin policy decision. |
| `removed` | none | A new invitation is required; no reactivation or role change. |

Role changes can assign `admin` or `member`. Ownership transfer is a separate
atomic operation that demotes the current owner and promotes one active member
under an organization row lock. At least one active owner must remain.

## Events

Lifecycle mutations append `auth_organization_lifecycle_events` records for
organization creation and rename, membership role/status changes, and ownership
transfer. Events contain actor, organization, target, typed event name, payload,
and UTC time; they do not contain credentials, invitation tokens, or provider
secrets. Issue #210 owns the later audit query and retention contract.

## Verification

Run from `finance-agent-core/`:

```bash
uv run pytest tests/auth/test_organization_service.py tests/auth/test_organization_routes.py -q
AUTH_POSTGRES_TEST=1 uv run pytest tests/auth/test_sql_organization_repository.py -q
uv run ruff check src/auth tests/auth
python3 scripts/architecture_guard.py
```

The PostgreSQL test must run against the isolated Compose project and verifies
row-lock behavior for concurrent ownership transfer, last-owner protection,
and event persistence. Reset only disposable local/staging data before a fresh
acceptance run; no compatibility migration or legacy provider backfill is
provided for this clean-cut organization model.

Update this runbook and the API schemas when membership statuses, role
transitions, lifecycle endpoints, event fields, ownership invariants, or the
session context contract change. Add allow/deny and concurrent database tests
with every such change.
