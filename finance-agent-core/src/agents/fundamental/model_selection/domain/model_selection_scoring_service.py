from __future__ import annotations

from .model_selection_contracts import (
    DEFAULT_SCORING_WEIGHTS,
    ModelCandidate,
    ModelSpec,
    ScoringWeights,
    SelectionSignals,
)


def evaluate_model_spec(
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
    return any(keyword in text for keyword in keywords)
