from __future__ import annotations

from src.agents.fundamental.domain.valuation.skills.valuation_saas.schemas import (
    SaaSParams,
)
from src.agents.fundamental.domain.valuation.skills.valuation_saas.tools import (
    calculate_saas_valuation,
)
from src.shared.kernel.traceable import ManualProvenance, TraceableField


def test_saas_valuation_includes_distribution_summary_when_mc_enabled() -> None:
    params = SaaSParams(
        ticker="SAAS",
        rationale="test",
        initial_revenue=100.0,
        growth_rates=[0.15, 0.14, 0.12, 0.10, 0.08],
        operating_margins=[0.10, 0.12, 0.14, 0.16, 0.18],
        tax_rate=0.21,
        da_rates=[0.03, 0.03, 0.03, 0.03, 0.03],
        capex_rates=[0.05, 0.05, 0.05, 0.05, 0.05],
        wc_rates=[0.01, 0.01, 0.01, 0.01, 0.01],
        sbc_rates=[0.02, 0.02, 0.02, 0.02, 0.02],
        wacc=0.10,
        terminal_growth=0.025,
        shares_outstanding=100.0,
        cash=10.0,
        total_debt=5.0,
        preferred_stock=0.0,
        monte_carlo_iterations=300,
        monte_carlo_seed=123,
    )

    result = calculate_saas_valuation(params)
    assert "error" not in result
    details = result["details"]
    assert isinstance(details, dict)
    distribution = details.get("distribution_summary")
    assert isinstance(distribution, dict)
    summary = distribution.get("summary")
    assert isinstance(summary, dict)
    assert "percentile_5" in summary
    assert "median" in summary
    assert "percentile_95" in summary


def test_saas_valuation_monte_carlo_handles_traceable_inputs() -> None:
    params = SaaSParams(
        ticker="SAAS",
        rationale="test",
        initial_revenue=100.0,
        growth_rates=[0.15, 0.14, 0.12, 0.10, 0.08],
        operating_margins=[0.10, 0.12, 0.14, 0.16, 0.18],
        tax_rate=0.21,
        da_rates=[0.03, 0.03, 0.03, 0.03, 0.03],
        capex_rates=[0.05, 0.05, 0.05, 0.05, 0.05],
        wc_rates=[0.01, 0.01, 0.01, 0.01, 0.01],
        sbc_rates=[0.02, 0.02, 0.02, 0.02, 0.02],
        wacc=0.10,
        terminal_growth=0.025,
        shares_outstanding=100.0,
        cash=10.0,
        total_debt=5.0,
        preferred_stock=0.0,
        monte_carlo_iterations=200,
        monte_carlo_seed=99,
        trace_inputs={
            "growth_rates": TraceableField(
                name="growth_rates",
                value=[0.15, 0.14, 0.12, 0.10, 0.08],
                provenance=ManualProvenance(description="test"),
            )
        },
    )

    result = calculate_saas_valuation(params)
    assert "error" not in result
    details = result["details"]
    assert isinstance(details, dict)
    distribution = details.get("distribution_summary")
    assert isinstance(distribution, dict)
