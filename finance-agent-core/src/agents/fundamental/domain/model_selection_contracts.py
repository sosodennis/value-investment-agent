from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .valuation_model import ValuationModel

SelectionField = Literal[
    "total_revenue",
    "net_income",
    "operating_cash_flow",
    "total_equity",
    "total_assets",
    "extension_ffo",
]


@dataclass(frozen=True)
class ModelSpec:
    model: ValuationModel
    label: str
    description: str
    sector_keywords: tuple[str, ...]
    industry_keywords: tuple[str, ...]
    sic_ranges: tuple[tuple[int, int], ...]
    required_fields: tuple[SelectionField, ...]
    requires_profitability: bool | None = None
    prefers_preprofit: bool = False
    prefers_high_growth: bool = False
    base_score: float = 0.0


@dataclass(frozen=True)
class SelectionSignals:
    sector: str
    industry: str
    sic: int | None
    revenue_cagr: float | None
    is_profitable: bool | None
    net_income: float | None
    operating_cash_flow: float | None
    total_equity: float | None
    data_coverage: dict[SelectionField, bool]


@dataclass(frozen=True)
class ModelCandidate:
    model: ValuationModel
    score: float
    reasons: tuple[str, ...]
    missing_fields: tuple[str, ...]


@dataclass(frozen=True)
class ModelSelectionResult:
    model: ValuationModel
    reasoning: str
    candidates: tuple[ModelCandidate, ...]
    signals: SelectionSignals


@dataclass(frozen=True)
class ScoringWeights:
    sector_match: float = 2.0
    industry_match: float = 2.5
    sic_match: float = 3.0
    profitable_bonus: float = 1.0
    unprofitable_penalty: float = 2.5
    profitability_unknown_penalty: float = 0.5
    profitable_mismatch_penalty: float = 0.5
    preprofit_fit_bonus: float = 1.0
    preprofit_preference_bonus: float = 0.5
    high_growth_threshold: float = 0.15
    high_growth_bonus: float = 1.5
    low_growth_threshold: float = 0.05
    low_growth_penalty: float = 0.5
    coverage_ratio_multiplier: float = 1.5


DEFAULT_SCORING_WEIGHTS = ScoringWeights()
