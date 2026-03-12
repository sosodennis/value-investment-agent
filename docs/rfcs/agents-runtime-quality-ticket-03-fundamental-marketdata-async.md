# Ticket 03: Fundamental Market Data Async Accessor

## Objective
Prevent blocking retries/sleeps on async valuation path by offloading market snapshot fetch.

## Scope
- `finance-agent-core/src/agents/fundamental/subdomains/market_data/application/market_data_service.py`
- `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/ports.py`
- `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/factory.py`

## Changes
- Add `get_market_snapshot_async` to `MarketDataService` (offloads to thread).
- Extend `IFundamentalMarketDataService` with async method.
- Use async accessor inside fundamental valuation builder.

## Validation
- `rg "get_market_snapshot_async" finance-agent-core/src/agents/fundamental -n`
- Targeted tests if available (otherwise smoke via existing valuation replay scripts).
