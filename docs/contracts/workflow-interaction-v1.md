# Workflow interaction v1

This contract separates human input from activity status. `workflow.activity`
v2 carries activity identity, scope, status, progress, label, attempt, and
timestamps only. It never carries an interrupt request or response.

## Identity and lifecycle

Every interaction has `thread_id`, `run_id`, `activity_id`, and
`interaction_id`. The same identity appears in the event envelope and payload.
The authenticated principal, route, envelope, payload, and persisted run owner
must agree before a response is accepted.

`workflow.interaction` v1 has a discriminated `kind`, `status`, typed request,
and optional typed response. The first supported kind is `ticker_selection`.
The response must match the request kind and select one of its stored
candidates. `pending` has no response; `responded` has one; `cancelled` has
none. `responded` and `cancelled` are terminal.

A snapshot and replay fold the same durable event log for the exact run. A
thread-global cursor advances over activity, interaction, and output events.
Duplicate event delivery is idempotent. Run projections reject events whose
thread or run identity differs from the requested snapshot.

## Output references

`workflow.agent_output` v1 carries the owning run and activity, agent output
kind and version, a bounded summary, an optional preview, and an optional
artifact reference. The serialized UTF-8 JSON preview is at most 16 KiB. Full
reports, transcripts, financial statements, and time series stay in artifact
storage and are retrieved through the authenticated artifact API.

When an activity completes with an output, its completion event and output
reference event commit together with adjacent sequence values. A client must
not observe completion without the corresponding reference.

## Durable transitions

The event log is the only durable source for interaction lifecycle state. The
resume row is a command needed to recover graph execution, not a second
interaction-state store.

Writers lock in this order: current run, latest relevant event state, then
thread cursor. A waiting request appends the waiting activity and pending
interaction atomically with run/history status. A response validates the exact
identity, owner, pending state, and stored candidate, then atomically appends
the responded interaction and resumed activity, advances the attempt, updates
run/history, and records the resume command. Cancellation races on the same
run lock and atomically cancels any pending interaction, activity, and run.
Only committed events are published; replay repairs notification loss.

Snapshots read the requested run projection and thread cursor from one
repeatable-read transaction. Resume recovery requires a matching responded
event and command. Keep the command until a subsequent durable graph event or
terminal transition proves that the checkpoint consumed it.

## Cutover

This is a pre-release wire-contract replacement. Generate OpenAPI and frontend
types from the backend schema, update fixtures and consumers together, and
remove the v1 activity interruption shape and parser in the same cutover. Do
not add a compatibility alias or a second interaction-state table. Existing
staging data is retained and is not reset as part of local verification.
