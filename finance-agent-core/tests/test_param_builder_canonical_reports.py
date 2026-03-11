from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.fundamental.domain.valuation.parameterization.orchestrator import (
    build_params,
)
from src.agents.fundamental.domain.valuation.parameterization.reinvestment_clamp_profile_service import (
    REINVESTMENT_CLAMP_PROFILE_PATH_ENV,
    clear_reinvestment_clamp_profile_cache,
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
                "interest_cost_rate": _tf(0.05),
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
                "interest_cost_rate": _tf(0.052),
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


def _raw_reports_high_growth() -> list[dict[str, object]]:
    reports = _raw_reports()
    reports[0]["base"]["total_revenue"] = _tf(1000.0)
    reports[1]["base"]["total_revenue"] = _tf(200.0)
    return reports


def _raw_reports_high_margin() -> list[dict[str, object]]:
    reports = _raw_reports()
    reports[0]["base"]["operating_income"] = _tf(650.0)
    return reports


def _raw_reports_reinvestment_outlier() -> list[dict[str, object]]:
    reports = _raw_reports()
    reports[0]["extension"]["capex"] = _tf(400.0)
    reports[0]["base"]["current_assets"] = _tf(1200.0)
    reports[0]["base"]["current_liabilities"] = _tf(400.0)
    return reports


def _raw_reports_mature_stable_growth() -> list[dict[str, object]]:
    reports = _raw_reports()
    reports.append(
        {
            "industry_type": "Industrial",
            "extension_type": "Industrial",
            "base": {
                "fiscal_year": _tf("2022"),
                "fiscal_period": _tf("FY"),
                "period_end_date": _tf("2022-12-31"),
                "company_name": _tf("Example Inc."),
                "cik": _tf("0000000001"),
                "sic_code": _tf("7372"),
                "shares_outstanding": _tf(1000.0),
                "total_revenue": _tf(810.0),
                "net_income": _tf(90.0),
                "income_tax_expense": _tf(24.0),
                "total_assets": _tf(1800.0),
                "total_liabilities": _tf(760.0),
                "total_equity": _tf(1040.0),
                "cash_and_equivalents": _tf(220.0),
                "operating_cash_flow": _tf(120.0),
                "operating_income": _tf(135.0),
                "income_before_tax": _tf(114.0),
                "depreciation_and_amortization": _tf(30.0),
                "share_based_compensation": _tf(16.0),
                "current_assets": _tf(810.0),
                "current_liabilities": _tf(370.0),
                "total_debt": _tf(220.0),
                "preferred_stock": _tf(10.0),
            },
            "extension": {"capex": _tf(40.0)},
        }
    )
    return reports


def _raw_reports_with_weighted_average_dilution(
    *,
    basic_shares: float,
    diluted_shares: float,
) -> list[dict[str, object]]:
    reports = _raw_reports()
    reports[0]["base"]["weighted_average_shares_basic"] = _tf(basic_shares)
    reports[0]["base"]["weighted_average_shares_diluted"] = _tf(diluted_shares)
    return reports


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
    growth_rates = result.params["growth_rates"]
    assert isinstance(growth_rates, list)
    assert len(growth_rates) == 10
    assert "model_variant=dcf_standard routed via dedicated param builder" in "; ".join(
        result.assumptions
    )


def test_build_params_dcf_growth_uses_dedicated_builder_variant() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.dcf_growth"
    )
    result = build_params("dcf_growth", "EXM", canonical_reports)

    assert result.params["model_variant"] == "dcf_growth"
    growth_rates = result.params["growth_rates"]
    assert isinstance(growth_rates, list)
    assert len(growth_rates) == 10
    assert "model_variant=dcf_growth routed via dedicated param builder" in "; ".join(
        result.assumptions
    )


def test_build_params_dcf_growth_harmonizes_market_class_shares_when_scope_mismatch() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.dcf_growth.scope_harmonize"
    )
    result = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "shares_outstanding": 500.0,
            "current_price": 77.5,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    shares_outstanding = result.params["shares_outstanding"]
    assert isinstance(shares_outstanding, float)
    assert shares_outstanding == pytest.approx(500.0)
    shares_source = result.metadata.get("data_freshness", {}).get(
        "shares_outstanding_source"
    )
    assert shares_source == "market_data_scope_harmonized"
    shares_path = result.metadata.get("data_freshness", {}).get("shares_path")
    assert isinstance(shares_path, dict)
    assert shares_path.get("scope_policy_mode") == "harmonize_when_mismatch"
    assert shares_path.get("scope_policy_resolution") == "harmonized_market_class"
    assert shares_path.get("shares_scope") == "market_class_harmonized"
    assert shares_path.get("scope_mismatch_resolved") is True
    assert any(
        statement.startswith(
            "dcf_shares_scope_policy harmonized denominator to market-class shares"
        )
        for statement in result.assumptions
    )


def test_build_params_dcf_growth_scope_policy_can_stay_conservative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FUNDAMENTAL_DCF_SHARES_SCOPE_POLICY", "conservative_only")
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.dcf_growth.scope_conservative"
    )
    result = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "shares_outstanding": 500.0,
            "current_price": 77.5,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    shares_outstanding = result.params["shares_outstanding"]
    assert isinstance(shares_outstanding, float)
    assert shares_outstanding == pytest.approx(1000.0)
    shares_source = result.metadata.get("data_freshness", {}).get(
        "shares_outstanding_source"
    )
    assert shares_source == "filing_conservative_dilution"
    shares_path = result.metadata.get("data_freshness", {}).get("shares_path")
    assert isinstance(shares_path, dict)
    assert shares_path.get("scope_policy_mode") == "conservative_only"
    assert shares_path.get("scope_policy_resolution") == "conservative_only"


def test_build_params_dcf_growth_applies_base_growth_guardrail() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports_high_growth(),
        context="test.financial_reports.dcf_growth.guardrail",
    )
    result = build_params("dcf_growth", "EXM", canonical_reports)

    growth_rates = result.params["growth_rates"]
    assert isinstance(growth_rates, list)
    assert growth_rates[0] <= 0.53
    assert growth_rates[-1] == pytest.approx(result.params["terminal_growth"])
    assert any(
        item.startswith("base_growth_guardrail applied") for item in result.assumptions
    )


def test_build_params_dcf_standard_applies_base_growth_guardrail_with_conservative_profile() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports_high_growth(),
        context="test.financial_reports.dcf_standard.no_guardrail",
    )
    result = build_params("dcf_standard", "EXM", canonical_reports)

    growth_rates = result.params["growth_rates"]
    assert isinstance(growth_rates, list)
    assert growth_rates[0] <= 0.48
    terminal_growth = result.params["terminal_growth"]
    assert isinstance(terminal_growth, float)
    assert terminal_growth >= 0.018
    assert any(
        item.startswith("base_growth_guardrail applied") for item in result.assumptions
    )
    assert any("profile=dcf_standard" in item for item in result.assumptions)


def test_build_params_dcf_growth_applies_base_margin_guardrail() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports_high_margin(), context="test.financial_reports.dcf_growth.margin"
    )
    result = build_params("dcf_growth", "EXM", canonical_reports)

    operating_margins = result.params["operating_margins"]
    assert isinstance(operating_margins, list)
    assert operating_margins[0] == pytest.approx(0.60)
    assert operating_margins[-1] <= 0.40 + 1e-9
    assert operating_margins[-1] >= 0.30 - 1e-9
    assert any(
        item.startswith("base_margin_guardrail applied") for item in result.assumptions
    )


def test_build_params_dcf_standard_applies_base_margin_guardrail_with_conservative_profile() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports_high_margin(),
        context="test.financial_reports.dcf_standard.margin.no_guardrail",
    )
    result = build_params("dcf_standard", "EXM", canonical_reports)

    operating_margins = result.params["operating_margins"]
    assert isinstance(operating_margins, list)
    assert operating_margins[-1] <= 0.38 + 1e-9
    assert any(
        item.startswith("base_margin_guardrail applied") for item in result.assumptions
    )
    assert any("profile=dcf_standard" in item for item in result.assumptions)


def test_build_params_dcf_growth_applies_reinvestment_guardrail() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports_reinvestment_outlier(),
        context="test.financial_reports.dcf_growth.reinvestment_guardrail",
    )
    result = build_params("dcf_growth", "EXM", canonical_reports)

    capex_rates = result.params["capex_rates"]
    wc_rates = result.params["wc_rates"]
    assert isinstance(capex_rates, list)
    assert isinstance(wc_rates, list)
    assert capex_rates[0] == pytest.approx(0.30)
    assert capex_rates[-1] == pytest.approx(0.11)
    assert wc_rates[0] == pytest.approx(0.13)
    assert wc_rates[-1] == pytest.approx(0.045)
    assert any(
        "base_reinvestment_guardrail applied" in item and "metric=capex_rates" in item
        for item in result.assumptions
    )
    assert any(
        "base_reinvestment_guardrail applied" in item and "metric=wc_rates" in item
        for item in result.assumptions
    )


def test_build_params_dcf_variants_emit_shared_guardrail_profile_version() -> None:
    dcf_growth_reports = parse_financial_reports_model(
        _raw_reports_reinvestment_outlier(),
        context="test.financial_reports.dcf_growth.shared_guardrail_profile_version",
    )
    dcf_standard_reports = parse_financial_reports_model(
        _raw_reports_mature_stable_growth(),
        context="test.financial_reports.dcf_standard.shared_guardrail_profile_version",
    )
    growth_result = build_params("dcf_growth", "EXM", dcf_growth_reports)
    standard_result = build_params("dcf_standard", "EXM", dcf_standard_reports)

    assert any(
        statement == "guardrail_profile_version=shared_base_v2;variant=dcf_growth"
        for statement in growth_result.assumptions
    )
    assert any(
        statement == "guardrail_profile_version=shared_base_v2;variant=dcf_standard"
        for statement in standard_result.assumptions
    )


def test_build_params_dcf_growth_relaxes_capex_terminal_upper_for_high_consensus_premium() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports_reinvestment_outlier(),
        context="test.financial_reports.dcf_growth.reinvestment_consensus_relaxation",
    )
    baseline = build_params("dcf_growth", "EXM", canonical_reports)
    relaxed = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 150.0,
            "target_consensus_applied": False,
            "target_consensus_source_count": 1,
            "target_consensus_fallback_reason": "provider_blocked",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    baseline_capex = baseline.params["capex_rates"]
    relaxed_capex = relaxed.params["capex_rates"]
    assert isinstance(baseline_capex, list)
    assert isinstance(relaxed_capex, list)
    assert relaxed_capex[-1] < baseline_capex[-1]
    assert any(
        statement.startswith("dcf_growth_capex_consensus_relaxation applied")
        for statement in relaxed.assumptions
    )


def test_build_params_dcf_growth_relaxes_wc_terminal_lower_for_high_consensus_premium() -> (
    None
):
    raw_reports = _raw_reports_mature_stable_growth()
    raw_reports[0]["base"]["current_assets"] = _tf(700.0)
    raw_reports[0]["base"]["current_liabilities"] = _tf(500.0)
    canonical_reports = parse_financial_reports_model(
        raw_reports,
        context="test.financial_reports.dcf_growth.wc_consensus_relaxation",
    )

    baseline = build_params("dcf_growth", "EXM", canonical_reports)
    relaxed = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 150.0,
            "target_consensus_applied": False,
            "target_consensus_source_count": 1,
            "target_consensus_fallback_reason": "provider_blocked",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    baseline_wc = baseline.params["wc_rates"]
    relaxed_wc = relaxed.params["wc_rates"]
    assert isinstance(baseline_wc, list)
    assert isinstance(relaxed_wc, list)
    assert relaxed_wc[-1] < baseline_wc[-1]
    assert any(
        statement.startswith("dcf_growth_wc_consensus_relaxation applied")
        for statement in relaxed.assumptions
    )


def test_build_params_dcf_growth_enforces_capex_low_premium_conservative_floor() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports_mature_stable_growth(),
        context="test.financial_reports.dcf_growth.capex_low_premium_floor",
    )
    baseline = build_params("dcf_growth", "EXM", canonical_reports)
    adjusted = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 120.0,
            "target_consensus_applied": True,
            "target_consensus_source_count": 3,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    baseline_capex = baseline.params["capex_rates"]
    adjusted_capex = adjusted.params["capex_rates"]
    assert isinstance(baseline_capex, list)
    assert isinstance(adjusted_capex, list)
    assert adjusted_capex[-1] > baseline_capex[-1]
    assert any(
        statement.startswith("dcf_growth_capex_low_premium_conservative_floor applied")
        for statement in adjusted.assumptions
    )


def test_build_params_dcf_growth_enforces_wc_low_premium_conservative_floor() -> None:
    raw_reports = _raw_reports_mature_stable_growth()
    raw_reports[0]["base"]["current_assets"] = _tf(700.0)
    raw_reports[0]["base"]["current_liabilities"] = _tf(500.0)
    canonical_reports = parse_financial_reports_model(
        raw_reports,
        context="test.financial_reports.dcf_growth.wc_low_premium_floor",
    )

    baseline = build_params("dcf_growth", "EXM", canonical_reports)
    adjusted = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 120.0,
            "target_consensus_applied": True,
            "target_consensus_source_count": 3,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    baseline_wc = baseline.params["wc_rates"]
    adjusted_wc = adjusted.params["wc_rates"]
    assert isinstance(baseline_wc, list)
    assert isinstance(adjusted_wc, list)
    assert adjusted_wc[-1] > baseline_wc[-1]
    assert adjusted_wc[-1] >= 0.0
    assert any(
        statement.startswith("dcf_growth_wc_low_premium_conservative_floor applied")
        for statement in adjusted.assumptions
    )


def test_build_params_dcf_growth_raises_capex_upper_for_low_premium_scope_mismatch() -> (
    None
):
    raw_reports = _raw_reports_mature_stable_growth()
    raw_reports[0]["extension"]["capex"] = _tf(220.0)
    raw_reports[1]["extension"]["capex"] = _tf(200.0)
    raw_reports[2]["extension"]["capex"] = _tf(180.0)
    canonical_reports = parse_financial_reports_model(
        raw_reports,
        context="test.financial_reports.dcf_growth.capex_low_premium_scope_mismatch_upper",
    )
    low_premium = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 120.0,
            "target_consensus_applied": True,
            "target_consensus_source_count": 3,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )
    mismatch = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 120.0,
            "shares_outstanding": 450.0,
            "target_consensus_applied": True,
            "target_consensus_source_count": 3,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    low_premium_capex = low_premium.params["capex_rates"]
    mismatch_capex = mismatch.params["capex_rates"]
    assert isinstance(low_premium_capex, list)
    assert isinstance(mismatch_capex, list)
    assert mismatch_capex[-1] > low_premium_capex[-1]
    assert mismatch_capex[-1] >= 0.12
    assert any(
        "dcf_growth_capex_shares_mismatch_conservative_floor applied" in statement
        for statement in mismatch.assumptions
    )


def test_build_params_dcf_growth_raises_wc_upper_for_low_premium_scope_mismatch() -> (
    None
):
    raw_reports = _raw_reports_mature_stable_growth()
    raw_reports[0]["base"]["current_assets"] = _tf(1100.0)
    raw_reports[0]["base"]["current_liabilities"] = _tf(300.0)
    raw_reports[1]["base"]["current_assets"] = _tf(900.0)
    raw_reports[1]["base"]["current_liabilities"] = _tf(300.0)
    raw_reports[2]["base"]["current_assets"] = _tf(700.0)
    raw_reports[2]["base"]["current_liabilities"] = _tf(300.0)
    canonical_reports = parse_financial_reports_model(
        raw_reports,
        context="test.financial_reports.dcf_growth.wc_low_premium_scope_mismatch_upper",
    )
    low_premium = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 120.0,
            "target_consensus_applied": True,
            "target_consensus_source_count": 3,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )
    mismatch = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 120.0,
            "shares_outstanding": 450.0,
            "target_consensus_applied": True,
            "target_consensus_source_count": 3,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    low_premium_wc = low_premium.params["wc_rates"]
    mismatch_wc = mismatch.params["wc_rates"]
    assert isinstance(low_premium_wc, list)
    assert isinstance(mismatch_wc, list)
    assert mismatch_wc[-1] > low_premium_wc[-1]
    assert mismatch_wc[-1] >= 0.02
    assert any(
        "dcf_growth_wc_shares_mismatch_conservative_floor applied" in statement
        for statement in mismatch.assumptions
    )


def test_build_params_dcf_growth_applies_severe_capex_floor_for_harmonized_mismatch() -> (
    None
):
    raw_reports = _raw_reports_mature_stable_growth()
    raw_reports[0]["extension"]["capex"] = _tf(220.0)
    raw_reports[1]["extension"]["capex"] = _tf(200.0)
    raw_reports[2]["extension"]["capex"] = _tf(180.0)
    canonical_reports = parse_financial_reports_model(
        raw_reports,
        context="test.financial_reports.dcf_growth.capex_harmonized_mismatch_severe_floor",
    )
    mismatch = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 120.0,
            "shares_outstanding": 450.0,
            "target_consensus_applied": True,
            "target_consensus_source_count": 3,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )
    severe = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 120.0,
            "shares_outstanding": 450.0,
            "target_consensus_applied": False,
            "target_consensus_source_count": 1,
            "target_consensus_fallback_reason": "provider_blocked",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    mismatch_capex = mismatch.params["capex_rates"]
    severe_capex = severe.params["capex_rates"]
    assert isinstance(mismatch_capex, list)
    assert isinstance(severe_capex, list)
    assert severe_capex[-1] > mismatch_capex[-1]
    assert severe_capex[-1] >= 0.14
    assert any(
        "dcf_growth_capex_harmonized_mismatch_severe_floor applied" in statement
        for statement in severe.assumptions
    )


def test_build_params_dcf_growth_applies_severe_wc_floor_for_harmonized_mismatch() -> (
    None
):
    raw_reports = _raw_reports_mature_stable_growth()
    raw_reports[0]["base"]["current_assets"] = _tf(1100.0)
    raw_reports[0]["base"]["current_liabilities"] = _tf(300.0)
    raw_reports[1]["base"]["current_assets"] = _tf(900.0)
    raw_reports[1]["base"]["current_liabilities"] = _tf(300.0)
    raw_reports[2]["base"]["current_assets"] = _tf(700.0)
    raw_reports[2]["base"]["current_liabilities"] = _tf(300.0)
    canonical_reports = parse_financial_reports_model(
        raw_reports,
        context="test.financial_reports.dcf_growth.wc_harmonized_mismatch_severe_floor",
    )
    mismatch = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 120.0,
            "shares_outstanding": 450.0,
            "target_consensus_applied": True,
            "target_consensus_source_count": 3,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )
    severe = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 120.0,
            "shares_outstanding": 450.0,
            "target_consensus_applied": False,
            "target_consensus_source_count": 1,
            "target_consensus_fallback_reason": "provider_blocked",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    mismatch_wc = mismatch.params["wc_rates"]
    severe_wc = severe.params["wc_rates"]
    assert isinstance(mismatch_wc, list)
    assert isinstance(severe_wc, list)
    assert severe_wc[-1] > mismatch_wc[-1]
    assert severe_wc[-1] >= 0.07
    assert any(
        "dcf_growth_wc_harmonized_mismatch_severe_floor applied" in statement
        for statement in severe.assumptions
    )


def test_build_params_dcf_growth_severe_floor_uses_profile_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile_path = tmp_path / "reinvestment_profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "schema_version": "fundamental_reinvestment_clamp_profile_v1",
                "profile_version": "reinvestment_clamp_profile_v1_test_override",
                "dcf_growth": {
                    "severe_scope_mismatch_ratio_threshold": 0.40,
                    "severe_mismatch_capex_terminal_lower_min": 0.20,
                    "severe_mismatch_capex_terminal_lower_year1_ratio": 0.50,
                    "severe_mismatch_wc_terminal_lower_min": 0.03,
                    "severe_mismatch_wc_terminal_lower_year1_ratio": 0.30,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(REINVESTMENT_CLAMP_PROFILE_PATH_ENV, str(profile_path))
    clear_reinvestment_clamp_profile_cache()

    raw_reports = _raw_reports_mature_stable_growth()
    raw_reports[0]["extension"]["capex"] = _tf(220.0)
    raw_reports[1]["extension"]["capex"] = _tf(200.0)
    raw_reports[2]["extension"]["capex"] = _tf(180.0)
    canonical_reports = parse_financial_reports_model(
        raw_reports,
        context="test.financial_reports.dcf_growth.capex_harmonized_mismatch_profile_override",
    )
    severe = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 120.0,
            "shares_outstanding": 450.0,
            "target_consensus_applied": False,
            "target_consensus_source_count": 1,
            "target_consensus_fallback_reason": "provider_blocked",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    severe_capex = severe.params["capex_rates"]
    assert isinstance(severe_capex, list)
    assert severe_capex[-1] >= 0.20
    assert any(
        "profile_version=reinvestment_clamp_profile_v1_test_override" in statement
        for statement in severe.assumptions
    )
    clear_reinvestment_clamp_profile_cache()


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


def test_build_params_emits_forward_signal_trace_without_signal_payload() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.dcf_growth.forward_signal_empty"
    )
    result = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={"consensus_growth_rate": 0.25},
    )

    forward_signal = result.metadata.get("forward_signal")
    assert isinstance(forward_signal, dict)
    assert forward_signal["signals_total"] == 0
    assert forward_signal["calibration_applied"] is False
    mapping_version = forward_signal.get("mapping_version")
    assert isinstance(mapping_version, str)
    assert mapping_version
    assert forward_signal["raw_growth_adjustment_basis_points"] == pytest.approx(0.0)
    assert forward_signal["growth_adjustment_basis_points"] == pytest.approx(0.0)


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
    assert any(
        statement.startswith(
            "historical_growth_anchor blended from clipped YoY windows"
        )
        for statement in result.assumptions
    )
    assert result.params["monte_carlo_iterations"] == 1000
    assert result.params["monte_carlo_seed"] == 42
    assert result.params["monte_carlo_sampler"] == "sobol"


def test_build_params_saas_applies_short_term_consensus_decay_for_growth_blend() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports(),
        context="test.financial_reports.saas.short_term_consensus_ignored",
    )
    baseline = build_params("saas", "EXM", canonical_reports, market_snapshot=None)
    short_term = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "consensus_growth_rate": 0.50,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
            "market_datums": {
                "consensus_growth_rate": {
                    "value": 0.50,
                    "source": "yfinance",
                    "horizon": "short_term",
                }
            },
        },
    )

    baseline_growth = baseline.params["growth_rates"]
    short_term_growth = short_term.params["growth_rates"]
    assert isinstance(baseline_growth, list)
    assert isinstance(short_term_growth, list)
    assert short_term_growth[0] > baseline_growth[0]
    assert short_term_growth[1] > baseline_growth[1]
    assert short_term_growth[2] > baseline_growth[2]
    assert short_term_growth[-1] == pytest.approx(baseline_growth[-1])
    assert any(
        "consensus_growth_rate decayed into near-term DCF growth path (horizon=short_term, window_years=3"
        in statement
        for statement in short_term.assumptions
    )


def test_build_params_dcf_standard_extends_short_term_consensus_decay_for_mature_profile() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports_mature_stable_growth(),
        context="test.financial_reports.dcf_standard.short_term_consensus_decay_window",
    )
    short_term = build_params(
        "dcf_standard",
        "EXM",
        canonical_reports,
        market_snapshot={
            "consensus_growth_rate": 0.50,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
            "market_datums": {
                "consensus_growth_rate": {
                    "value": 0.50,
                    "source": "yfinance",
                    "horizon": "short_term",
                }
            },
        },
    )

    assert any(
        "consensus_growth_rate decayed into near-term DCF growth path (horizon=short_term, window_years=8"
        in statement
        for statement in short_term.assumptions
    )


def test_build_params_dcf_standard_applies_consensus_terminal_nudge() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports_mature_stable_growth(),
        context="test.financial_reports.dcf_standard.consensus_terminal_nudge",
    )
    baseline = build_params(
        "dcf_standard",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 100.0,
            "long_run_growth_anchor": 0.014,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )
    nudged = build_params(
        "dcf_standard",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 130.0,
            "long_run_growth_anchor": 0.014,
            "target_consensus_applied": False,
            "target_consensus_source_count": 1,
            "target_consensus_fallback_reason": "provider_blocked",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    baseline_terminal = baseline.params["terminal_growth"]
    nudged_terminal = nudged.params["terminal_growth"]
    assert isinstance(baseline_terminal, float)
    assert isinstance(nudged_terminal, float)
    assert nudged_terminal > baseline_terminal
    assert any(
        statement.startswith("terminal_growth_consensus_nudge applied")
        for statement in nudged.assumptions
    )


def test_build_params_dcf_standard_downweights_single_source_consensus_nudge() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports_mature_stable_growth(),
        context="test.financial_reports.dcf_standard.consensus_terminal_nudge.downweighted_single_source",
    )
    multi_source = build_params(
        "dcf_standard",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 130.0,
            "long_run_growth_anchor": 0.014,
            "target_consensus_applied": True,
            "target_consensus_source_count": 3,
            "target_consensus_quality_bucket": "high",
            "target_consensus_confidence_weight": 1.0,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )
    single_source = build_params(
        "dcf_standard",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 130.0,
            "long_run_growth_anchor": 0.014,
            "target_consensus_applied": False,
            "target_consensus_source_count": 1,
            "target_consensus_fallback_reason": "provider_blocked",
            "target_consensus_quality_bucket": "degraded",
            "target_consensus_confidence_weight": 0.30,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    multi_terminal = multi_source.params["terminal_growth"]
    single_terminal = single_source.params["terminal_growth"]
    assert isinstance(multi_terminal, float)
    assert isinstance(single_terminal, float)
    assert multi_terminal > single_terminal
    assert any(
        "quality_bucket=degraded" in statement
        for statement in single_source.assumptions
    )


def test_build_params_dcf_standard_can_disable_consensus_terminal_nudge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FUNDAMENTAL_DCF_STANDARD_CONSENSUS_TERMINAL_NUDGE_ENABLED", "0")
    canonical_reports = parse_financial_reports_model(
        _raw_reports_mature_stable_growth(),
        context="test.financial_reports.dcf_standard.consensus_terminal_nudge_disabled",
    )
    result = build_params(
        "dcf_standard",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 130.0,
            "long_run_growth_anchor": 0.014,
            "target_consensus_applied": False,
            "target_consensus_source_count": 1,
            "target_consensus_fallback_reason": "provider_blocked",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    terminal_growth = result.params["terminal_growth"]
    assert isinstance(terminal_growth, float)
    assert terminal_growth == pytest.approx(0.035)
    assert not any(
        statement.startswith("terminal_growth_consensus_nudge applied")
        for statement in result.assumptions
    )


def test_build_params_dcf_standard_relaxes_growth_guardrail_for_high_consensus_premium() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports_high_growth(),
        context="test.financial_reports.dcf_standard.growth_consensus_relaxation",
    )
    baseline = build_params(
        "dcf_standard",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 100.0,
            "target_consensus_applied": True,
            "target_consensus_source_count": 3,
            "target_consensus_quality_bucket": "high",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )
    relaxed = build_params(
        "dcf_standard",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 150.0,
            "target_consensus_applied": True,
            "target_consensus_source_count": 3,
            "target_consensus_quality_bucket": "high",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    baseline_growth = baseline.params["growth_rates"]
    relaxed_growth = relaxed.params["growth_rates"]
    assert isinstance(baseline_growth, list)
    assert isinstance(relaxed_growth, list)
    assert relaxed_growth[0] > baseline_growth[0]
    assert any(
        statement.startswith("dcf_standard_growth_consensus_relaxation applied")
        for statement in relaxed.assumptions
    )


def test_build_params_dcf_standard_relaxes_margin_guardrail_for_high_consensus_premium() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports_high_margin(),
        context="test.financial_reports.dcf_standard.margin_consensus_relaxation",
    )
    baseline = build_params(
        "dcf_standard",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 100.0,
            "target_consensus_applied": True,
            "target_consensus_source_count": 3,
            "target_consensus_quality_bucket": "high",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )
    relaxed = build_params(
        "dcf_standard",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 150.0,
            "target_consensus_applied": True,
            "target_consensus_source_count": 3,
            "target_consensus_quality_bucket": "high",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    baseline_margins = baseline.params["operating_margins"]
    relaxed_margins = relaxed.params["operating_margins"]
    assert isinstance(baseline_margins, list)
    assert isinstance(relaxed_margins, list)
    assert relaxed_margins[-1] > baseline_margins[-1]
    assert any(
        statement.startswith("dcf_standard_margin_consensus_relaxation applied")
        for statement in relaxed.assumptions
    )


def test_build_params_dcf_standard_relaxes_reinvestment_guardrail_for_high_consensus_premium() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports_reinvestment_outlier(),
        context="test.financial_reports.dcf_standard.reinvestment_consensus_relaxation",
    )
    baseline = build_params(
        "dcf_standard",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 100.0,
            "target_consensus_applied": True,
            "target_consensus_source_count": 3,
            "target_consensus_quality_bucket": "high",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )
    relaxed = build_params(
        "dcf_standard",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 150.0,
            "target_consensus_applied": True,
            "target_consensus_source_count": 3,
            "target_consensus_quality_bucket": "high",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    baseline_capex = baseline.params["capex_rates"]
    relaxed_capex = relaxed.params["capex_rates"]
    baseline_wc = baseline.params["wc_rates"]
    relaxed_wc = relaxed.params["wc_rates"]
    assert isinstance(baseline_capex, list)
    assert isinstance(relaxed_capex, list)
    assert isinstance(baseline_wc, list)
    assert isinstance(relaxed_wc, list)
    assert relaxed_capex[-1] < baseline_capex[-1]
    assert relaxed_wc[-1] <= baseline_wc[-1]
    assert any(
        statement.startswith("dcf_standard_capex_consensus_relaxation applied")
        for statement in relaxed.assumptions
    )
    assert any(
        statement.startswith("dcf_standard_wc_consensus_relaxation applied")
        for statement in relaxed.assumptions
    )


def test_build_params_dcf_growth_does_not_apply_consensus_terminal_nudge() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports_mature_stable_growth(),
        context="test.financial_reports.dcf_growth.consensus_terminal_nudge_disabled",
    )
    result = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 140.0,
            "long_run_growth_anchor": 0.014,
            "target_consensus_applied": True,
            "target_consensus_source_count": 3,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    assert not any(
        statement.startswith("terminal_growth_consensus_nudge applied")
        for statement in result.assumptions
    )


def test_build_params_dcf_growth_applies_terminal_consensus_nudge_for_high_premium() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports_mature_stable_growth(),
        context="test.financial_reports.dcf_growth.terminal_consensus_nudge",
    )
    baseline = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 100.0,
            "long_run_growth_anchor": 0.014,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )
    nudged = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 150.0,
            "long_run_growth_anchor": 0.014,
            "target_consensus_applied": False,
            "target_consensus_source_count": 1,
            "target_consensus_fallback_reason": "provider_blocked",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    baseline_terminal = baseline.params["terminal_growth"]
    nudged_terminal = nudged.params["terminal_growth"]
    assert isinstance(baseline_terminal, float)
    assert isinstance(nudged_terminal, float)
    assert nudged_terminal > baseline_terminal
    assert any(
        statement.startswith("dcf_growth_terminal_consensus_nudge applied")
        for statement in nudged.assumptions
    )


def test_build_params_dcf_growth_uses_higher_terminal_cap_for_degraded_high_premium() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports_mature_stable_growth(),
        context="test.financial_reports.dcf_growth.terminal_consensus_nudge.degraded_high_premium_cap",
    )
    result = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 150.0,
            "long_run_growth_anchor": 0.034,
            "target_consensus_applied": False,
            "target_consensus_source_count": 1,
            "target_consensus_fallback_reason": "provider_blocked",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    terminal_growth = result.params["terminal_growth"]
    assert isinstance(terminal_growth, float)
    assert terminal_growth > 0.035
    assert terminal_growth <= 0.04
    assert any(
        statement.startswith("dcf_growth_terminal_consensus_nudge applied")
        and "max_terminal_cap=0.0400" in statement
        for statement in result.assumptions
    )


def test_build_params_dcf_growth_skips_terminal_nudge_when_scope_mismatch_detected() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports_mature_stable_growth(),
        context="test.financial_reports.dcf_growth.terminal_consensus_nudge.scope_mismatch",
    )
    result = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 150.0,
            "long_run_growth_anchor": 0.014,
            "shares_outstanding": 450.0,
            "target_consensus_applied": False,
            "target_consensus_source_count": 1,
            "target_consensus_fallback_reason": "provider_blocked",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    terminal_growth = result.params["terminal_growth"]
    assert isinstance(terminal_growth, float)
    assert terminal_growth == pytest.approx(0.014)
    assert any(
        statement.startswith("dcf_growth_terminal_consensus_nudge skipped")
        for statement in result.assumptions
    )


def test_build_params_dcf_growth_skips_terminal_nudge_for_high_growth_profile() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports_high_growth(),
        context="test.financial_reports.dcf_growth.terminal_consensus_nudge.high_growth",
    )
    result = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 150.0,
            "long_run_growth_anchor": 0.014,
            "target_consensus_applied": False,
            "target_consensus_source_count": 1,
            "target_consensus_fallback_reason": "provider_blocked",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    terminal_growth = result.params["terminal_growth"]
    assert isinstance(terminal_growth, float)
    assert terminal_growth == pytest.approx(0.014)
    assert any(
        statement.startswith("dcf_growth_terminal_consensus_nudge skipped")
        and "year1_growth=" in statement
        for statement in result.assumptions
    )


def test_build_params_dcf_growth_caps_terminal_for_degraded_low_premium_path() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports_mature_stable_growth(),
        context="test.financial_reports.dcf_growth.degraded_low_premium_terminal_cap",
    )
    high_premium = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 150.0,
            "long_run_growth_anchor": 0.03,
            "target_consensus_applied": False,
            "target_consensus_source_count": 1,
            "target_consensus_fallback_reason": "provider_blocked",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )
    low_premium = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 120.0,
            "long_run_growth_anchor": 0.03,
            "target_consensus_applied": False,
            "target_consensus_source_count": 1,
            "target_consensus_fallback_reason": "provider_blocked",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    high_terminal = high_premium.params["terminal_growth"]
    low_terminal = low_premium.params["terminal_growth"]
    assert isinstance(high_terminal, float)
    assert isinstance(low_terminal, float)
    assert high_terminal > low_terminal
    assert low_terminal == pytest.approx(0.02)
    assert any(
        statement.startswith("dcf_growth_degraded_low_premium_terminal_cap applied")
        for statement in low_premium.assumptions
    )


def test_build_params_dcf_growth_relaxes_margin_upper_for_high_consensus_premium() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports_high_margin(),
        context="test.financial_reports.dcf_growth.margin_consensus_relaxation",
    )
    baseline = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 100.0,
            "long_run_growth_anchor": 0.014,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )
    relaxed = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 150.0,
            "long_run_growth_anchor": 0.014,
            "target_consensus_applied": False,
            "target_consensus_source_count": 1,
            "target_consensus_fallback_reason": "provider_blocked",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    baseline_margins = baseline.params["operating_margins"]
    relaxed_margins = relaxed.params["operating_margins"]
    assert isinstance(baseline_margins, list)
    assert isinstance(relaxed_margins, list)
    assert relaxed_margins[-1] > baseline_margins[-1]
    assert any(
        statement.startswith("dcf_growth_margin_consensus_relaxation applied")
        for statement in relaxed.assumptions
    )


def test_build_params_dcf_growth_applies_degraded_high_premium_margin_floor() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports_high_margin(),
        context="test.financial_reports.dcf_growth.margin_degraded_high_premium_floor",
    )
    low_premium = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 130.0,
            "long_run_growth_anchor": 0.014,
            "target_consensus_applied": False,
            "target_consensus_source_count": 1,
            "target_consensus_fallback_reason": "provider_blocked",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )
    high_premium = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 141.0,
            "long_run_growth_anchor": 0.014,
            "target_consensus_applied": False,
            "target_consensus_source_count": 1,
            "target_consensus_fallback_reason": "provider_blocked",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    low_margins = low_premium.params["operating_margins"]
    high_margins = high_premium.params["operating_margins"]
    assert isinstance(low_margins, list)
    assert isinstance(high_margins, list)
    assert high_margins[-1] > low_margins[-1]
    assert high_margins[-1] >= 0.44
    assert any(
        "dcf_growth_margin_degraded_high_premium_floor applied" in statement
        for statement in high_premium.assumptions
    )


def test_build_params_dcf_growth_skips_margin_relaxation_for_high_growth_profile() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports_high_growth(),
        context="test.financial_reports.dcf_growth.margin_consensus_relaxation.high_growth",
    )
    result = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 150.0,
            "long_run_growth_anchor": 0.014,
            "target_consensus_applied": False,
            "target_consensus_source_count": 1,
            "target_consensus_fallback_reason": "provider_blocked",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    assert any(
        statement.startswith("dcf_growth_margin_consensus_relaxation skipped")
        and "year1_growth=" in statement
        for statement in result.assumptions
    )


def test_build_params_dcf_growth_applies_degraded_high_premium_capex_cap() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports_reinvestment_outlier(),
        context="test.financial_reports.dcf_growth.capex_degraded_high_premium_cap",
    )
    low_premium = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 130.0,
            "long_run_growth_anchor": 0.014,
            "target_consensus_applied": False,
            "target_consensus_source_count": 1,
            "target_consensus_fallback_reason": "provider_blocked",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )
    high_premium = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 141.0,
            "long_run_growth_anchor": 0.014,
            "target_consensus_applied": False,
            "target_consensus_source_count": 1,
            "target_consensus_fallback_reason": "provider_blocked",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    low_capex_rates = low_premium.params["capex_rates"]
    high_capex_rates = high_premium.params["capex_rates"]
    assert isinstance(low_capex_rates, list)
    assert isinstance(high_capex_rates, list)
    assert high_capex_rates[-1] <= 0.09
    assert high_capex_rates[-1] < low_capex_rates[-1]
    assert any(
        "dcf_growth_capex_degraded_high_premium_cap applied" in statement
        for statement in high_premium.assumptions
    )


def test_build_params_saas_allows_long_term_consensus_for_growth_blend() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports(),
        context="test.financial_reports.saas.long_term_consensus_allowed",
    )
    baseline = build_params("saas", "EXM", canonical_reports, market_snapshot=None)
    long_term = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "consensus_growth_rate": 0.50,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
            "market_datums": {
                "consensus_growth_rate": {
                    "value": 0.50,
                    "source": "synthetic_consensus",
                    "horizon": "long_term",
                }
            },
        },
    )

    baseline_growth = baseline.params["growth_rates"]
    long_term_growth = long_term.params["growth_rates"]
    assert isinstance(baseline_growth, list)
    assert isinstance(long_term_growth, list)
    assert long_term_growth[0] > baseline_growth[0]
    assert long_term_growth[0] > long_term_growth[-1]
    assert any(
        "consensus_growth_rate included in long-horizon DCF growth blend (horizon=long_term)"
        in statement
        for statement in long_term.assumptions
    )


def test_build_params_saas_damps_short_term_decay_for_degraded_low_premium() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports(),
        context="test.financial_reports.saas.short_term_decay.degraded_low_premium",
    )
    high_premium = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 150.0,
            "consensus_growth_rate": 0.50,
            "target_consensus_applied": False,
            "target_consensus_source_count": 1,
            "target_consensus_fallback_reason": "provider_blocked",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
            "market_datums": {
                "consensus_growth_rate": {
                    "value": 0.50,
                    "source": "synthetic_consensus",
                    "horizon": "short_term",
                }
            },
        },
    )
    low_premium = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "current_price": 100.0,
            "target_mean_price": 120.0,
            "consensus_growth_rate": 0.50,
            "target_consensus_applied": False,
            "target_consensus_source_count": 1,
            "target_consensus_fallback_reason": "provider_blocked",
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
            "market_datums": {
                "consensus_growth_rate": {
                    "value": 0.50,
                    "source": "synthetic_consensus",
                    "horizon": "short_term",
                }
            },
        },
    )

    high_growth = high_premium.params["growth_rates"]
    low_growth = low_premium.params["growth_rates"]
    assert isinstance(high_growth, list)
    assert isinstance(low_growth, list)
    assert low_growth[0] < high_growth[0]
    assert any(
        statement.startswith(
            "consensus_growth_rate decay amplitude damped for low-premium degraded consensus"
        )
        for statement in low_premium.assumptions
    )


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
            "current_price": 50.0,
            "consensus_growth_rate": 0.15,
            "long_run_growth_anchor": 0.03,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    assert result.params["risk_free_rate"] == 0.04
    assert result.params["beta"] == 1.2
    assert result.params["market_risk_premium"] == 0.045
    assert result.params["wacc"] == pytest.approx(0.09378486055776892)
    assert result.params["terminal_growth"] == pytest.approx(0.03)
    assert any(
        statement.startswith("wacc sourced from FCFF-WACC")
        for statement in result.assumptions
    )
    assert "terminal_growth sourced from long_run_growth_anchor" in result.assumptions


def test_build_params_saas_converts_real_growth_anchor_to_nominal() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.saas.real_to_nominal"
    )
    result = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "risk_free_rate": 0.04,
            "beta": 1.2,
            "current_price": 50.0,
            "long_run_growth_anchor": 0.014,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
            "market_datums": {
                "long_run_growth_anchor": {
                    "value": 0.014,
                    "source": "fred",
                    "source_detail": "fred:A191RL1Q225SBEA",
                }
            },
        },
    )

    expected_nominal = (1.0 + 0.014) * (1.0 + 0.02) - 1.0
    assert result.params["terminal_growth"] == pytest.approx(expected_nominal)
    assert any(
        statement.startswith(
            "terminal_growth market anchor converted from real to nominal"
        )
        for statement in result.assumptions
    )


def test_build_params_saas_fallbacks_to_capm_wacc_when_fcff_weights_unavailable() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.saas.market_wacc.fallback"
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

    assert result.params["wacc"] == pytest.approx(0.094)
    assert any(
        "wacc fallback to CAPM cost_of_equity (fcff_wacc_missing_equity_market_value)"
        in statement
        for statement in result.assumptions
    )


def test_build_params_saas_ignores_market_risk_premium_from_snapshot_by_policy() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.saas.market_risk_premium.source"
    )
    result = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "risk_free_rate": 0.04,
            "beta": 1.2,
            "market_risk_premium": 0.06,
            "consensus_growth_rate": 0.15,
            "long_run_growth_anchor": 0.03,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    assert result.params["market_risk_premium"] == 0.045
    assert result.params["wacc"] == pytest.approx(0.094)
    assert (
        "market_risk_premium from market snapshot ignored by policy "
        "(market-level source only)"
    ) in result.assumptions


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

    assert result.params["wacc"] == pytest.approx(0.0525)
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
    assert result.params["wacc"] == pytest.approx(0.121)
    assert any(
        "beta clamped from 2.400 to 1.800" in statement
        for statement in result.assumptions
    )


def test_build_params_saas_applies_beta_mean_reversion_for_positive_premium() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.saas.beta_mean_reversion"
    )
    result = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "risk_free_rate": 0.04,
            "beta": 1.20,
            "current_price": 100.0,
            "target_mean_price": 130.0,
            "long_run_growth_anchor": 0.03,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    assert result.params["beta"] == pytest.approx(1.134)
    assert any(
        "beta mean-reversion applied" in statement for statement in result.assumptions
    )


def test_build_params_saas_skips_beta_mean_reversion_for_degraded_low_premium() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports(),
        context="test.financial_reports.saas.beta_mean_reversion.degraded_low_premium",
    )
    result = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "risk_free_rate": 0.04,
            "beta": 1.20,
            "current_price": 100.0,
            "target_mean_price": 120.0,
            "target_consensus_fallback_reason": "provider_blocked",
            "long_run_growth_anchor": 0.03,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    assert result.params["beta"] == pytest.approx(1.2)
    assert any(
        "beta mean-reversion skipped (degraded_low_premium_consensus" in statement
        for statement in result.assumptions
    )


def test_build_params_saas_skips_beta_mean_reversion_for_shares_scope_mismatch() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports(),
        context="test.financial_reports.saas.beta_mean_reversion.scope_mismatch",
    )
    result = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "risk_free_rate": 0.04,
            "beta": 1.20,
            "current_price": 100.0,
            "target_mean_price": 150.0,
            "shares_outstanding": 500.0,
            "long_run_growth_anchor": 0.03,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    assert result.params["beta"] == pytest.approx(1.2)
    assert any(
        "beta mean-reversion skipped (shares_scope_mismatch_ratio=" in statement
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


def test_build_params_saas_falls_back_to_policy_default_when_market_anchor_is_stale() -> (
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

    assert result.params["terminal_growth"] == pytest.approx(0.02)
    assert any(
        statement.startswith(
            "terminal_growth market anchor stale; fallback to policy default"
        )
        for statement in result.assumptions
    )
    assert any(
        statement.startswith(
            "terminal_growth market anchor stale; filing growth anchor captured for diagnostics only"
        )
        for statement in result.assumptions
    )


def test_build_params_saas_uses_filing_anchor_when_stale_mode_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "FUNDAMENTAL_TERMINAL_GROWTH_STALE_FALLBACK_MODE",
        "filing_first_then_default",
    )
    canonical_reports = parse_financial_reports_model(
        _raw_reports(),
        context="test.financial_reports.saas.terminal_stale_filing_first",
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
        statement == "terminal_growth stale fallback mode=filing_first_then_default"
        for statement in result.assumptions
    )
    assert any(
        statement.startswith(
            "terminal_growth market anchor stale; filing growth anchor selected as terminal anchor"
        )
        for statement in result.assumptions
    )
    assert any(
        statement.startswith("terminal_growth clamped from")
        for statement in result.assumptions
    )
    assert all(
        not statement.startswith(
            "terminal_growth market anchor stale; fallback to policy default"
        )
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


def test_build_params_saas_uses_conservative_shares_denominator_when_market_lower() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.shares.conservative_policy"
    )
    result = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "shares_outstanding": 900.0,
            "current_price": 77.5,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    assert result.params["shares_outstanding"] == 1000.0
    shares_source = result.metadata.get("data_freshness", {}).get(
        "shares_outstanding_source"
    )
    assert shares_source == "filing_conservative_dilution"
    assert any(
        statement.startswith(
            "shares_outstanding conservative denominator policy selected filing shares"
        )
        for statement in result.assumptions
    )


def test_build_params_saas_marks_scope_mismatch_when_filing_and_market_shares_diverge() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.shares.scope_mismatch"
    )
    result = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "shares_outstanding": 500.0,
            "current_price": 77.5,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    shares_path = result.metadata.get("data_freshness", {}).get("shares_path")
    assert isinstance(shares_path, dict)
    assert shares_path.get("shares_scope") == "filing_consolidated"
    assert shares_path.get("equity_value_scope") == "mixed_price_filing_shares"
    assert shares_path.get("scope_mismatch_detected") is True
    ratio = shares_path.get("scope_mismatch_ratio")
    assert isinstance(ratio, float)
    assert ratio == pytest.approx(0.5)
    assert any(
        statement.startswith("shares_scope mismatch detected")
        for statement in result.assumptions
    )


def test_build_params_saas_applies_s3_lite_dilution_proxy_to_denominator() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports_with_weighted_average_dilution(
            basic_shares=1000.0,
            diluted_shares=1100.0,
        ),
        context="test.financial_reports.shares.s3_lite_proxy_applied",
    )
    result = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "shares_outstanding": 900.0,
            "current_price": 77.5,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    assert result.params["shares_outstanding"] == pytest.approx(1100.0)
    shares_source = result.metadata.get("data_freshness", {}).get(
        "shares_outstanding_source"
    )
    assert shares_source == "filing_conservative_dilution_dilution_proxy"
    shares_summary = result.metadata.get("parameter_source_summary", {}).get(
        "shares_outstanding",
        {},
    )
    assert shares_summary.get("dilution_proxy_applied") is True
    assert any(
        statement.startswith("shares_outstanding adjusted by s3_lite dilution proxy")
        for statement in result.assumptions
    )


def test_build_params_saas_s3_lite_proxy_fallback_when_weighted_average_shares_missing() -> (
    None
):
    canonical_reports = parse_financial_reports_model(
        _raw_reports(), context="test.financial_reports.shares.s3_lite_proxy_fallback"
    )
    result = build_params(
        "saas",
        "EXM",
        canonical_reports,
        market_snapshot={
            "shares_outstanding": 900.0,
            "current_price": 77.5,
            "provider": "test_feed",
            "as_of": "2026-02-20T00:00:00Z",
        },
    )

    assert result.params["shares_outstanding"] == pytest.approx(1000.0)
    shares_source = result.metadata.get("data_freshness", {}).get(
        "shares_outstanding_source"
    )
    assert shares_source == "filing_conservative_dilution"
    assert any(
        statement
        == "s3_lite dilution proxy fallback: weighted-average basic shares unavailable"
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
    assert result.params["market_risk_premium"] == 0.045
    assert result.params["rwa_intensity"] == 30.0 / 1200.0
    assert result.params["shares_outstanding"] == 10.0
    assert result.params["cost_of_equity_strategy"] == "capm"
    assert result.params["terminal_growth"] == 0.02
    assert result.params["monte_carlo_iterations"] == 1000
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
    assert result.params["monte_carlo_iterations"] == 1000
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


def test_build_params_metadata_includes_terminal_growth_path_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "FUNDAMENTAL_TERMINAL_GROWTH_STALE_FALLBACK_MODE",
        "filing_first_then_default",
    )
    canonical_reports = parse_financial_reports_model(
        _raw_reports_mature_stable_growth(),
        context="test.financial_reports.terminal_growth_path_metadata",
    )
    result = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "provider": "yfinance",
            "as_of": "2026-03-08T00:00:00Z",
            "long_run_growth_anchor": 0.02,
            "market_datums": {
                "long_run_growth_anchor": {
                    "value": 0.02,
                    "source": "fred",
                    "as_of": "2025-10-31T00:00:00Z",
                    "staleness": {"days": 128, "is_stale": True, "max_days": 90},
                }
            },
        },
    )

    freshness = result.metadata.get("data_freshness")
    assert isinstance(freshness, dict)
    terminal_growth_path = freshness.get("terminal_growth_path")
    assert isinstance(terminal_growth_path, dict)
    assert (
        terminal_growth_path.get("terminal_growth_fallback_mode")
        == "filing_first_then_default"
    )
    assert terminal_growth_path.get("terminal_growth_anchor_source") == "filing"
    staleness = terminal_growth_path.get("long_run_growth_anchor_staleness")
    assert isinstance(staleness, dict)
    assert staleness.get("is_stale") is True
    assert staleness.get("days") == 128
    assert staleness.get("max_days") == 90

    parameter_source_summary = result.metadata.get("parameter_source_summary")
    assert isinstance(parameter_source_summary, dict)
    parameter_path = parameter_source_summary.get("terminal_growth_path")
    assert isinstance(parameter_path, dict)
    assert parameter_path.get("terminal_growth_anchor_source") == "filing"


def test_build_params_metadata_includes_nominal_bridge_summary() -> None:
    canonical_reports = parse_financial_reports_model(
        _raw_reports_mature_stable_growth(),
        context="test.financial_reports.terminal_growth_nominal_bridge_metadata",
    )
    result = build_params(
        "dcf_growth",
        "EXM",
        canonical_reports,
        market_snapshot={
            "provider": "yfinance",
            "as_of": "2026-03-08T00:00:00Z",
            "long_run_growth_anchor": 0.014,
            "market_datums": {
                "long_run_growth_anchor": {
                    "value": 0.014,
                    "source": "fred",
                    "source_detail": "fred:A191RL1Q225SBEA",
                    "staleness": {"days": 3, "is_stale": False, "max_days": 90},
                }
            },
        },
    )

    freshness = result.metadata.get("data_freshness")
    assert isinstance(freshness, dict)
    terminal_growth_path = freshness.get("terminal_growth_path")
    assert isinstance(terminal_growth_path, dict)
    assert (
        terminal_growth_path.get("long_run_growth_anchor_market_basis")
        == "real_to_nominal_bridge"
    )
    assert terminal_growth_path.get(
        "long_run_growth_anchor_market_raw"
    ) == pytest.approx(0.014)
    assert terminal_growth_path.get(
        "long_run_growth_nominal_bridge_inflation"
    ) == pytest.approx(0.02)
    assert terminal_growth_path.get("long_run_growth_anchor_source_detail") == (
        "fred:A191RL1Q225SBEA"
    )
