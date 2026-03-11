"""Thin entrypoint for valuation model selection.

This module keeps public API stability while delegating capability owners:
- contracts/spec catalog
- signal extraction
- per-model scoring
- reasoning formatting
"""

from __future__ import annotations

import logging

from src.agents.fundamental.subdomains.core_valuation.domain.valuation_model import (
    ValuationModel,
)
from src.agents.fundamental.subdomains.model_selection.domain.entities import (
    FundamentalSelectionReport,
)
from src.shared.cross_agent.domain.market_identity import CompanyProfile
from src.shared.kernel.tools.logger import get_logger, log_event

from .model_selection_contracts import (
    DEFAULT_SCORING_WEIGHTS,
    ModelCandidate,
    ModelSelectionResult,
    ModelSpec,
    ScoringWeights,
    SelectionField,
    SelectionSignals,
)
from .model_selection_scoring_service import evaluate_model_spec
from .model_selection_signal_service import collect_selection_signals
from .model_selection_spec_catalog import MODEL_SPECS

logger = get_logger(__name__)


def _evaluate_spec(
    spec: ModelSpec,
    signals: SelectionSignals,
    *,
    weights: ScoringWeights = DEFAULT_SCORING_WEIGHTS,
) -> ModelCandidate:
    return evaluate_model_spec(spec, signals, weights=weights)


def build_model_selection_reasoning(
    *,
    signals: SelectionSignals,
    ranked_candidates: tuple[ModelCandidate, ...],
) -> str:
    reasons: list[str] = [
        f"Sector/Industry: {signals.sector or 'unknown'} / {signals.industry or 'unknown'}"
    ]
    if signals.sic is not None:
        reasons.append(f"SIC: {signals.sic}")
    if signals.revenue_cagr is not None:
        reasons.append(f"Revenue CAGR: {signals.revenue_cagr:.1%}")
    if signals.is_profitable is not None:
        reasons.append(f"Profitable: {'Yes' if signals.is_profitable else 'No'}")

    candidate_lines: list[str] = []
    for candidate in ranked_candidates[:3]:
        missing = (
            f" (missing: {', '.join(candidate.missing_fields)})"
            if candidate.missing_fields
            else ""
        )
        candidate_lines.append(
            f"- {candidate.model.value}: score {candidate.score:.2f} | "
            f"{', '.join(candidate.reasons)}{missing}"
        )

    return "\n".join(
        ["Model selection signals:"]
        + [f"- {line}" for line in reasons]
        + candidate_lines
    )


def select_valuation_model(
    profile: CompanyProfile,
    financial_reports: list[FundamentalSelectionReport] | None = None,
    *,
    weights: ScoringWeights = DEFAULT_SCORING_WEIGHTS,
) -> ModelSelectionResult:
    """Select valuation model using domain signals, catalog scoring, and reasoning."""
    signals = collect_selection_signals(profile, financial_reports)

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

    ranked_candidates = tuple(
        sorted(candidates, key=lambda candidate: candidate.score, reverse=True)
    )
    top_candidate = ranked_candidates[0]

    reasoning = build_model_selection_reasoning(
        signals=signals,
        ranked_candidates=ranked_candidates,
    )

    return ModelSelectionResult(
        model=top_candidate.model,
        reasoning=reasoning,
        candidates=ranked_candidates,
        signals=signals,
    )


__all__ = [
    "DEFAULT_SCORING_WEIGHTS",
    "MODEL_SPECS",
    "ModelCandidate",
    "ModelSelectionResult",
    "ModelSpec",
    "ScoringWeights",
    "SelectionField",
    "SelectionSignals",
    "_evaluate_spec",
    "select_valuation_model",
]
