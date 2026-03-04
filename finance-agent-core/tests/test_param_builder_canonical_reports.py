from __future__ import annotations

import pytest

from src.agents.fundamental.domain.valuation.parameterization.orchestrator import (
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
            "extension_type": "Industrial",
            "base": {
                "fiscal_year": _tf("2024"),
                "fiscal_period": _tf("FY"),
                "period_end_date": _tf("2024-12-31"),
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
            "extension_type": "Industrial",
            "base": {
                "fiscal_year": _tf("2023"),
                "fiscal_period": _tf("FY"),
                "period_end_date": _tf("2023-12-31"),
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
            "extension_type": "FinancialServices",
            "base": {
                "fiscal_year": _tf("2024"),
                "total_assets": _tf(2000.0),
                "total_equity": _tf(300.0),
                "net_income": _tf(30.0),
                "shares_outstanding": _tf(10.0),
            },
            "extension": {
                "risk_weighted_assets": _tf(1200.0),
                "tier1_capital_ratio": _tf(0.12),
            },
        },
        {
            "industry_type": "FinancialServices",
            "extension_type": "FinancialServices",
            "base": {
                "fiscal_year": _tf("2023"),
                "total_assets": _tf(1800.0),
                "total_equity": _tf(280.0),
                "net_income": _tf(25.0),
                "shares_outstanding": _tf(10.0),
            },
            "extension": {
                "risk_weighted_assets": _tf(1100.0),
                "tier1_capital_ratio": _tf(0.11),
            },
        },
    ]


def _raw_bank_reports_with_latest_rwa_outlier() -> list[dict[str, object]]:
    return [
        {
            "industry_type": "FinancialServices",
            "extension_type": "FinancialServices",
            "base": {
                "fiscal_year": _tf("2024"),
                "total_assets": _tf(2000.0),
                "total_equity": _tf(300.0),
                "net_income": _tf(30.0),
                "shares_outstanding": _tf(10.0),
            },
            "extension": {
                "risk_weighted_assets": _tf(20.0),
                "tier1_capital_ratio": _tf(0.12),
            },
        },
        {
            "industry_type": "FinancialServices",
            "extension_type": "FinancialServices",
            "base": {
                "fiscal_year": _tf("2023"),
                "total_assets": _tf(1800.0),
                "total_equity": _tf(280.0),
                "net_income": _tf(25.0),
                "shares_outstanding": _tf(10.0),
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
            "extension_type": "RealEstate",
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


def test_build_params_dcf_standard_uses_dedicated_builder_variant() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.dcf_standard"
    )
    result = build_params("dcf_standard", "EXM", canonical_reports)

    assert result.params["model_variant"] == "dcf_standard"
    assert "model_variant=dcf_standard routed via dedicated param builder" in "; ".join(
        result.assumptions
    )


def test_build_params_dcf_growth_uses_dedicated_builder_variant() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.dcf_growth"
    )
    result = build_params("dcf_growth", "EXM", canonical_reports)

    assert result.params["model_variant"] == "dcf_growth"
    assert "model_variant=dcf_growth routed via dedicated param builder" in "; ".join(
        result.assumptions
    )


def test_build_params_forward_signal_adjustments_sync_trace_inputs() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.dcf_growth.forward_signal_sync"
    )
    baseline = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={"consensus_growth_rate": 0.25},
    )
    adjusted = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "consensus_growth_rate": 0.25,
            "forward_signals": [
                {
                    "signal_id": "sig-growth-down",
                    "source_type": "manual",
                    "metric": "growth_outlook",
                    "direction": "down",
                    "value": 120.0,
                    "unit": "basis_points",
                    "confidence": 0.8,
                    "evidence": [
                        {
                            "preview_text": "growth pressure",
                            "full_text": "growth pressure",
                            "source_url": "https://example.com/growth",
                        }
                    ],
                },
                {
                    "signal_id": "sig-margin-down",
                    "source_type": "mda",
                    "metric": "margin_outlook",
                    "direction": "down",
                    "value": 80.0,
                    "unit": "basis_points",
                    "confidence": 0.8,
                    "evidence": [
                        {
                            "preview_text": "margin pressure",
                            "full_text": "margin pressure",
                            "source_url": "https://example.com/margin",
                        }
                    ],
                },
            ],
        },
    )

    baseline_growth = baseline.params["growth_rates"]
    adjusted_growth = adjusted.params["growth_rates"]
    assert isinstance(baseline_growth, list)
    assert isinstance(adjusted_growth, list)
    assert adjusted_growth[0] < baseline_growth[0]

    baseline_margin = baseline.params["operating_margins"]
    adjusted_margin = adjusted.params["operating_margins"]
    assert isinstance(baseline_margin, list)
    assert isinstance(adjusted_margin, list)
    assert adjusted_margin[0] < baseline_margin[0]

    trace_growth = adjusted.trace_inputs["growth_rates"]
    trace_margin = adjusted.trace_inputs["operating_margins"]
    assert trace_growth.value == adjusted_growth
    assert trace_margin.value == adjusted_margin
    assert any(
        statement.startswith("forward_signal growth adjustment applied")
        for statement in adjusted.assumptions
    )
    assert any(
        statement.startswith("forward_signal margin adjustment applied")
        for statement in adjusted.assumptions
    )


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
    assert any(
        statement.startswith("shares_outstanding sourced from market data")
        for statement in result.assumptions
    )
    growth_rates = result.params["growth_rates"]
    assert isinstance(growth_rates, list)
    assert growth_rates[0] > growth_rates[-1]
    assert "growth_rates blended via context-aware weights" in "; ".join(
        result.assumptions
    )
    assert result.params["monte_carlo_iterations"] == 300
    assert result.params["monte_carlo_seed"] == 42
    assert result.params["monte_carlo_sampler"] == "sobol"


def test_build_params_saas_uses_market_aware_wacc_when_available() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.saas.market_wacc"
    )
    result = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "risk_free_rate": 0.04,
            "beta": 1.2,
            "consensus_growth_rate": 0.15,
            "long_run_growth_anchor": 0.03,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    assert result.params["risk_free_rate"] == 0.04
    assert result.params["beta"] == 1.2
    assert result.params["market_risk_premium"] == 0.05
    assert result.params["wacc"] == pytest.approx(0.10)
    assert result.params["terminal_growth"] == pytest.approx(0.03)
    assert "wacc sourced from market-aware CAPM inputs" in result.assumptions
    assert "terminal_growth sourced from long_run_growth_anchor" in result.assumptions


def test_build_params_saas_clamps_terminal_growth_against_wacc() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.saas.terminal_clamp"
    )
    result = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "risk_free_rate": 0.03,
            "beta": 0.50,
            "long_run_growth_anchor": 0.20,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    assert result.params["wacc"] == pytest.approx(0.055)
    assert result.params["terminal_growth"] == pytest.approx(0.04)
    assert any(
        "terminal_growth clamped from 20.00% to 4.00%" in s for s in result.assumptions
    )


def test_build_params_saas_clamps_beta_for_capm_stability() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.saas.beta_clamp"
    )
    result = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "risk_free_rate": 0.04,
            "beta": 2.40,
            "consensus_growth_rate": 0.15,
            "long_run_growth_anchor": 0.03,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    assert result.params["beta"] == pytest.approx(1.8)
    assert result.params["wacc"] == pytest.approx(0.13)
    assert any(
        "beta clamped from 2.400 to 1.800" in statement
        for statement in result.assumptions
    )


def test_build_params_saas_does_not_use_short_term_consensus_for_terminal_growth() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.saas.terminal_consensus_split"
    )
    result = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "risk_free_rate": 0.04,
            "beta": 1.2,
            "consensus_growth_rate": 0.25,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    assert result.params["terminal_growth"] == pytest.approx(0.02)
    assert (
        "terminal_growth sourced from long_run_growth_anchor" not in result.assumptions
    )
    assert any(
        "long_run_growth_anchor unavailable" in statement
        for statement in result.assumptions
    )


def test_build_params_saas_falls_back_to_filing_terminal_anchor_when_market_anchor_is_stale() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.saas.terminal_stale_fallback"
    )
    result = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "risk_free_rate": 0.04,
            "beta": 1.2,
            "long_run_growth_anchor": 0.014,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
            "market_datums": {
                "long_run_growth_anchor": {
                    "value": 0.014,
                    "source": "fred",
                    "as_of": "2025-01-01T00:00:00Z",
                    "staleness": {"days": 416, "is_stale": True, "max_days": 5},
                }
            },
        },
    )

    assert result.params["terminal_growth"] == pytest.approx(0.04)
    assert any(
        statement.startswith("terminal_growth fallback to filing-first anchor")
        for statement in result.assumptions
    )
    assert any(
        "terminal_growth sourced from filing-first anchor" in statement
        or "terminal_growth clamped from" in statement
        for statement in result.assumptions
    )


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
    assert all(
        not statement.startswith("shares_outstanding sourced from market data")
        for statement in result.assumptions
    )


def test_build_params_falls_back_to_filing_shares_when_market_shares_is_stale() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.shares_stale_fallback"
    )
    result = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "shares_outstanding": 1200.0,
            "shares_outstanding_is_stale": True,
            "shares_outstanding_staleness_days": 9,
            "market_stale_max_days": 5,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    assert result.params["shares_outstanding"] == 1000.0
    shares_source = result.metadata.get("data_freshness", {}).get(
        "shares_outstanding_source"
    )
    assert shares_source == "filing_market_stale_fallback"
    assert any(
        statement.startswith("shares_outstanding fallback to filing (market stale")
        for statement in result.assumptions
    )


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
    assert result.params["rwa_intensity"] == 30.0 / 1200.0
    assert result.params["shares_outstanding"] == 10.0
    assert result.params["cost_of_equity_strategy"] == "capm"
    assert result.params["terminal_growth"] == 0.02
    assert result.params["monte_carlo_iterations"] == 300
    assert result.params["monte_carlo_seed"] == 42
    assert result.params["monte_carlo_sampler"] == "sobol"
    assert "terminal_growth defaulted to 2.00%" in result.assumptions


def test_build_params_bank_rorwa_outlier_uses_historical_median() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_bank_reports_with_latest_rwa_outlier(),
        context="test.financial_reports.bank.outlier",
    )
    result = build_params("bank", "BNK", canonical_reports)

    assert result.params["rwa_intensity"] == 25.0 / 1100.0
    assert (
        "rwa_intensity fallback to historical median RoRWA (latest RWA discontinuity)"
        in result.assumptions
    )


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
    assert result.params["monte_carlo_sampler"] == "sobol"


def test_build_params_reit_derives_ffo_multiple_from_market_price() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reit_reports(), context="test.financial_reports.reit.multiple"
    )
    result = build_params(
        "reit_ffo",
        "REIT",
        canonical_reports,
        market_snapshot={
            "current_price": 12.0,
            "shares_outstanding": 1000.0,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    assert result.params["ffo_multiple"] == pytest.approx(100.0)
    assert "ffo_multiple implied from market price and FFO/share" in result.assumptions
    assert "ffo_multiple" not in result.missing


def test_build_params_can_disable_monte_carlo_via_env(monkeypatch) -> None:
    monkeypatch.setenv("FUNDAMENTAL_MONTE_CARLO_ENABLED", "false")
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports"
    )
    result = build_params("saas", "EXM", canonical_reports)

    assert result.params["monte_carlo_iterations"] == 0
    assert "monte_carlo disabled by policy" in result.assumptions


def test_build_params_can_override_monte_carlo_sampler_from_snapshot() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.mc_sampler_override"
    )
    result = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={"monte_carlo_sampler": "lhs"},
    )

    assert result.params["monte_carlo_sampler"] == "lhs"
    assert any("sampler=lhs" in statement for statement in result.assumptions)


def test_build_params_raises_for_unsupported_model() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports"
    )

    with pytest.raises(ValueError, match="Unsupported model type for SEC XBRL builder"):
        build_params("unsupported_model", "EXM", canonical_reports)


def test_build_params_time_alignment_warns_when_market_data_is_stale() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.time_alignment"
    )
    result = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "as_of": "2026-06-30T00:00:00Z",
            "time_alignment_max_days": 180,
            "time_alignment_policy": "warn",
        },
    )

    assert any(
        "high-risk: market_data_as_of exceeds filing_period_end" in a
        for a in result.assumptions
    )
    freshness = result.metadata.get("data_freshness")
    assert isinstance(freshness, dict)
    time_alignment = freshness.get("time_alignment")
    assert isinstance(time_alignment, dict)
    assert time_alignment.get("status") == "high_risk"
    assert time_alignment.get("policy") == "warn"


def test_build_params_time_alignment_reject_policy_raises_error() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.time_alignment.reject"
    )

    with pytest.raises(ValueError, match="Time-alignment guard rejected valuation"):
        build_params(
            "saas",
            "EXM",
            canonical_reports,
            market_snapshot={
                "as_of": "2026-06-30T00:00:00Z",
                "time_alignment_max_days": 180,
                "time_alignment_policy": "reject",
            },
        )


def test_build_params_metadata_includes_market_datum_quality_contract() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.market_datum_contract"
    )
    result = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "provider": "yfinance",
            "as_of": "2026-02-23T00:00:00Z",
            "missing_fields": ["target_mean_price"],
            "quality_flags": ["risk_free_rate:defaulted"],
            "license_note": "test license",
            "market_datums": {
                "risk_free_rate": {
                    "value": 0.042,
                    "source": "policy_default",
                    "as_of": "2026-02-23T00:00:00Z",
                    "horizon": "long_term",
                    "source_detail": "policy:default",
                    "quality_flags": ["defaulted"],
                    "staleness": {"days": 0, "is_stale": False, "max_days": 5},
                    "fallback_reason": "provider_missing",
                    "license_note": "internal default",
                }
            },
        },
    )

    freshness = result.metadata.get("data_freshness")
    assert isinstance(freshness, dict)
    market_data = freshness.get("market_data")
    assert isinstance(market_data, dict)
    assert market_data.get("quality_flags") == ["risk_free_rate:defaulted"]
    assert market_data.get("license_note") == "test license"
    market_datums = market_data.get("market_datums")
    assert isinstance(market_datums, dict)
    risk_free = market_datums.get("risk_free_rate")
    assert isinstance(risk_free, dict)
    assert risk_free.get("source") == "policy_default"
    assert risk_free.get("horizon") == "long_term"
    assert risk_free.get("fallback_reason") == "provider_missing"
    parameter_source_summary = result.metadata.get("parameter_source_summary")
    assert isinstance(parameter_source_summary, dict)
    assert parameter_source_summary.get("market_data_anchor", {}).get("provider") == (
        "yfinance"
    )
