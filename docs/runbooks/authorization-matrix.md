# Organization Authorization Matrix

This runbook is the contract for organization authorization in issue #203. The
typed matrix is implemented in `finance-agent-core/src/auth/domain/authorization.py`
and is evaluated by the application `AuthorizationService`. Routes and UI code
must call that service instead of comparing role strings. HTTP dependencies use
the active server-resolved organization by default; resource routes must provide
a typed resource factory that binds their route resource to the authorization
context before the use case loads relationship facts.

## Role Matrix

| Permission | Owner | Admin | Member |
| --- | --- | --- | --- |
| `organization.create` | allow | allow | allow |
| `organization.read` | allow | allow | allow |
| `organization.update` | allow | allow | deny |
| `organization.delete` | allow | deny | deny |
| `organization.archive` | allow | deny | deny |
| `membership.read` | allow | allow | allow |
| `membership.remove` | allow | allow | deny |
| `membership.leave` | allow, subject to last-owner rule | allow | allow |
| `membership.role.change` | allow, subject to role rules | allow, subject to role rules | deny |
| `membership.owner.transfer` | allow | deny | deny |
| `invitation.create` | allow, admin/member only | allow, member only | deny |
| `invitation.read` | allow, or recipient | allow, or recipient | allow as recipient |
| `invitation.revoke` | allow | allow | deny |
| `notification.inbox.read` | recipient only | recipient only | recipient only |
| `notification.inbox.mutate` | recipient only | recipient only | recipient only |
| `directory.search` | allow | allow | allow |
| `provider.config.read` | allow | allow | allow |
| `provider.config.write` | allow | allow | deny |
| `organization.audit.read` | allow | allow | deny |

`organization.create` is authenticated-user scoped and does not require an
active organization. Every other organization-scoped decision requires an
active membership and a matching server-resolved organization ID. Inbox
permissions are recipient-private user permissions; organization metadata on a
notification does not grant access to another user's inbox.

## Relationship Rules

- Invitations may request `admin` or `member` from an owner, and only `member`
  from an admin. No invitation may request `owner`.
- A role change may assign `admin` or `member` only. Admins cannot assign
  another admin, and only owners can transfer ownership.
- Removing or demoting the last active owner is denied.
- An owner cannot demote themself through a role-management operation and may
  leave only when another active owner remains. Members and admins may leave
  when the last-owner invariant is not affected.
- A resource belonging to another organization returns the stable
  `resource_not_found` failure so callers cannot use authorization to enumerate
  tenant resources.

## Failure Contract

The policy returns stable codes: `authentication_required`,
`organization_context_required`, `resource_not_found`, `permission_denied`,
`invalid_resource_context`, `last_owner_protected`,
`self_removal_not_allowed`, and `role_transition_not_allowed`. The HTTP
dependency maps cross-organization `resource_not_found` to 404 and other
authorization failures to 403.

Update this document and the matrix tests whenever a role, permission,
relationship rule, or failure contract changes. Add the affected allow and deny
cases before changing a dependent organization, invitation, notification, or
provider route.
