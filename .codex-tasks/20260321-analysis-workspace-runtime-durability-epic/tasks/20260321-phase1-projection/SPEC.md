# Child Task Specification

## Goal

Design and implement the durable runtime projection schema and repository layer that will support enterprise-grade workspace restore.

## Scope

- Add append-only storage for workflow activity events and durable cursors.
- Define repository interfaces and projection semantics.
- Keep ownership aligned with backend architecture layers.

## Non-Goals

- Rewriting stream transport.
- Rewriting frontend restore.
- Keeping old replay-buffer data as a parallel persistence path.

## Done-When

- Projection ORM tables and repository APIs exist.
- Active-agent and recent-activity derivation logic is testable and deterministic.
- No compatibility storage path is introduced.
