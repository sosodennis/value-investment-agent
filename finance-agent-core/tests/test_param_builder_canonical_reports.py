from __future__ import annotations

from src.agents.fundamental.domain.valuation.param_builder import (
    build_params,
)
from src.agents.fundamental.interface.contracts import parse_financial_reports_model


def _tf(value: float | str) -> dict[str, object]:
    return {
        "value": value,
        "provenance": {"type": "MANUAL", "description": "test"},
    }


def _raw_reports() -> list[dict[str, object]]:
    return [
        {
            "industry_type": "Industrial",
            "base": {
                "fiscal_year": _tf("2024"),
                "fiscal_period": _tf("FY"),
                "company_name": _tf("Example Inc."),
                "cik": _tf("0000000001"),
                "sic_code": _tf("7372"),
                "shares_outstanding": _tf(1000.0),
                "total_revenue": _tf(1000.0),
                "net_income": _tf(120.0),
                "income_tax_expense": _tf(30.0),
                "total_assets": _tf(2000.0),
                "total_liabilities": _tf(800.0),
                "total_equity": _tf(1200.0),
                "cash_and_equivalents": _tf(300.0),
                "operating_cash_flow": _tf(150.0),
                "operating_income": _tf(180.0),
                "income_before_tax": _tf(150.0),
                "depreciation_and_amortization": _tf(40.0),
                "share_based_compensation": _tf(20.0),
                "current_assets": _tf(900.0),
                "current_liabilities": _tf(400.0),
                "total_debt": _tf(200.0),
                "preferred_stock": _tf(10.0),
            },
            "extension": {"capex": _tf(50.0)},
        },
        {
            "industry_type": "Industrial",
            "base": {
                "fiscal_year": _tf("2023"),
                "fiscal_period": _tf("FY"),
                "company_name": _tf("Example Inc."),
                "cik": _tf("0000000001"),
                "sic_code": _tf("7372"),
                "shares_outstanding": _tf(1000.0),
                "total_revenue": _tf(900.0),
                "net_income": _tf(100.0),
                "income_tax_expense": _tf(28.0),
                "total_assets": _tf(1900.0),
                "total_liabilities": _tf(790.0),
                "total_equity": _tf(1110.0),
                "cash_and_equivalents": _tf(250.0),
                "operating_cash_flow": _tf(130.0),
                "operating_income": _tf(150.0),
                "income_before_tax": _tf(130.0),
                "depreciation_and_amortization": _tf(35.0),
                "share_based_compensation": _tf(18.0),
                "current_assets": _tf(850.0),
                "current_liabilities": _tf(390.0),
                "total_debt": _tf(210.0),
                "preferred_stock": _tf(10.0),
            },
            "extension": {"capex": _tf(45.0)},
        },
    ]


def _raw_bank_reports() -> list[dict[str, object]]:
    return [
        {
            "industry_type": "FinancialServices",
            "base": {
                "fiscal_year": _tf("2024"),
                "total_assets": _tf(2000.0),
                "total_equity": _tf(300.0),
                "net_income": _tf(30.0),
            },
            "extension": {
                "risk_weighted_assets": _tf(1200.0),
                "tier1_capital_ratio": _tf(0.12),
            },
        },
        {
            "industry_type": "FinancialServices",
            "base": {
                "fiscal_year": _tf("2023"),
                "total_assets": _tf(1800.0),
                "total_equity": _tf(280.0),
                "net_income": _tf(25.0),
            },
            "extension": {
                "risk_weighted_assets": _tf(1100.0),
                "tier1_capital_ratio": _tf(0.11),
            },
        },
    ]


def _raw_reit_reports() -> list[dict[str, object]]:
    return [
        {
            "industry_type": "RealEstate",
            "base": {
                "fiscal_year": _tf("2024"),
                "shares_outstanding": _tf(1000.0),
                "cash_and_equivalents": _tf(100.0),
                "total_debt": _tf(300.0),
                "preferred_stock": _tf(0.0),
                "depreciation_and_amortization": _tf(50.0),
            },
            "extension": {"ffo": _tf(120.0)},
        }
    ]


def test_build_params_accepts_canonicalized_financial_reports() -> None:
    raw_reports = _raw_reports()

    canonical_reports = parse_financial_reports_model(
        raw_reports, context="test.financial_reports"
    )
    result = build_params("saas", "EXM", canonical_reports)

    assert result.params["ticker"] == "EXM"
    assert not result.missing


def test_build_params_prefers_market_shares_when_available() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports"
    )
    result = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "shares_outstanding": 1200.0,
            "current_price": 77.5,
            "consensus_growth_rate": 0.50,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    assert result.params["shares_outstanding"] == 1200.0
    assert result.params["current_price"] == 77.5
    shares_input = result.trace_inputs["shares_outstanding"]
    assert shares_input.value == 1200.0
    assert "shares_outstanding sourced from market data" in result.assumptions
    growth_rates = result.params["growth_rates"]
    assert isinstance(growth_rates, list)
    assert growth_rates[0] > growth_rates[-1]
    assert "growth_rates blended via context-aware weights" in "; ".join(
        result.assumptions
    )
    assert result.params["monte_carlo_iterations"] == 300
    assert result.params["monte_carlo_seed"] == 42


def test_build_params_does_not_infer_shares_from_market_cap_price() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports"
    )
    result = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "market_cap": 100_000.0,
            "current_price": 50.0,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    assert result.params["shares_outstanding"] == 1000.0
    assert "shares_outstanding sourced from market data" not in result.assumptions


def test_build_params_bank_includes_capm_inputs() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_bank_reports(), context="test.financial_reports.bank"
    )
    result = build_params(
        "bank",
        "BNK",
        canonical_reports,
        market_snapshot={
            "risk_free_rate": 0.041,
            "beta": 1.25,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    assert result.params["risk_free_rate"] == 0.041
    assert result.params["beta"] == 1.25
    assert result.params["market_risk_premium"] == 0.05
    assert result.params["cost_of_equity_strategy"] == "capm"
    assert result.params["terminal_growth"] == 0.02
    assert result.params["monte_carlo_iterations"] == 300
    assert result.params["monte_carlo_seed"] == 42
    assert "terminal_growth defaulted to 2.00%" in result.assumptions


def test_build_params_reit_supports_configurable_maintenance_capex_ratio() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reit_reports(), context="test.financial_reports.reit"
    )
    result = build_params(
        "reit_ffo",
        "REIT",
        canonical_reports,
        market_snapshot={
            "maintenance_capex_ratio": 0.65,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    assert result.params["maintenance_capex_ratio"] == 0.65
    assert result.params["depreciation_and_amortization"] == 50.0
    assert result.params["monte_carlo_iterations"] == 300
    assert result.params["monte_carlo_seed"] == 42


def test_build_params_can_disable_monte_carlo_via_env(monkeypatch) -> None:
    monkeypatch.setenv("FUNDAMENTAL_MONTE_CARLO_ENABLED", "false")
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports"
    )
    result = build_params("saas", "EXM", canonical_reports)

    assert result.params["monte_carlo_iterations"] == 0
    assert "monte_carlo disabled by policy" in result.assumptions
