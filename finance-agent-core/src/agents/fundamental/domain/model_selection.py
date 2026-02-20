"""
Model selection logic for the Fundamental Analysis Node.

Implements an enterprise-grade model registry with scoring based on sector,
industry, SIC, financial signals, and data coverage.
"""

import logging
from dataclasses import dataclass
from typing import Literal

from src.agents.fundamental.domain.entities import FundamentalSelectionReport
from src.agents.fundamental.domain.rules import calculate_cagr
from src.shared.cross_agent.domain.market_identity import CompanyProfile
from src.shared.kernel.tools.logger import get_logger, log_event

from .models import ValuationModel

logger = get_logger(__name__)

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


MODEL_SPECS: tuple[ModelSpec, ...] = (
    ModelSpec(
        model=ValuationModel.DDM,
        label="Dividend Discount Model",
        description="Best for regulated, dividend-centric businesses (banks/utilities).",
        sector_keywords=("financial", "bank", "utilities", "utility"),
        industry_keywords=("bank", "banking", "regional bank", "utility"),
        sic_ranges=((6000, 6999),),
        required_fields=("net_income", "total_equity"),
        requires_profitability=True,
        base_score=3.0,
    ),
    ModelSpec(
        model=ValuationModel.FFO,
        label="FFO (REIT)",
        description="Adjusts for non-cash depreciation in real estate companies.",
        sector_keywords=("real estate",),
        industry_keywords=("reit", "real estate"),
        sic_ranges=((6798, 6798),),
        required_fields=("net_income", "extension_ffo"),
        requires_profitability=None,
        base_score=3.0,
    ),
    ModelSpec(
        model=ValuationModel.DCF_GROWTH,
        label="DCF (Growth)",
        description="Growth-adjusted DCF for high-growth tech or reinvestment-heavy firms.",
        sector_keywords=(
            "technology",
            "information technology",
            "communication services",
        ),
        industry_keywords=("software", "saas", "internet", "semiconductor", "cloud"),
        sic_ranges=(),
        required_fields=(
            "total_revenue",
            "operating_cash_flow",
            "net_income",
        ),
        requires_profitability=None,
        prefers_high_growth=True,
        base_score=2.0,
    ),
    ModelSpec(
        model=ValuationModel.DCF_STANDARD,
        label="DCF (Standard)",
        description="Stable cash flow businesses with predictable economics.",
        sector_keywords=("industrial", "material", "energy", "consumer", "health care"),
        industry_keywords=("manufacturing", "consumer", "pharma", "energy"),
        sic_ranges=(),
        required_fields=(
            "total_revenue",
            "operating_cash_flow",
            "net_income",
        ),
        requires_profitability=True,
        base_score=1.5,
    ),
    ModelSpec(
        model=ValuationModel.EV_REVENUE,
        label="EV/Revenue",
        description="Pre-profit companies with strong top-line growth.",
        sector_keywords=("technology", "communication services"),
        industry_keywords=("software", "saas", "internet", "biotech"),
        sic_ranges=(),
        required_fields=("total_revenue",),
        requires_profitability=False,
        prefers_preprofit=True,
        prefers_high_growth=True,
        base_score=1.0,
    ),
    ModelSpec(
        model=ValuationModel.EV_EBITDA,
        label="EV/EBITDA",
        description="Comparables-based valuation for positive EBITDA businesses.",
        sector_keywords=(),
        industry_keywords=(),
        sic_ranges=(),
        required_fields=("total_revenue", "net_income"),
        requires_profitability=True,
        base_score=0.5,
    ),
    ModelSpec(
        model=ValuationModel.RESIDUAL_INCOME,
        label="Residual Income",
        description="Equity valuation based on excess returns over required return.",
        sector_keywords=("financial", "bank", "insurance"),
        industry_keywords=("bank", "insurance", "financial"),
        sic_ranges=((6000, 6999),),
        required_fields=("net_income", "total_equity"),
        requires_profitability=True,
        base_score=0.3,
    ),
    ModelSpec(
        model=ValuationModel.EVA,
        label="EVA",
        description="Firm valuation based on economic value added.",
        sector_keywords=(),
        industry_keywords=(),
        sic_ranges=(),
        required_fields=("net_income", "total_assets"),
        requires_profitability=True,
        base_score=0.2,
    ),
)


def _normalize(text: str | None) -> str:
    return (text or "").strip().lower()


def _in_sic_ranges(sic: int | None, ranges: tuple[tuple[int, int], ...]) -> bool:
    if sic is None or not ranges:
        return False
    for start, end in ranges:
        if start <= sic <= end:
            return True
    return False


def _matches_keywords(text: str, keywords: tuple[str, ...]) -> bool:
    if not keywords:
        return False
    return any(k in text for k in keywords)


def _latest_report(
    financial_reports: list[FundamentalSelectionReport],
) -> FundamentalSelectionReport | None:
    if not financial_reports:
        return None
    return financial_reports[0]


def _collect_signals(
    profile: CompanyProfile,
    financial_reports: list[FundamentalSelectionReport] | None,
) -> SelectionSignals:
    sector = _normalize(profile.sector)
    industry = _normalize(profile.industry)

    reports = financial_reports or []
    latest = _latest_report(reports)
    sic = latest.sic_code if latest is not None else None
    net_income = latest.net_income if latest is not None else None
    operating_cash_flow = latest.operating_cash_flow if latest is not None else None
    total_equity = latest.total_equity if latest is not None else None

    if profile.is_profitable is not None:
        is_profitable = profile.is_profitable
    else:
        is_profitable = net_income > 0 if net_income is not None else None

    revenue_series = [r.total_revenue for r in reports if r.total_revenue is not None]
    revenue_cagr = calculate_cagr(revenue_series)

    fields_to_check: tuple[SelectionField, ...] = (
        "total_revenue",
        "net_income",
        "operating_cash_flow",
        "total_equity",
        "total_assets",
        "extension_ffo",
    )
    data_coverage: dict[SelectionField, bool] = {
        field: (latest is not None and getattr(latest, field) is not None)
        for field in fields_to_check
    }

    return SelectionSignals(
        sector=sector,
        industry=industry,
        sic=sic,
        revenue_cagr=revenue_cagr,
        is_profitable=is_profitable,
        net_income=net_income,
        operating_cash_flow=operating_cash_flow,
        total_equity=total_equity,
        data_coverage=data_coverage,
    )


def _evaluate_spec(
    spec: ModelSpec,
    signals: SelectionSignals,
    *,
    weights: ScoringWeights = DEFAULT_SCORING_WEIGHTS,
) -> ModelCandidate:
    score = spec.base_score
    reasons: list[str] = []

    if _matches_keywords(signals.sector, spec.sector_keywords):
        score += weights.sector_match
        reasons.append("Sector match")
    if _matches_keywords(signals.industry, spec.industry_keywords):
        score += weights.industry_match
        reasons.append("Industry match")
    if _in_sic_ranges(signals.sic, spec.sic_ranges):
        score += weights.sic_match
        reasons.append("SIC match")

    if spec.requires_profitability is True:
        if signals.is_profitable is True:
            score += weights.profitable_bonus
            reasons.append("Profitable")
        elif signals.is_profitable is False:
            score -= weights.unprofitable_penalty
            reasons.append("Not profitable")
        else:
            score -= weights.profitability_unknown_penalty
            reasons.append("Profitability unknown")
    elif spec.requires_profitability is False:
        if signals.is_profitable is False:
            score += weights.preprofit_fit_bonus
            reasons.append("Pre-profit fit")
        elif signals.is_profitable is True:
            score -= weights.profitable_mismatch_penalty
            reasons.append("Profitable mismatch")

    if spec.prefers_preprofit and signals.is_profitable is False:
        score += weights.preprofit_preference_bonus
    if spec.prefers_high_growth and signals.revenue_cagr is not None:
        if signals.revenue_cagr >= weights.high_growth_threshold:
            score += weights.high_growth_bonus
            reasons.append("High growth")
        elif signals.revenue_cagr <= weights.low_growth_threshold:
            score -= weights.low_growth_penalty
            reasons.append("Low growth")

    missing = []
    available = 0
    for field in spec.required_fields:
        if signals.data_coverage.get(field, False):
            available += 1
        else:
            missing.append(field)

    if spec.required_fields:
        coverage_ratio = available / len(spec.required_fields)
        score += coverage_ratio * weights.coverage_ratio_multiplier
        if missing:
            reasons.append("Partial data coverage")
        else:
            reasons.append("Full data coverage")

    return ModelCandidate(
        model=spec.model,
        score=score,
        reasons=tuple(reasons),
        missing_fields=tuple(missing),
    )


def select_valuation_model(
    profile: CompanyProfile,
    financial_reports: list[FundamentalSelectionReport] | None = None,
    *,
    weights: ScoringWeights = DEFAULT_SCORING_WEIGHTS,
) -> ModelSelectionResult:
    """
    Select the appropriate valuation model based on company characteristics and data coverage.
    """
    signals = _collect_signals(profile, financial_reports)

    candidates = tuple(
        _evaluate_spec(spec, signals, weights=weights) for spec in MODEL_SPECS
    )
    if not candidates:
        log_event(
            logger,
            event="fundamental_model_candidates_missing",
            message="no model candidates generated; defaulting to dcf_standard",
            level=logging.WARNING,
            error_code="FUNDAMENTAL_MODEL_DEFAULTED",
        )
        return ModelSelectionResult(
            model=ValuationModel.DCF_STANDARD,
            reasoning="No model candidates generated; defaulting to standard DCF.",
            candidates=(),
            signals=signals,
        )

    top = sorted(candidates, key=lambda c: c.score, reverse=True)[0]

    reasons = []
    reasons.append(
        f"Sector/Industry: {signals.sector or 'unknown'} / {signals.industry or 'unknown'}"
    )
    if signals.sic is not None:
        reasons.append(f"SIC: {signals.sic}")
    if signals.revenue_cagr is not None:
        reasons.append(f"Revenue CAGR: {signals.revenue_cagr:.1%}")
    if signals.is_profitable is not None:
        reasons.append(f"Profitable: {'Yes' if signals.is_profitable else 'No'}")

    candidate_lines = []
    for c in sorted(candidates, key=lambda x: x.score, reverse=True)[:3]:
        missing = (
            f" (missing: {', '.join(c.missing_fields)})" if c.missing_fields else ""
        )
        candidate_lines.append(
            f"- {c.model.value}: score {c.score:.2f} | {', '.join(c.reasons)}{missing}"
        )

    reasoning = "\n".join(
        ["Model selection signals:"] + [f"- {r}" for r in reasons] + candidate_lines
    )

    return ModelSelectionResult(
        model=top.model,
        reasoning=reasoning,
        candidates=tuple(sorted(candidates, key=lambda c: c.score, reverse=True)),
        signals=signals,
    )
