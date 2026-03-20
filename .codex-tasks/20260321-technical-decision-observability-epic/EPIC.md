# Epic Specification

## Goal

- Implement the technical decision observability backbone described in `/Users/denniswong/Desktop/Project/value-investment-agent/docs/technical-decision-observability-backbone-adr-2026-03-21.md` across schema, runtime registry, delayed labeling, monitoring read models, and calibration observation integration.

## Non-Goals

- Add macro, breadth, or new quant families.
- Build a full automated recalibration loop.
- Create a cross-agent shared observability platform.
- Productize a frontend dashboard.

## Constraints

- Keep the capability agent-local under `technical/subdomains/decision_observability`.
- Preserve DB-level integrity and do not drop foreign keys preemptively.
- Keep `raw outcomes` as truth and `approved_label_snapshots` as governed derived rows.
- Use the fixed phase-1 horizon set: `1d`, `5d`, `20d`.
- Keep scheduler architecture single-path: dedicated scheduler container plus `supercronic`, with no host cron and no in-process API scheduler loop.
- Follow strict typing and existing repo architecture boundaries.

## Risk Assessment

- Schema errors or weak event semantics can permanently reduce downstream calibration value.
- Runtime registry writes can add latency or degraded-path complexity to technical finalization.
- Market-data incompleteness or retry mistakes can create duplicate or missing outcome rows.
- Monitoring dimensions can sprawl if context payload and horizon governance drift.
- Calibration consumer wiring can regress existing file-based offline workflows if facade boundaries are unclear.

## Child Deliverables

- Phase 1 registry backbone and schema
- Phase 2 delayed labeling and scheduler runtime
- Phase 3 DB-backed monitoring read model
- Phase 4 calibration observation builder integration

## Dependency Notes

- Child 2 depends on child 1 because labeling requires persisted prediction events and schema.
- Child 3 depends on child 2 because phase-1 monitoring should read joined event and outcome truth.
- Child 4 depends on child 2 because the builder requires event plus outcome records; it may proceed in parallel with child 3 once those contracts stabilize.

## Child Task Types

- `single-compact`
- `single-full`
- `batch`

## Done-When

- [ ] Every row in `SUBTASKS.csv` is `DONE`
- [ ] The final implementation satisfies the ADR success criteria
- [ ] Validation gates for each phase have explicit passing evidence
