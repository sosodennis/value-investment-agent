from __future__ import annotations

from typing import Protocol

from src.agents.technical.subdomains.decision_observability.domain.contracts import (
    MonitoringQueryScope,
    OutcomeLabelingRequest,
    TechnicalMonitoringEventDetail,
    TechnicalMonitoringReadModelRow,
    TechnicalOutcomePathRecord,
    TechnicalPredictionEventRecord,
)
from src.agents.technical.subdomains.market_data.application.ports import (
    MarketDataOhlcvFetchResult,
)


class TechnicalDecisionObservabilityRepository(Protocol):
    async def append_prediction_event(
        self, record: TechnicalPredictionEventRecord
    ) -> None: ...

    async def fetch_unlabeled_prediction_events(
        self,
        *,
        labeling_method_version: str,
        limit: int = 100,
    ) -> list[TechnicalPredictionEventRecord]: ...

    async def append_outcome_path_if_missing(
        self,
        *,
        request: OutcomeLabelingRequest,
        outcome: TechnicalOutcomePathRecord,
    ) -> bool: ...

    async def fetch_monitoring_rows(
        self,
        *,
        scope: MonitoringQueryScope,
    ) -> list[TechnicalMonitoringReadModelRow]: ...

    async def fetch_monitoring_event_detail(
        self,
        *,
        event_id: str,
        labeling_method_version: str,
    ) -> TechnicalMonitoringEventDetail | None: ...


class OutcomeLabelingMarketDataReader(Protocol):
    async def fetch_ohlcv(
        self,
        ticker_symbol: str,
        *,
        period: str = "6mo",
        interval: str = "1d",
    ) -> MarketDataOhlcvFetchResult: ...
