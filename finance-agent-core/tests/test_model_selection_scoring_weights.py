from __future__ import annotations

from src.agents.fundamental.domain.model_selection import (
    DEFAULT_SCORING_WEIGHTS,
    MODEL_SPECS,
    ScoringWeights,
    SelectionSignals,
    _evaluate_spec,
)
from src.agents.fundamental.domain.models import ValuationModel


def test_evaluate_spec_uses_configurable_scoring_weights() -> None:
    ddm_spec = next(spec for spec in MODEL_SPECS if spec.model == ValuationModel.DDM)
    signals = SelectionSignals(
        sector="financial",
        industry="banking",
        sic=6200,
        revenue_cagr=0.08,
        is_profitable=True,
        net_income=100.0,
        operating_cash_flow=120.0,
        total_equity=500.0,
        data_coverage={
            "total_revenue": True,
            "net_income": True,
            "operating_cash_flow": True,
            "total_equity": True,
            "total_assets": True,
            "extension_ffo": False,
        },
    )

    default_candidate = _evaluate_spec(
        ddm_spec, signals, weights=DEFAULT_SCORING_WEIGHTS
    )
    custom_weights = ScoringWeights(
        sector_match=0.0,
        industry_match=0.0,
        sic_match=0.0,
    )
    custom_candidate = _evaluate_spec(ddm_spec, signals, weights=custom_weights)

    assert default_candidate.score > custom_candidate.score
    assert round(default_candidate.score - custom_candidate.score, 6) == 7.5
