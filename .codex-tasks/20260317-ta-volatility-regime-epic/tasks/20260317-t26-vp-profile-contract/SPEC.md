# Task Spec: T26 VP-Lite Profile Contract Completion

## Objective
Promote VP-lite output from node-only metadata to an explicit profile contract that exposes `POC`, `VAH`, `VAL`, and fidelity markers while keeping the logic inside the patterns capability boundary.

## Scope
- Expand pattern/artifact contracts to carry explicit profile summary fields.
- Update patterns runtime to derive stable `POC/VAH/VAL` outputs and fidelity metadata from OHLCV-backed approximations.
- Add targeted artifact and runtime tests for the new profile contract.

## Non-goals
- New VP artifact kind or separate subdomain.
- Paid market-depth providers or order-flow terminology.
- Broader frontend redesign beyond contract/parser updates required by the new payload shape.
