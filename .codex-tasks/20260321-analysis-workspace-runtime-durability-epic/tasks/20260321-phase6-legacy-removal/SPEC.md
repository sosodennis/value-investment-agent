# Child Task Specification

## Goal

Delete legacy replay-path restore logic and harden the new enterprise-grade restore architecture end to end.

## Scope

- remove replay-buffer-based restore code
- delete dead reducer and API merge logic
- run end-to-end validation and import hygiene checks

## Non-Goals

- New product features unrelated to restore durability

## Done-When

- Legacy replay restore code is gone.
- End-to-end refresh, reconnect, and completed-thread scenarios are green.
- Docs and contracts reflect only the new architecture.
