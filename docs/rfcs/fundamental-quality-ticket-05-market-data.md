# Ticket 05: market_data Quality and Cohesion

## Requirement Breakdown
- Clarify ownership of `MarketSnapshot` and provider contracts.
- Remove empty `interface/` if no contracts remain.
- Ensure application layer only orchestrates, not models domain concepts.

## Technical Objectives and Strategy
- Decide whether `MarketSnapshot` is a domain entity or a boundary contract.
- Move provider protocol to `application/ports.py` if it is an application boundary.
- Keep infrastructure adapters thin and typed.

## Involved Files
- `finance-agent-core/src/agents/fundamental/market_data/application/market_data_service.py`
- `finance-agent-core/src/agents/fundamental/market_data/domain/provider_contracts.py`
- `finance-agent-core/src/agents/fundamental/market_data/domain/consensus_anchor_aggregator.py`
- `finance-agent-core/src/agents/fundamental/market_data/infrastructure/*`
- `finance-agent-core/src/agents/fundamental/market_data/interface/__init__.py`

## Slices

### Slice 1 (small): Ownership Decision for MarketSnapshot
- Objective: decide `MarketSnapshot` home (domain vs interface).
- Entry: confirm consumers and usage patterns.
- Exit: one canonical owner; imports updated.
- Validation: `tests/test_fundamental_market_data_client.py`, `tests/test_consensus_anchor_aggregator.py`.

### Slice 2 (small): Provider Contract Placement
- Objective: move `MarketDataProvider` protocol to `application/ports.py` if it is a use-case boundary.
- Entry: slice 1 complete.
- Exit: domain contracts only represent domain entities; application owns use-case ports.
- Validation: `tests/test_fundamental_market_data_client.py`.

### Slice 3 (small): Remove Empty Interface Layer
- Objective: delete `interface/` if no boundary contracts remain.
- Entry: slices 1–2 complete.
- Exit: no empty layer packages.
- Validation: `tests/test_fundamental_import_hygiene_guard.py`.

## Risk/Dependency Assessment
- Low to moderate risk; changes are mostly structural.

## Validation and Rollout Gates
- Lint: `ruff check` on touched files.
- Tests: market data and consensus tests, plus import hygiene.

## Assumptions/Open Questions
- Is `MarketSnapshot` considered domain data (business concept) or interface contract (boundary)?
