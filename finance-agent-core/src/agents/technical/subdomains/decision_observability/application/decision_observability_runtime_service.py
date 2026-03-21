from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.agents.technical.subdomains.decision_observability.application.ports import (
    OutcomeLabelingMarketDataReader,
    TechnicalDecisionObservabilityRepository,
)
from src.agents.technical.subdomains.decision_observability.domain import (
    MonitoringQueryScope,
    TechnicalCalibrationObservationBuildResult,
    TechnicalMonitoringAggregate,
    TechnicalMonitoringEventDetail,
    TechnicalMonitoringReadModelRow,
    build_prediction_event_record,
    build_technical_direction_calibration_observations,
    compute_monitoring_aggregates,
    compute_outcome_label,
    filter_matured_events,
)
from src.shared.kernel.types import JSONObject


@dataclass(frozen=True)
class OutcomeLabelingBatchResult:
    scanned_event_count: int
    matured_event_count: int
    inserted_outcome_count: int
    skipped_existing_count: int
    failed_event_ids: tuple[str, ...]
    provider_failures: tuple[str, ...]


@dataclass(frozen=True)
class TechnicalDecisionObservabilityRuntimeService:
    repository: TechnicalDecisionObservabilityRepository

    async def register_prediction_event(
        self,
        *,
        ticker: str,
        technical_context: JSONObject,
        full_report_payload: JSONObject,
        report_artifact_id: str,
        run_type: str = "workflow",
    ) -> str:
        record = build_prediction_event_record(
            ticker=ticker,
            technical_context=technical_context,
            full_report_payload=full_report_payload,
            report_artifact_id=report_artifact_id,
            run_type=run_type,
        )
        await self.repository.append_prediction_event(record)
        return record.event_id

    async def label_matured_prediction_events(
        self,
        *,
        market_data_reader: OutcomeLabelingMarketDataReader,
        as_of_time: datetime,
        limit: int = 100,
        labeling_method_version: str = "technical_outcome_labeling.v1",
    ) -> OutcomeLabelingBatchResult:
        events = await self.repository.fetch_unlabeled_prediction_events(
            labeling_method_version=labeling_method_version,
            limit=limit,
        )
        requests = filter_matured_events(events=events, as_of_time=as_of_time)

        inserted_count = 0
        skipped_existing_count = 0
        failed_event_ids: list[str] = []
        provider_failures: list[str] = []

        for request in requests:
            fetch_result = await market_data_reader.fetch_ohlcv(
                request.event.ticker,
                period=request.period,
                interval=request.interval,
            )
            if fetch_result.failure is not None:
                failed_event_ids.append(request.event.event_id)
                provider_failures.append(fetch_result.failure.failure_code)
                continue
            if fetch_result.data is None:
                failed_event_ids.append(request.event.event_id)
                provider_failures.append("TECHNICAL_LABELING_PRICE_PATH_MISSING")
                continue

            try:
                outcome_result = compute_outcome_label(
                    request=request,
                    price_frame=fetch_result.data,
                )
            except ValueError:
                failed_event_ids.append(request.event.event_id)
                provider_failures.append("TECHNICAL_LABELING_PRICE_WINDOW_INVALID")
                continue

            inserted = await self.repository.append_outcome_path_if_missing(
                request=request,
                outcome=outcome_result.outcome,
            )
            if inserted:
                inserted_count += 1
            else:
                skipped_existing_count += 1

        return OutcomeLabelingBatchResult(
            scanned_event_count=len(events),
            matured_event_count=len(requests),
            inserted_outcome_count=inserted_count,
            skipped_existing_count=skipped_existing_count,
            failed_event_ids=tuple(failed_event_ids),
            provider_failures=tuple(provider_failures),
        )

    async def load_monitoring_rows(
        self,
        *,
        scope: MonitoringQueryScope,
    ) -> tuple[TechnicalMonitoringReadModelRow, ...]:
        rows = await self.repository.fetch_monitoring_rows(scope=scope)
        return tuple(rows)

    async def load_monitoring_event_detail(
        self,
        *,
        event_id: str,
        labeling_method_version: str = "technical_outcome_labeling.v1",
    ) -> TechnicalMonitoringEventDetail | None:
        return await self.repository.fetch_monitoring_event_detail(
            event_id=event_id,
            labeling_method_version=labeling_method_version,
        )

    async def load_monitoring_aggregates(
        self,
        *,
        scope: MonitoringQueryScope,
    ) -> tuple[TechnicalMonitoringAggregate, ...]:
        rows = await self.load_monitoring_rows(scope=scope)
        return compute_monitoring_aggregates(rows)

    async def load_direction_calibration_observations(
        self,
        *,
        scope: MonitoringQueryScope,
    ) -> TechnicalCalibrationObservationBuildResult:
        rows = await self.load_monitoring_rows(scope=scope)
        return build_technical_direction_calibration_observations(rows)


__all__ = [
    "OutcomeLabelingBatchResult",
    "TechnicalDecisionObservabilityRuntimeService",
]
