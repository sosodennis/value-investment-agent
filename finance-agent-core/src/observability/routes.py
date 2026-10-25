from __future__ import annotations

from datetime import datetime
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query

from src.agents.technical.subdomains.decision_observability import (
    TechnicalCalibrationObservationBuildResultModel,
    TechnicalDecisionObservabilityRuntimeService,
    TechnicalMonitoringAggregateModel,
    TechnicalMonitoringEventDetailModel,
    TechnicalMonitoringRowModel,
    build_default_technical_decision_observability_runtime_service,
    build_monitoring_query_scope,
    build_technical_calibration_observation_build_result_model,
    build_technical_monitoring_aggregate_model,
    build_technical_monitoring_event_detail_model,
    build_technical_monitoring_row_model,
)
from src.auth.entrypoint import Principal, require_current_user

router = APIRouter(prefix="/api/v1/observability", tags=["Observability"])


@lru_cache
def get_observability_runtime() -> TechnicalDecisionObservabilityRuntimeService:
    return build_default_technical_decision_observability_runtime_service()


def _scope(
    *,
    tickers: list[str],
    agent_sources: list[str],
    timeframes: list[str],
    horizons: list[str],
    logic_versions: list[str],
    directions: list[str],
    run_types: list[str],
    reliability_levels: list[str],
    event_time_start: datetime | None,
    event_time_end: datetime | None,
    resolved_time_start: datetime | None,
    resolved_time_end: datetime | None,
    labeling_method_version: str,
    limit: int,
):
    return build_monitoring_query_scope(
        tickers=tickers,
        agent_sources=agent_sources,
        timeframes=timeframes,
        horizons=horizons,
        logic_versions=logic_versions,
        directions=directions,
        run_types=run_types,
        reliability_levels=reliability_levels,
        event_time_start=event_time_start,
        event_time_end=event_time_end,
        resolved_time_start=resolved_time_start,
        resolved_time_end=resolved_time_end,
        labeling_method_version=labeling_method_version,
        limit=limit,
    )


async def _query_scope(
    *,
    tickers: list[str],
    agent_sources: list[str],
    timeframes: list[str],
    horizons: list[str],
    logic_versions: list[str],
    directions: list[str],
    run_types: list[str],
    reliability_levels: list[str],
    event_time_start: datetime | None,
    event_time_end: datetime | None,
    resolved_time_start: datetime | None,
    resolved_time_end: datetime | None,
    labeling_method_version: str,
    limit: int,
    runtime: TechnicalDecisionObservabilityRuntimeService,
    principal: Principal,
):
    return _scope(
        tickers=tickers,
        agent_sources=agent_sources,
        timeframes=timeframes,
        horizons=horizons,
        logic_versions=logic_versions,
        directions=directions,
        run_types=run_types,
        reliability_levels=reliability_levels,
        event_time_start=event_time_start,
        event_time_end=event_time_end,
        resolved_time_start=resolved_time_start,
        resolved_time_end=resolved_time_end,
        labeling_method_version=labeling_method_version,
        limit=limit,
    )


def _filters():
    return {
        "tickers": Query(default=[]),
        "agent_sources": Query(default=[]),
        "timeframes": Query(default=[]),
        "horizons": Query(default=[]),
        "logic_versions": Query(default=[]),
        "directions": Query(default=[]),
        "run_types": Query(default=[]),
        "reliability_levels": Query(default=[]),
    }


@router.get(
    "/monitoring/aggregates", response_model=list[TechnicalMonitoringAggregateModel]
)
async def monitoring_aggregates(
    principal: Principal = Depends(require_current_user),
    runtime: TechnicalDecisionObservabilityRuntimeService = Depends(
        get_observability_runtime
    ),
    tickers: list[str] = Query(default=[]),
    agent_sources: list[str] = Query(default=[]),
    timeframes: list[str] = Query(default=[]),
    horizons: list[str] = Query(default=[]),
    logic_versions: list[str] = Query(default=[]),
    directions: list[str] = Query(default=[]),
    run_types: list[str] = Query(default=[]),
    reliability_levels: list[str] = Query(default=[]),
    event_time_start: datetime | None = None,
    event_time_end: datetime | None = None,
    resolved_time_start: datetime | None = None,
    resolved_time_end: datetime | None = None,
    labeling_method_version: str = "technical_outcome_labeling.v1",
    limit: int = Query(default=200, ge=1, le=1000),
):
    scope = _scope(
        tickers=tickers,
        agent_sources=agent_sources,
        timeframes=timeframes,
        horizons=horizons,
        logic_versions=logic_versions,
        directions=directions,
        run_types=run_types,
        reliability_levels=reliability_levels,
        event_time_start=event_time_start,
        event_time_end=event_time_end,
        resolved_time_start=resolved_time_start,
        resolved_time_end=resolved_time_end,
        labeling_method_version=labeling_method_version,
        limit=limit,
    )
    rows = await runtime.load_monitoring_aggregates(scope=scope)
    return [build_technical_monitoring_aggregate_model(row) for row in rows]


@router.get("/monitoring/rows", response_model=list[TechnicalMonitoringRowModel])
async def monitoring_rows(
    principal: Principal = Depends(require_current_user),
    runtime: TechnicalDecisionObservabilityRuntimeService = Depends(
        get_observability_runtime
    ),
    tickers: list[str] = Query(default=[]),
    agent_sources: list[str] = Query(default=[]),
    timeframes: list[str] = Query(default=[]),
    horizons: list[str] = Query(default=[]),
    logic_versions: list[str] = Query(default=[]),
    directions: list[str] = Query(default=[]),
    run_types: list[str] = Query(default=[]),
    reliability_levels: list[str] = Query(default=[]),
    limit: int = Query(default=200, ge=1, le=1000),
):
    scope = _scope(
        tickers=tickers,
        agent_sources=agent_sources,
        timeframes=timeframes,
        horizons=horizons,
        logic_versions=logic_versions,
        directions=directions,
        run_types=run_types,
        reliability_levels=reliability_levels,
        event_time_start=None,
        event_time_end=None,
        resolved_time_start=None,
        resolved_time_end=None,
        labeling_method_version="technical_outcome_labeling.v1",
        limit=limit,
    )
    rows = await runtime.load_monitoring_rows(scope=scope)
    return [build_technical_monitoring_row_model(row) for row in rows]


@router.get(
    "/monitoring/events/{event_id}", response_model=TechnicalMonitoringEventDetailModel
)
async def monitoring_event(
    event_id: str,
    principal: Principal = Depends(require_current_user),
    runtime: TechnicalDecisionObservabilityRuntimeService = Depends(
        get_observability_runtime
    ),
    labeling_method_version: str = "technical_outcome_labeling.v1",
):
    result = await runtime.load_monitoring_event_detail(
        event_id=event_id, labeling_method_version=labeling_method_version
    )
    if result is None:
        raise HTTPException(status_code=404, detail="observability_event_not_found")
    return build_technical_monitoring_event_detail_model(result)


@router.get(
    "/calibration/direction-readiness",
    response_model=TechnicalCalibrationObservationBuildResultModel,
)
async def direction_readiness(
    principal: Principal = Depends(require_current_user),
    runtime: TechnicalDecisionObservabilityRuntimeService = Depends(
        get_observability_runtime
    ),
    tickers: list[str] = Query(default=[]),
    limit: int = Query(default=200, ge=1, le=1000),
    include_observations: bool = False,
):
    scope = _scope(
        tickers=tickers,
        agent_sources=[],
        timeframes=[],
        horizons=[],
        logic_versions=[],
        directions=[],
        run_types=[],
        reliability_levels=[],
        event_time_start=None,
        event_time_end=None,
        resolved_time_start=None,
        resolved_time_end=None,
        labeling_method_version="technical_outcome_labeling.v1",
        limit=limit,
    )
    result = await runtime.load_direction_calibration_observations(scope=scope)
    return build_technical_calibration_observation_build_result_model(
        result, include_observations=include_observations
    )
