from __future__ import annotations

from src.agents.fundamental.market_data.application.market_data_service import (
    MarketDataService,
)
from src.agents.fundamental.market_data.application.ports import MarketDataProvider
from src.agents.fundamental.market_data.infrastructure.fred_macro_provider import (
    FredMacroProvider,
)
from src.agents.fundamental.market_data.infrastructure.investing_provider import (
    InvestingProvider,
)
from src.agents.fundamental.market_data.infrastructure.marketbeat_provider import (
    MarketBeatProvider,
)
from src.agents.fundamental.market_data.infrastructure.tipranks_provider import (
    TipRanksProvider,
)
from src.agents.fundamental.market_data.infrastructure.yahoo_finance_provider import (
    YahooFinanceProvider,
)


def build_market_data_service(
    *,
    ttl_seconds: int = 120,
    max_retries: int = 2,
    retry_delay_seconds: float = 0.25,
    providers: tuple[MarketDataProvider, ...] | None = None,
) -> MarketDataService:
    configured = providers or (
        YahooFinanceProvider(),
        FredMacroProvider(),
        TipRanksProvider(),
        InvestingProvider(),
        MarketBeatProvider(),
    )
    return MarketDataService(
        ttl_seconds=ttl_seconds,
        max_retries=max_retries,
        retry_delay_seconds=retry_delay_seconds,
        providers=configured,
    )


market_data_service = build_market_data_service()

__all__ = ["build_market_data_service", "market_data_service"]
