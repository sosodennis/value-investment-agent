from src.workflow.nodes.fundamental_analysis.mappers import (
    summarize_fundamental_for_preview,
)


def test_summarize_fundamental_for_preview_empty():
    ctx = {"ticker": "AAPL", "status": "done"}
    preview = summarize_fundamental_for_preview(ctx)

    assert preview["ticker"] == "AAPL"
    assert preview["status"] == "done"
    assert preview["key_metrics"] == {}


def test_summarize_fundamental_for_preview_with_reports():
    ctx = {
        "ticker": "TSLA",
        "company_name": "Tesla, Inc.",
        "model_type": "saas",
        "sector": "Consumer Cyclical",
        "industry": "Auto Manufacturers",
        "valuation_score": 0.85,
    }

    financial_reports = [
        {
            "base": {
                "total_revenue": {"value": 100000000000},  # 100B
                "net_income": {"value": 15000000000},  # 15B
                "total_assets": {"value": 200000000000},  # 200B
                "total_equity": {"value": 50000000000},  # 50B
            }
        }
    ]

    preview = summarize_fundamental_for_preview(ctx, financial_reports)

    assert preview["ticker"] == "TSLA"
    assert preview["key_metrics"]["Revenue"] == "$100.0B"
    assert preview["key_metrics"]["Net Income"] == "$15.0B"
    assert preview["key_metrics"]["ROE"] == "30.0%"
    assert preview["valuation_score"] == 0.85


def test_summarize_fundamental_for_preview_small_numbers():
    ctx = {"ticker": "SMALL"}
    financial_reports = [
        {
            "base": {
                "total_revenue": {"value": 500000},  # 0.5M
                "net_income": {"value": 50000},  # 0.05M
            }
        }
    ]

    preview = summarize_fundamental_for_preview(ctx, financial_reports)
    assert preview["key_metrics"]["Revenue"] == "$500,000"
    assert preview["key_metrics"]["Net Income"] == "$50,000"
