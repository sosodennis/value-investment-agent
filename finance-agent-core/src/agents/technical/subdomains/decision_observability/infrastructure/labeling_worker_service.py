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
from src.agents.technical.subdomains.market_data.application.ports import (
    MarketDataOhlcvFetchResult,
)
from src.agents.technical.subdomains.market_data.infrastructure.yahoo_ohlcv_provider import (
    fetch_ohlcv,
)
from src.shared.kernel.tools.logger import get_logger, log_event

from .runtime_factory import (
    build_default_technical_decision_observability_runtime_service,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class TechnicalOutcomeLabelingMarketDataReader:
    cache_base_dir: str = "/tmp/ta_labeling_market_data_cache"
    cache_key_prefix: str = "labeling"
    max_retries: int = 2
    retry_delay_seconds: float = 0.5

    async def fetch_ohlcv(
        self,
        ticker_symbol: str,
        *,
        period: str = "6mo",
        interval: str = "1d",
    ) -> MarketDataOhlcvFetchResult:
        return await asyncio.to_thread(
            fetch_ohlcv,
            ticker_symbol,
            period=period,
            interval=interval,
            cache_base_dir=self.cache_base_dir,
            cache_key_prefix=self.cache_key_prefix,
            max_retries=self.max_retries,
            retry_delay_seconds=self.retry_delay_seconds,
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
        market_data_reader=TechnicalOutcomeLabelingMarketDataReader(),
    )


__all__ = [
    "TechnicalOutcomeLabelingMarketDataReader",
    "TechnicalOutcomeLabelingWorkerService",
    "build_default_technical_outcome_labeling_worker_service",
]
