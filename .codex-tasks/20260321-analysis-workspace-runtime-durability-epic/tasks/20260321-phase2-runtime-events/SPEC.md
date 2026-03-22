# Child Task Specification

## Goal

Refactor runtime event handling so workflow activity is durably written to the new projection in real time.

## Scope

- Projection writes from runtime event adaptation.
- Deterministic append semantics for agent status, lifecycle, and interrupt-visible workflow state.
- Projection ownership at the backend runtime boundary.

## Non-Goals

- Public API redesign.
- Frontend restore changes.

## Done-When

- Runtime writes populate the durable projection for live and refresh scenarios.
- Tests cover append semantics, idempotency expectations, and active-state derivation inputs.
