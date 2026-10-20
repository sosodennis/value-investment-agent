"""Stable valuation model selection contracts and services."""

from .domain.entities import FinancialHealthInsights, FundamentalSelectionReport
from .domain.financial_health_service import (
    build_latest_health_context,
    calculate_revenue_cagr,
    extract_latest_health_insights,
)
from .domain.model_selection import (
    DEFAULT_SCORING_WEIGHTS,
    MODEL_SPECS,
    ModelCandidate,
    ModelSelectionResult,
    ModelSpec,
    ScoringWeights,
    SelectionField,
    SelectionSignals,
    build_model_selection_reasoning,
    select_valuation_model,
)
from .interface.report_projection_service import (
    FundamentalPreviewMetrics,
    extract_latest_preview_metrics,
    project_selection_reports,
    project_selection_reports_from_models,
)

__all__ = [
    "DEFAULT_SCORING_WEIGHTS",
    "MODEL_SPECS",
    "FinancialHealthInsights",
    "FundamentalPreviewMetrics",
    "FundamentalSelectionReport",
    "ModelCandidate",
    "ModelSelectionResult",
    "ModelSpec",
    "ScoringWeights",
    "SelectionField",
    "SelectionSignals",
    "build_latest_health_context",
    "build_model_selection_reasoning",
    "calculate_revenue_cagr",
    "extract_latest_health_insights",
    "extract_latest_preview_metrics",
    "project_selection_reports",
    "project_selection_reports_from_models",
    "select_valuation_model",
]
