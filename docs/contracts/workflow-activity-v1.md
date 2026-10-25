# `workflow.activity` v1

Status: canonical contract for #148. The machine-readable source is
`contracts/workflow-activity-v1.schema.json`; the shared behavior cases are in
`contracts/fixtures/workflow-activity-v1.json`.

## Purpose and ownership

`workflow.activity` is the application-owned durable projection of workflow
activity. It is separate from LangGraph state/checkpoints, transient model
content, and final artifacts. The backend normalizes pinned LangGraph v2
`astream_events` signals into this contract. The frontend consumes only this
contract and typed content/lifecycle contracts; raw namespaces, callback
metadata, and arbitrary state dictionaries do not cross the boundary.

The contract is intentionally owned by the application runtime. An agent node
may report a narrow activity signal, but it does not choose the public event
shape, cursor, persistence policy, or frontend view model.

## Typed event shape

Each durable event has exactly one logical identity and one thread cursor:

```text
ActivityEvent {
  event_id: string,
  seq_id: positive integer,
  event_version: "v1",
  event_name: "workflow.activity",
  thread_id: string,
  run_id: string,
  occurred_at: UTC date-time,
  payload: Activity
}

Activity {
  activity_id: string,
  parent_activity_id?: string,
  thread_id: string,
  run_id: string,
  scope_path: string[],
  kind: "phase" | "node" | "tool" | "subgraph",
  status: "queued" | "running" | "waiting" | "completed" |
          "failed" | "cancelled" | "skipped",
  label: string,
  progress?: number,  // measured [0, 100], omit when not measurable
  attempt: positive integer,
  interruption?: {
    interaction_id: string,
    request: {
      type: "ticker_selection",
      title: string,
      description: string,
      candidates: { symbol: string, name: string, exchange?: string | null,
                    type?: string | null, confidence: number }[]
    }
  }
}
```

`activity_id` is the stable logical operation identity. A retry or resume of
the same logical operation keeps `activity_id`, increments `attempt`, and
emits a new event. `event_id` identifies the delivery record and is immutable;
duplicate delivery has the same `event_id` and `seq_id` and is idempotent.
`scope_path` is a stable application path such as
`["fundamental", "valuation", "calculation"]`; it is not a LangGraph
namespace or generated UUID. Root activities omit `parent_activity_id`.

`thread_id` and `run_id` occur in both envelope and payload so a decoder can
validate ownership and run identity without trusting nested arbitrary data.
They must match exactly. `seq_id` is monotonically increasing per thread for
durable events. A subscriber resumes after the last applied cursor; a missing
sequence is a replay/snapshot recovery condition, not an invitation to invent
an event.

## Lifecycle and projection rules

Allowed normal transitions are:

```text
queued -> running -> completed
                   -> failed
                   -> cancelled
                   -> skipped
running -> waiting -> running
```

An activity may be discovered as `queued`, become `running`, pause as
`waiting` for an interrupt or deliberate wait, and then resume. A human-input
wait includes a typed `interruption` on the waiting activity. For ticker
selection, the answer is submitted to
`POST /api/v1/threads/{thread_id}/runs/{run_id}/resume` with the exact
`activity_id`, `interaction_id`, and a `ticker_selection` response. The runtime
accepts it only while that matching interaction is still the current waiting
activity, and only when the selected symbol is one of its candidates. A
successful resume continues the same run, emits the same activity identity
with `attempt + 1`, and omits the consumed interruption. `waiting` without an
`interruption` is not resumable. A retry emits the same logical `activity_id`
with `attempt + 1`; each attempt has its own terminal event. A terminal status
for an attempt is immutable. `degraded` is not a lifecycle status: a usable
completed result carries quality metadata in the owning result/artifact
contract.

The current active set contains activities whose latest attempt is queued,
running, or waiting. Completed, failed, cancelled, and skipped activities are
removed from the active set but remain in bounded recent history. A snapshot
contains `thread_id`, `run_id`, `run_status`, the durable `cursor`, the active
set, and recent history. The snapshot is the recovery base; deltas apply only
after its cursor.

Parallel work is represented by multiple activity records. The UI renders the
set and does not infer a single current node or calculate an aggregate
percentage. `progress` is optional and only present when the producer measures
that activity; a missing value means unknown, not zero.

The normalized event and cursor are appended atomically in one database
transaction before publication to SSE. A failed projection write is not
durable delivery. Replay is bounded by the runtime contract, and a cursor gap
returns `replay_gap` so the client can hydrate a fresh snapshot.

## Source signal mapping

| Source signal | Canonical result |
| --- | --- |
| Node/subgraph discovered | `queued` |
| `agent.status: running` or explicit activity start | `running` |
| Human interrupt or deliberate wait | `waiting` |
| Successful task finish or `agent.status: done` | `completed` |
| Chain/task error or `agent.status: error` | `failed` |
| Cancellation | `cancelled` |
| Unselected branch/explicit skip | `skipped` |
| `agent.status: degraded` | `completed` plus quality warning in the result contract |
| `agent.status: attention` | `waiting` plus human-input reason in the interruption contract |

These mappings are backend normalization policy. They are not frontend parser
fallbacks and do not expose the source event name.

## Fixture coverage

`contracts/fixtures/workflow-activity-v1.json` contains independent scenarios
for sequential nodes, parallel subgraphs, repeated invocations, retry
attempts, interrupts, cancellation, failure, completion, duplicate delivery,
replay, and sequence gaps. Every scenario includes valid events, a snapshot,
and machine-readable assertions for the backend and frontend tests.
The interrupt scenarios carry the prompt in the durable activity event and
snapshot, include the typed resume request, and verify the next attempt removes
the consumed prompt. No interrupt content is carried through chat-message
metadata or a separate SSE event.

The fixture manifest indexes this contract under `activity_contracts`. The
legacy SSE event fixture and event union are deleted by the #147 cutover; they
are not compatibility sources for this contract.

## Dependency gate

The repository pins LangGraph `1.0.5` for Python 3.12 and currently consumes
`astream_events(..., version="v2")`. #148 does not upgrade LangGraph or assume
the newer typed event-streaming API. A future dependency issue must verify that
API against the pinned replacement, its subgraph namespace/cancellation
behavior, and the fixture normalization before any adoption.
