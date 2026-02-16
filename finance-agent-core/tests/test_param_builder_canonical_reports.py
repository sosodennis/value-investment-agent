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


def test_build_params_accepts_canonicalized_financial_reports() -> None:
    raw_reports = [
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

    canonical_reports = parse_financial_reports_model(
        raw_reports, context="test.financial_reports"
    )
    result = build_params("saas", "EXM", canonical_reports)

    assert result.params["ticker"] == "EXM"
    assert not result.missing
