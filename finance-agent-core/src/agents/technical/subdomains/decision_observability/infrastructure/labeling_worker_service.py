from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from src.agents.technical.subdomains.decision_observability.application import (
    OutcomeLabelingBatchResult,
    OutcomeLabelingMarketDataReader,
    TechnicalDecisionObservabilityRuntimeService,
)
from src.agents.technical.subdomains.market_data import (
    MarketDataRuntimeService,
)
from src.agents.technical.subdomains.market_data.public import (
    MarketDataCacheConfig,
    MarketDataOhlcvFetchResult,
    MarketDataRetryPolicy,
    build_default_market_data_provider,
)
from src.shared.kernel.tools.logger import get_logger, log_event

from .runtime_factory import (
    build_default_technical_decision_observability_runtime_service,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class TechnicalOutcomeLabelingMarketDataReader:
    runtime_service: MarketDataRuntimeService

    async def fetch_ohlcv(
        self,
        ticker_symbol: str,
        *,
        period: str = "6mo",
        interval: str = "1d",
    ) -> MarketDataOhlcvFetchResult:
        return await asyncio.to_thread(
            self.runtime_service.fetch_ohlcv,
            ticker_symbol,
            period=period,
            interval=interval,
        )


@dataclass(frozen=True)
class TechnicalOutcomeLabelingWorkerService:
    runtime_service: TechnicalDecisionObservabilityRuntimeService
    market_data_reader: OutcomeLabelingMarketDataReader

    async def run_once(
        self,
        *,
        as_of_time: datetime | None = None,
        limit: int = 100,
        labeling_method_version: str = "technical_outcome_labeling.v1",
    ) -> OutcomeLabelingBatchResult:
        effective_as_of = (
            as_of_time
            if as_of_time is not None
            else datetime.now(UTC).replace(tzinfo=None)
        )
        log_event(
            logger,
            event="technical_outcome_labeling_started",
            message="technical outcome labeling started",
            fields={
                "as_of_time": effective_as_of.isoformat(),
                "limit": limit,
                "labeling_method_version": labeling_method_version,
            },
        )
        result = await self.runtime_service.label_matured_prediction_events(
            market_data_reader=self.market_data_reader,
            as_of_time=effective_as_of,
            limit=limit,
            labeling_method_version=labeling_method_version,
        )
        is_degraded = bool(result.failed_event_ids)
        log_event(
            logger,
            event="technical_outcome_labeling_completed",
            message="technical outcome labeling completed",
            level=logging.WARNING if is_degraded else logging.INFO,
            fields={
                "status": "done",
                "is_degraded": is_degraded,
                "scanned_event_count": result.scanned_event_count,
                "matured_event_count": result.matured_event_count,
                "inserted_outcome_count": result.inserted_outcome_count,
                "skipped_existing_count": result.skipped_existing_count,
                "failed_event_count": len(result.failed_event_ids),
                "provider_failures": list(result.provider_failures),
            },
        )
        return result


def build_default_technical_outcome_labeling_worker_service() -> (
    TechnicalOutcomeLabelingWorkerService
):
    return TechnicalOutcomeLabelingWorkerService(
        runtime_service=build_default_technical_decision_observability_runtime_service(),
        market_data_reader=TechnicalOutcomeLabelingMarketDataReader(
            runtime_service=MarketDataRuntimeService(
                provider=build_default_market_data_provider(
                    cache=MarketDataCacheConfig(
                        base_dir="/tmp/ta_labeling_market_data_cache",
                        namespace="labeling",
                    ),
                    retry_policy=MarketDataRetryPolicy(
                        max_retries=2,
                        delay_seconds=0.5,
                    ),
                )
            )
        ),
    )


__all__ = [
    "TechnicalOutcomeLabelingMarketDataReader",
    "TechnicalOutcomeLabelingWorkerService",
    "build_default_technical_outcome_labeling_worker_service",
]
