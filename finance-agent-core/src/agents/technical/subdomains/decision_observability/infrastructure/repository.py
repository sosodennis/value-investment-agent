from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, and_, select

from src.agents.technical.subdomains.decision_observability.domain.contracts import (
    MonitoringQueryScope,
    OutcomeLabelingRequest,
    TechnicalMonitoringReadModelRow,
    TechnicalOutcomePathRecord,
    TechnicalPredictionEventRecord,
)
from src.infrastructure.database import AsyncSessionLocal
from src.infrastructure.models import TechnicalOutcomePath, TechnicalPredictionEvent


@dataclass(frozen=True)
class SqlAlchemyTechnicalDecisionObservabilityRepository:
    async def append_prediction_event(
        self, record: TechnicalPredictionEventRecord
    ) -> None:
        async with AsyncSessionLocal() as session:
            event = TechnicalPredictionEvent(
                event_id=record.event_id,
                agent_source=record.agent_source,
                event_time=record.event_time,
                ticker=record.ticker,
                timeframe=record.timeframe,
                horizon=record.horizon,
                direction=record.direction,
                raw_score=record.raw_score,
                confidence=record.confidence,
                reliability_level=record.reliability_level,
                logic_version=record.logic_version,
                feature_contract_version=record.feature_contract_version,
                run_type=record.run_type,
                full_report_artifact_id=record.full_report_artifact_id,
                source_artifact_refs=record.source_artifact_refs,
                context_payload=record.context_payload,
            )
            session.add(event)
            await session.commit()

    async def fetch_unlabeled_prediction_events(
        self,
        *,
        labeling_method_version: str,
        limit: int = 100,
    ) -> list[TechnicalPredictionEventRecord]:
        async with AsyncSessionLocal() as session:
            query = self._build_unlabeled_prediction_events_query(
                labeling_method_version=labeling_method_version,
                limit=limit,
            )
            result = await session.execute(query)
            rows = list(result.scalars().all())
        return [self._prediction_event_record_from_model(row) for row in rows]

    async def append_outcome_path_if_missing(
        self,
        *,
        request: OutcomeLabelingRequest,
        outcome: TechnicalOutcomePathRecord,
    ) -> bool:
        async with AsyncSessionLocal() as session:
            existing_query = select(TechnicalOutcomePath.outcome_path_id).where(
                TechnicalOutcomePath.event_id == request.event.event_id,
                TechnicalOutcomePath.labeling_method_version
                == request.labeling_method_version,
            )
            existing = await session.execute(existing_query)
            if existing.scalar_one_or_none() is not None:
                return False

            model = TechnicalOutcomePath(
                outcome_path_id=outcome.outcome_path_id,
                event_id=outcome.event_id,
                resolved_at=outcome.resolved_at,
                forward_return=outcome.forward_return,
                mfe=outcome.mfe,
                mae=outcome.mae,
                realized_volatility=outcome.realized_volatility,
                labeling_method_version=outcome.labeling_method_version,
                data_quality_flags=list(outcome.data_quality_flags),
            )
            session.add(model)
            await session.commit()
            return True

    async def fetch_monitoring_rows(
        self,
        *,
        scope: MonitoringQueryScope,
    ) -> list[TechnicalMonitoringReadModelRow]:
        async with AsyncSessionLocal() as session:
            query = self._build_monitoring_rows_query(scope=scope)
            result = await session.execute(query)
            rows = list(result.all())
        return [
            self._monitoring_row_from_models(
                prediction_event=prediction_event,
                outcome_path=outcome_path,
            )
            for prediction_event, outcome_path in rows
        ]

    def _build_unlabeled_prediction_events_query(
        self,
        *,
        labeling_method_version: str,
        limit: int,
    ) -> Select[tuple[TechnicalPredictionEvent]]:
        return (
            select(TechnicalPredictionEvent)
            .where(
                ~TechnicalPredictionEvent.event_id.in_(
                    select(TechnicalOutcomePath.event_id).where(
                        TechnicalOutcomePath.labeling_method_version
                        == labeling_method_version
                    )
                )
            )
            .order_by(TechnicalPredictionEvent.event_time.asc())
            .limit(limit)
        )

    def _build_monitoring_rows_query(
        self,
        *,
        scope: MonitoringQueryScope,
    ) -> Select[tuple[TechnicalPredictionEvent, TechnicalOutcomePath | None]]:
        join_condition = and_(
            TechnicalOutcomePath.event_id == TechnicalPredictionEvent.event_id,
            TechnicalOutcomePath.labeling_method_version
            == scope.labeling_method_version,
        )
        query = select(TechnicalPredictionEvent, TechnicalOutcomePath).outerjoin(
            TechnicalOutcomePath,
            join_condition,
        )

        if scope.tickers:
            query = query.where(TechnicalPredictionEvent.ticker.in_(scope.tickers))
        if scope.agent_sources:
            query = query.where(
                TechnicalPredictionEvent.agent_source.in_(scope.agent_sources)
            )
        if scope.timeframes:
            query = query.where(
                TechnicalPredictionEvent.timeframe.in_(scope.timeframes)
            )
        if scope.horizons:
            query = query.where(TechnicalPredictionEvent.horizon.in_(scope.horizons))
        if scope.logic_versions:
            query = query.where(
                TechnicalPredictionEvent.logic_version.in_(scope.logic_versions)
            )
        if scope.directions:
            query = query.where(
                TechnicalPredictionEvent.direction.in_(scope.directions)
            )
        if scope.run_types:
            query = query.where(TechnicalPredictionEvent.run_type.in_(scope.run_types))
        if scope.reliability_levels:
            query = query.where(
                TechnicalPredictionEvent.reliability_level.in_(scope.reliability_levels)
            )
        if scope.event_time_start is not None:
            query = query.where(
                TechnicalPredictionEvent.event_time >= scope.event_time_start
            )
        if scope.event_time_end is not None:
            query = query.where(
                TechnicalPredictionEvent.event_time <= scope.event_time_end
            )
        if scope.resolved_time_start is not None:
            query = query.where(
                TechnicalOutcomePath.resolved_at >= scope.resolved_time_start
            )
        if scope.resolved_time_end is not None:
            query = query.where(
                TechnicalOutcomePath.resolved_at <= scope.resolved_time_end
            )

        return query.order_by(TechnicalPredictionEvent.event_time.desc()).limit(
            scope.limit
        )

    def _prediction_event_record_from_model(
        self, model: TechnicalPredictionEvent
    ) -> TechnicalPredictionEventRecord:
        return TechnicalPredictionEventRecord(
            event_id=model.event_id,
            agent_source=model.agent_source,
            event_time=model.event_time,
            ticker=model.ticker,
            timeframe=model.timeframe,
            horizon=model.horizon,
            direction=model.direction,
            raw_score=model.raw_score,
            confidence=model.confidence,
            reliability_level=model.reliability_level,
            logic_version=model.logic_version,
            feature_contract_version=model.feature_contract_version,
            run_type=model.run_type,
            full_report_artifact_id=model.full_report_artifact_id,
            source_artifact_refs=dict(model.source_artifact_refs or {}),
            context_payload=dict(model.context_payload or {}),
        )

    def _monitoring_row_from_models(
        self,
        *,
        prediction_event: TechnicalPredictionEvent,
        outcome_path: TechnicalOutcomePath | None,
    ) -> TechnicalMonitoringReadModelRow:
        return TechnicalMonitoringReadModelRow(
            event_id=prediction_event.event_id,
            event_time=prediction_event.event_time,
            ticker=prediction_event.ticker,
            agent_source=prediction_event.agent_source,
            timeframe=prediction_event.timeframe,
            horizon=prediction_event.horizon,
            direction=prediction_event.direction,
            logic_version=prediction_event.logic_version,
            run_type=prediction_event.run_type,
            reliability_level=prediction_event.reliability_level,
            raw_score=prediction_event.raw_score,
            confidence=prediction_event.confidence,
            outcome_path_id=None
            if outcome_path is None
            else outcome_path.outcome_path_id,
            resolved_at=None if outcome_path is None else outcome_path.resolved_at,
            labeling_method_version=(
                None if outcome_path is None else outcome_path.labeling_method_version
            ),
            forward_return=None
            if outcome_path is None
            else outcome_path.forward_return,
            mfe=None if outcome_path is None else outcome_path.mfe,
            mae=None if outcome_path is None else outcome_path.mae,
            realized_volatility=(
                None if outcome_path is None else outcome_path.realized_volatility
            ),
            data_quality_flags=tuple(
                [] if outcome_path is None else outcome_path.data_quality_flags or []
            ),
        )


def build_default_technical_decision_observability_repository() -> (
    SqlAlchemyTechnicalDecisionObservabilityRepository
):
    return SqlAlchemyTechnicalDecisionObservabilityRepository()


__all__ = [
    "SqlAlchemyTechnicalDecisionObservabilityRepository",
    "build_default_technical_decision_observability_repository",
]
