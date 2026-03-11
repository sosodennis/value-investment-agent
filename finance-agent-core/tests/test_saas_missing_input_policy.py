from __future__ import annotations

from src.agents.fundamental.core_valuation.domain.parameterization.model_builders.shared.missing_metrics_service import (
    apply_missing_metric_policy,
)
from src.agents.fundamental.core_valuation.domain.parameterization.orchestrator import (
    build_params,
)
from src.agents.fundamental.financial_statements.interface.contracts import (
    parse_financial_reports_model,
)


def _tf(value: float | str | None) -> dict[str, object]:
    return {
        "value": value,
        "provenance": {"type": "MANUAL", "description": "test"},
    }


def _raw_reports_with_non_critical_missing() -> list[dict[str, object]]:
    return [
        {
            "industry_type": "Industrial",
            "extension_type": "Industrial",
            "base": {
                "fiscal_year": _tf("2024"),
                "period_end_date": _tf("2024-12-31"),
                "shares_outstanding": _tf(1000.0),
                "total_revenue": _tf(1000.0),
                "operating_income": _tf(180.0),
                "income_tax_expense": _tf(None),
                "income_before_tax": _tf(150.0),
                "depreciation_and_amortization": _tf(40.0),
                "share_based_compensation": _tf(None),
                "current_assets": _tf(900.0),
                "current_liabilities": _tf(400.0),
                "cash_and_equivalents": _tf(300.0),
                "total_debt": _tf(200.0),
                "preferred_stock": _tf(10.0),
            },
            "extension": {"capex": _tf(None)},
        },
        {
            "industry_type": "Industrial",
            "extension_type": "Industrial",
            "base": {
                "fiscal_year": _tf("2023"),
                "period_end_date": _tf("2023-12-31"),
                "shares_outstanding": _tf(1000.0),
                "total_revenue": _tf(900.0),
                "operating_income": _tf(150.0),
                "income_tax_expense": _tf(28.0),
                "income_before_tax": _tf(130.0),
                "depreciation_and_amortization": _tf(35.0),
                "share_based_compensation": _tf(18.0),
                "current_assets": _tf(None),
                "current_liabilities": _tf(390.0),
                "cash_and_equivalents": _tf(250.0),
                "total_debt": _tf(210.0),
                "preferred_stock": _tf(10.0),
            },
            "extension": {"capex": _tf(45.0)},
        },
    ]


def test_apply_missing_metric_policy_splits_blocking_and_warn_only() -> None:
    decision = apply_missing_metric_policy(
        missing_fields=["growth_rates", "capex_rates", "wc_rates"],
        warn_only_fields=["capex_rates", "wc_rates"],
    )
    assert decision.blocking_fields == ["growth_rates"]
    assert decision.warn_only_fields == ["capex_rates", "wc_rates"]


def test_build_params_saas_defaults_non_critical_missing_metrics() -> None:
    reports = parse_financial_reports_model(
        _raw_reports_with_non_critical_missing(),
        context="test.saas_missing_input_policy",
        inject_default_provenance=True,
    )
    result = build_params(
        "dcf_growth",
        "AMZN",
        reports,
        market_snapshot=None,
    )

    assert "tax_rate" not in result.missing
    assert "capex_rates" not in result.missing
    assert "wc_rates" not in result.missing
    assert "sbc_rates" not in result.missing
    assert any("tax_rate defaulted" in statement for statement in result.assumptions)
    assert any("capex_rates defaulted" in statement for statement in result.assumptions)
    assert any("wc_rates defaulted" in statement for statement in result.assumptions)
    assert any("sbc_rates defaulted" in statement for statement in result.assumptions)
