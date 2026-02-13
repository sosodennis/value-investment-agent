from src.agents.fundamental.application.view_models import (
    derive_fundamental_preview_view_model,
)
from src.agents.fundamental.interface.formatters import format_fundamental_preview


def test_derive_fundamental_preview_view_model_extracts_metrics() -> None:
    view_model = derive_fundamental_preview_view_model(
        {"ticker": "TSLA", "model_type": "saas"},
        [
            {
                "base": {
                    "total_revenue": {"value": 100000000000},
                    "net_income": {"value": 15000000000},
                    "total_assets": {"value": 200000000000},
                    "total_equity": {"value": 50000000000},
                }
            }
        ],
    )
    metrics = view_model["metrics"]
    assert metrics["revenue_raw"] == 100000000000
    assert metrics["net_income_raw"] == 15000000000
    assert metrics["total_assets_raw"] == 200000000000
    assert metrics["roe_ratio"] == 0.3


def test_format_fundamental_preview_formats_currency_and_roe() -> None:
    preview = format_fundamental_preview(
        {
            "ticker": "TSLA",
            "company_name": "Tesla",
            "selected_model": "saas",
            "sector": "Consumer",
            "industry": "Auto",
            "valuation_score": 0.85,
            "status": "done",
            "metrics": {
                "revenue_raw": 100000000000,
                "net_income_raw": 15000000000,
                "total_assets_raw": 200000000000,
                "roe_ratio": 0.3,
            },
        }
    )
    assert preview["key_metrics"]["Revenue"] == "$100.0B"
    assert preview["key_metrics"]["Net Income"] == "$15.0B"
    assert preview["key_metrics"]["Total Assets"] == "$200.0B"
    assert preview["key_metrics"]["ROE"] == "30.0%"
