# Organization audit trail runbook

The organization audit trail is stored in `auth_audit_events`. It is an
append-only record of security-relevant organization activity. Events carry the
organization, actor (user or named system actor), action, target, outcome,
correlation ID, UTC event time, and a redacted JSON payload.

## Query boundary

`GET /api/v1/organizations/{organization_id}/audit-events` requires the
`organization.audit.read` permission. Owners and admins can read only the
organization in their verified session context. Members, removed users,
forged actors, and cross-organization requests are denied or hidden by the
authorization contract. Results are capped at 100 records and use a signed
cursor ordered by `(occurred_at DESC, id DESC)`.

Production deployments must provide the required `AUDIT_CURSOR_SECRET` to the
backend. The production Compose overlay fails before startup when it is absent;
staging and local environments generate or explicitly configure an equivalent
per-environment secret.

## Data handling

The writer redacts keys containing secrets, tokens, passwords, credentials,
authorization values, API keys, private keys, invitation action material, and
invitation codes before persistence. Application code has no update or delete
operation for audit events. PostgreSQL installs a trigger that rejects direct
updates and deletes as a second boundary.

Audit payloads must contain investigation metadata only. Never add provider
keys, session tokens, CSRF values, invitation action references, passwords, or
raw request headers. Every HTTP request receives a bounded `X-Request-ID`
correlation value at the API boundary; a valid inbound value is echoed in the
response and reused by all audit events created during that request. Missing or
oversized values receive a fresh identifier. Notification outbox events persist
the same correlation value so worker logs and delivery audit events can be
joined to the originating request. Autonomous work receives a fresh identifier
at its persistence boundary.

The `notification_events.correlation_id` column is part of the fresh target
schema. Because this epic uses a clean-cut organization model, reset only
disposable local or staging databases before applying the target schema; do not
introduce a compatibility migration, dual read/write path, or legacy backfill.
Any retained database needs the explicit provider/data disposition tracked by
#215 before rollout.

Provider key events emitted before the organization-scoped provider slices
(`#213` and `#214`) are complete identify the verified active organization
context and include the provider resource scope as metadata. They do not grant
organization ownership over the current user-scoped provider resource; the
provider cutover issue owns that boundary.

## Retention and recovery

The audit store is evidence and the current policy is **indefinite retention**
with no automated deletion. Platform operations owns storage monitoring and
the security lead owns any future retention decision. A bounded deletion job
may be introduced only through a reviewed issue that defines the legal,
security, backup, and incident-recovery consequences, then updates this
runbook and the parent collaboration plan. Notification and invitation
retention jobs must not delete audit rows; their ownership is separate from
audit retention. Until that decision changes, operators preserve the table and
record its growth in each deployment review.

For recovery, restore `auth_audit_events` from the same point-in-time backup as
the organization and membership tables, verify the append-only trigger exists,
and compare row counts and the newest `(occurred_at, id)` checkpoint with the
backup manifest. Do not replay audit rows through application APIs. A missing
or inconsistent audit backup is an operational incident and blocks staging
acceptance for the affected environment.

## When to update this document

Update this runbook and rerun the relevant audit acceptance checks whenever:

- a new organization-scoped resource or security action is audited;
- the actor, target, outcome, correlation, redaction, or pagination contract changes;
- `organization.audit.read` policy changes;
- retention, backup, restore, database protection, or operational ownership changes;
- a provider, runtime, invitation, notification, or context-security issue starts
  emitting audit events through the shared contract.
