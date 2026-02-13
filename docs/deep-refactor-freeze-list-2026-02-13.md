# Deep Refactor Temporary Freeze List
Date: 2026-02-13
Status: Historical (freeze period closed)

Freeze constraints in this file are no longer active.
Retained only as audit evidence for migration controls.

## Scope

Until Wave 2 cutover is completed, avoid unrelated feature changes in these modules:

1. `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/interface/artifact_domain_models.py`
2. `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/services/domain_artifact_ports.py`
3. `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/**/nodes.py`

## Allowed Changes During Freeze

1. Refactor-only edits tied to deep refactor waves.
2. Failing test fixes caused by refactor changes.
3. Contract synchronization required by this refactor.

## Disallowed During Freeze

1. New feature additions unrelated to wave objectives.
2. Opportunistic cleanup unrelated to boundary migration.
3. Cross-cutting changes that increase merge conflict surface.

## Exit Condition

Freeze is removed after Wave 2 completes and old global contract/port ownership is split.
