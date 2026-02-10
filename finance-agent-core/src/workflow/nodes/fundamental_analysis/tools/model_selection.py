"""
Model selection logic for the Fundamental Analysis Node.

Implements an enterprise-grade model registry with scoring based on sector,
industry, SIC, financial signals, and data coverage.
"""

from dataclasses import dataclass

from src.common.tools.logger import get_logger

from ..structures import CompanyProfile, ValuationModel

logger = get_logger(__name__)


@dataclass(frozen=True)
class ModelSpec:
    model: ValuationModel
    label: str
    description: str
    sector_keywords: tuple[str, ...]
    industry_keywords: tuple[str, ...]
    sic_ranges: tuple[tuple[int, int], ...]
    required_fields: tuple[str, ...]
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
    data_coverage: dict[str, bool]


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


MODEL_SPECS: tuple[ModelSpec, ...] = (
    ModelSpec(
        model=ValuationModel.DDM,
        label="Dividend Discount Model",
        description="Best for regulated, dividend-centric businesses (banks/utilities).",
        sector_keywords=("financial", "bank", "utilities", "utility"),
        industry_keywords=("bank", "banking", "regional bank", "utility"),
        sic_ranges=((6000, 6999),),
        required_fields=("base.net_income", "base.total_equity"),
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
        required_fields=("base.net_income", "extension.ffo"),
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
            "base.total_revenue",
            "base.operating_cash_flow",
            "base.net_income",
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
            "base.total_revenue",
            "base.operating_cash_flow",
            "base.net_income",
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
        required_fields=("base.total_revenue",),
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
        required_fields=("base.total_revenue", "base.net_income"),
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
        required_fields=("base.net_income", "base.total_equity"),
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
        required_fields=("base.net_income", "base.total_assets"),
        requires_profitability=True,
        base_score=0.2,
    ),
)


def _normalize(text: str | None) -> str:
    return (text or "").strip().lower()


def _extract_path(report: dict, path: str) -> float | str | None:
    cur: object | None = report
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    if isinstance(cur, dict):
        val = cur.get("value")
        return val
    return cur  # Could be None or scalar


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


def _calculate_cagr(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    latest = values[0]
    earliest = values[-1]
    if latest <= 0 or earliest <= 0:
        return None
    years = len(values) - 1
    return (latest / earliest) ** (1 / years) - 1


def _collect_signals(
    profile: CompanyProfile, financial_reports: list[dict] | None
) -> SelectionSignals:
    sector = _normalize(profile.sector)
    industry = _normalize(profile.industry)

    latest_report = financial_reports[0] if financial_reports else {}
    sic_raw = _extract_path(latest_report, "base.sic_code")
    sic = None
    if sic_raw is not None:
        try:
            sic = int(sic_raw)
        except (ValueError, TypeError):
            sic = None

    net_income_val = _extract_path(latest_report, "base.net_income")
    ocf_val = _extract_path(latest_report, "base.operating_cash_flow")
    equity_val = _extract_path(latest_report, "base.total_equity")

    net_income = (
        float(net_income_val) if isinstance(net_income_val, int | float) else None
    )
    operating_cash_flow = float(ocf_val) if isinstance(ocf_val, int | float) else None
    total_equity = float(equity_val) if isinstance(equity_val, int | float) else None

    if profile.is_profitable is not None:
        is_profitable = profile.is_profitable
    else:
        is_profitable = net_income > 0 if net_income is not None else None

    revenue_series: list[float] = []
    if financial_reports:
        for rep in financial_reports:
            rev_val = _extract_path(rep, "base.total_revenue")
            if isinstance(rev_val, int | float):
                revenue_series.append(float(rev_val))
    revenue_cagr = _calculate_cagr(revenue_series)

    data_coverage: dict[str, bool] = {}
    fields_to_check = {
        "base.total_revenue",
        "base.net_income",
        "base.operating_cash_flow",
        "base.total_equity",
        "base.total_assets",
        "extension.ffo",
    }
    for field in fields_to_check:
        data_coverage[field] = _extract_path(latest_report, field) is not None

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


def _evaluate_spec(spec: ModelSpec, signals: SelectionSignals) -> ModelCandidate:
    score = spec.base_score
    reasons: list[str] = []

    if _matches_keywords(signals.sector, spec.sector_keywords):
        score += 2.0
        reasons.append("Sector match")
    if _matches_keywords(signals.industry, spec.industry_keywords):
        score += 2.5
        reasons.append("Industry match")
    if _in_sic_ranges(signals.sic, spec.sic_ranges):
        score += 3.0
        reasons.append("SIC match")

    if spec.requires_profitability is True:
        if signals.is_profitable is True:
            score += 1.0
            reasons.append("Profitable")
        elif signals.is_profitable is False:
            score -= 2.5
            reasons.append("Not profitable")
        else:
            score -= 0.5
            reasons.append("Profitability unknown")
    elif spec.requires_profitability is False:
        if signals.is_profitable is False:
            score += 1.0
            reasons.append("Pre-profit fit")
        elif signals.is_profitable is True:
            score -= 0.5
            reasons.append("Profitable mismatch")

    if spec.prefers_preprofit and signals.is_profitable is False:
        score += 0.5
    if spec.prefers_high_growth and signals.revenue_cagr is not None:
        if signals.revenue_cagr >= 0.15:
            score += 1.5
            reasons.append("High growth")
        elif signals.revenue_cagr <= 0.05:
            score -= 0.5
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
        score += coverage_ratio * 1.5
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
    profile: CompanyProfile, financial_reports: list[dict] | None = None
) -> ModelSelectionResult:
    """
    Select the appropriate valuation model based on company characteristics and data coverage.
    """
    signals = _collect_signals(profile, financial_reports)

    candidates = tuple(_evaluate_spec(spec, signals) for spec in MODEL_SPECS)
    if not candidates:
        logger.warning("No model candidates generated; defaulting to DCF_STANDARD.")
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


def should_request_clarification(
    candidates: list, confidence_threshold: float = 0.85
) -> bool:
    """
    Determine if human clarification is needed for ticker resolution.

    Args:
        candidates: List of ticker candidates
        confidence_threshold: Minimum confidence to auto-select

    Returns:
        True if clarification is needed
    """
    if not candidates:
        return True  # No matches found

    if len(candidates) == 1 and candidates[0].confidence >= confidence_threshold:
        return False  # Single high-confidence match

    if len(candidates) > 1:
        # Check if top two candidates are very close in confidence
        if len(candidates) >= 2:
            top_conf = candidates[0].confidence
            second_conf = candidates[1].confidence
            # Relaxed threshold to catch cases like GOOG (0.9) vs GOOGL (1.0)
            # where the difference is exactly 0.1
            if abs(top_conf - second_conf) <= 0.15:  # Ambiguous
                return True
        # If we have multiple candidates but they're not close in confidence,
        # still ask for clarification to be safe
        return True

    return False
