from src.agents.fundamental.interface.workflow_orchestrator.formatters import (
    format_fundamental_preview,
)
from src.agents.fundamental.interface.workflow_orchestrator.preview_projection_service import (
    project_fundamental_preview,
)


def test_project_fundamental_preview_extracts_metrics() -> None:
    projection = project_fundamental_preview(
        {
            "ticker": "TSLA",
            "model_type": "saas",
            "assumption_breakdown": {"total_assumptions": 2},
            "data_freshness": {"market_data": {"provider": "yfinance"}},
            "assumption_risk_level": "medium",
            "data_quality_flags": ["defaults_present"],
            "time_alignment_status": "ok",
            "forward_signal_summary": {"signals_total": 2, "signals_accepted": 1},
            "forward_signal_risk_level": "medium",
            "forward_signal_evidence_count": 3,
        },
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
    metrics = projection["metrics"]
    assert metrics["revenue_raw"] == 100000000000
    assert metrics["net_income_raw"] == 15000000000
    assert metrics["total_assets_raw"] == 200000000000
    assert metrics["roe_ratio"] == 0.3
    assert projection["assumption_breakdown"]["total_assumptions"] == 2
    assert projection["data_freshness"]["market_data"]["provider"] == "yfinance"
    assert projection["assumption_risk_level"] == "medium"
    assert projection["data_quality_flags"] == ["defaults_present"]
    assert projection["time_alignment_status"] == "ok"
    assert projection["forward_signal_summary"]["signals_total"] == 2
    assert projection["forward_signal_risk_level"] == "medium"
    assert projection["forward_signal_evidence_count"] == 3


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
            "assumption_breakdown": {
                "total_assumptions": 2,
            },
            "data_freshness": {
                "market_data": {"provider": "yfinance"},
            },
            "assumption_risk_level": "high",
            "data_quality_flags": ["defaults_present"],
            "time_alignment_status": "high_risk",
            "forward_signal_summary": {"signals_total": 2, "signals_accepted": 1},
            "forward_signal_risk_level": "medium",
            "forward_signal_evidence_count": 3,
        }
    )
    assert preview["key_metrics"]["Revenue"] == "$100.0B"
    assert preview["key_metrics"]["Net Income"] == "$15.0B"
    assert preview["key_metrics"]["Total Assets"] == "$200.0B"
    assert preview["key_metrics"]["ROE"] == "30.0%"
    assert preview["assumption_breakdown"]["total_assumptions"] == 2
    assert preview["data_freshness"]["market_data"]["provider"] == "yfinance"
    assert preview["assumption_risk_level"] == "high"
    assert preview["data_quality_flags"] == ["defaults_present"]
    assert preview["time_alignment_status"] == "high_risk"
    assert preview["forward_signal_summary"]["signals_total"] == 2
    assert preview["forward_signal_risk_level"] == "medium"
    assert preview["forward_signal_evidence_count"] == 3
