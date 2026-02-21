from __future__ import annotations

import pytest

from src.agents.fundamental.domain.valuation.skills.valuation_bank.schemas import (
    BankParams,
)
from src.agents.fundamental.domain.valuation.skills.valuation_bank.tools import (
    calculate_bank_valuation,
)
from src.agents.fundamental.domain.valuation.skills.valuation_reit_ffo.schemas import (
    ReitFfoParams,
)
from src.agents.fundamental.domain.valuation.skills.valuation_reit_ffo.tools import (
    calculate_reit_ffo_valuation,
)
from src.shared.kernel.traceable import ManualProvenance, TraceableField


def test_bank_valuation_uses_capm_when_strategy_is_capm() -> None:
    params = BankParams(
        ticker="BNK",
        rationale="test",
        initial_net_income=100.0,
        income_growth_rates=[0.05, 0.05, 0.05],
        rwa_intensity=0.05,
        tier1_target_ratio=0.12,
        initial_capital=200.0,
        risk_free_rate=0.04,
        beta=1.1,
        market_risk_premium=0.05,
        cost_of_equity_strategy="capm",
        terminal_growth=0.02,
    )

    result = calculate_bank_valuation(params)
    assert "error" not in result
    assert result["cost_of_equity"] == pytest.approx(0.095)


def test_bank_valuation_uses_manual_override_strategy() -> None:
    params = BankParams(
        ticker="BNK",
        rationale="test",
        initial_net_income=100.0,
        income_growth_rates=[0.05, 0.05, 0.05],
        rwa_intensity=0.05,
        tier1_target_ratio=0.12,
        initial_capital=200.0,
        risk_free_rate=0.04,
        beta=1.1,
        market_risk_premium=0.05,
        cost_of_equity_strategy="override",
        cost_of_equity_override=0.20,
        terminal_growth=0.02,
    )

    result = calculate_bank_valuation(params)
    assert "error" not in result
    assert result["cost_of_equity"] == pytest.approx(0.20)


def test_bank_valuation_includes_distribution_summary_when_mc_enabled() -> None:
    params = BankParams(
        ticker="BNK",
        rationale="test",
        initial_net_income=100.0,
        income_growth_rates=[0.05, 0.05, 0.05],
        rwa_intensity=0.05,
        tier1_target_ratio=0.12,
        initial_capital=200.0,
        risk_free_rate=0.04,
        beta=1.1,
        market_risk_premium=0.05,
        cost_of_equity_strategy="capm",
        terminal_growth=0.02,
        monte_carlo_iterations=300,
        monte_carlo_seed=123,
    )

    result = calculate_bank_valuation(params)
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


def test_bank_valuation_monte_carlo_handles_traceable_growth_inputs() -> None:
    params = BankParams(
        ticker="BNK",
        rationale="test",
        initial_net_income=100.0,
        income_growth_rates=[0.05, 0.05, 0.05],
        rwa_intensity=0.05,
        tier1_target_ratio=0.12,
        initial_capital=200.0,
        risk_free_rate=0.04,
        beta=1.1,
        market_risk_premium=0.05,
        cost_of_equity_strategy="capm",
        terminal_growth=0.02,
        monte_carlo_iterations=200,
        monte_carlo_seed=123,
        trace_inputs={
            "income_growth_rates": TraceableField(
                name="income_growth_rates",
                value=[0.05, 0.05, 0.05],
                provenance=ManualProvenance(description="test"),
            )
        },
    )

    result = calculate_bank_valuation(params)
    assert "error" not in result
    details = result["details"]
    assert isinstance(details, dict)
    distribution = details.get("distribution_summary")
    assert isinstance(distribution, dict)


def test_reit_valuation_uses_affo_like_adjustment() -> None:
    params = ReitFfoParams(
        ticker="REIT",
        rationale="test",
        ffo=100.0,
        ffo_multiple=10.0,
        depreciation_and_amortization=20.0,
        maintenance_capex_ratio=0.8,
        cash=10.0,
        total_debt=50.0,
        preferred_stock=0.0,
        shares_outstanding=10.0,
    )

    result = calculate_reit_ffo_valuation(params)
    assert "error" not in result
    details = result["details"]
    assert isinstance(details, dict)
    assert details["maintenance_capex"] == pytest.approx(16.0)
    assert details["affo"] == pytest.approx(84.0)
    assert result["enterprise_value"] == pytest.approx(840.0)
    assert result["equity_value"] == pytest.approx(800.0)
    assert result["intrinsic_value"] == pytest.approx(80.0)


def test_reit_valuation_includes_distribution_summary_when_mc_enabled() -> None:
    params = ReitFfoParams(
        ticker="REIT",
        rationale="test",
        ffo=100.0,
        ffo_multiple=10.0,
        depreciation_and_amortization=20.0,
        maintenance_capex_ratio=0.8,
        cash=10.0,
        total_debt=50.0,
        preferred_stock=0.0,
        shares_outstanding=10.0,
        monte_carlo_iterations=300,
        monte_carlo_seed=321,
    )

    result = calculate_reit_ffo_valuation(params)
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
