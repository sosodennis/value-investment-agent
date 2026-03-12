# Ticket 01: Intent Typed Ticker Search Result

## Objective
Introduce a typed ticker search result so failures are observable and degrade states are explicit.

## Scope
- `finance-agent-core/src/agents/intent/application/ports.py`
- `finance-agent-core/src/agents/intent/infrastructure/market_data/yahoo_ticker_search_provider.py`
- `finance-agent-core/src/agents/intent/application/orchestrator.py`
- `finance-agent-core/tests/test_error_handling_intent.py`

## Changes
- Add `IntentTickerSearchResult` with `candidates`, `failure_code`, `failure_reason`, `fallback_mode`.
- Update `IIntentTickerSearchProvider` to return `IntentTickerSearchResult`.
- Update Yahoo ticker search provider to return typed result with failure codes for errors and empty result.
- Update orchestrator to aggregate ticker-search degradation and propagate to logs/state.
- Update tests to match new typed return.

## Validation
- `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_error_handling_intent.py -q`
- `rg "IntentTickerSearchResult|IIntentTickerSearchProvider" finance-agent-core/src/agents/intent -n`
