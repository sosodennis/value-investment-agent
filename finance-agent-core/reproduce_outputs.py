import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from src.interface.mappers import NodeOutputMapper
from src.workflow.nodes.fundamental_analysis.adapter import (
    output_adapter as fa_output_adapter,
)
from src.workflow.nodes.technical_analysis.adapter import (
    output_adapter as ta_output_adapter,
)


def test_fundamental_adapter():
    print("\n--- Testing Fundamental Analysis Adapter ---")
    mock_input = {
        "ticker": "AAPL",
        "fundamental_analysis": {
            "model_type": "saas",
            "latest_report_id": "report_123",
            "financial_reports": [
                {
                    "ticker": "AAPL",
                    "period_end_date": "2023-09-30",
                    "period_type": "10-K",
                    "base": {
                        "total_revenue": 1000,
                        "net_income": 200,
                        "total_equity": 500,
                    },
                    "valuation": {"score": 85, "fair_value": 150},
                }
            ],
        },
        "intent_extraction": {
            "company_profile": {
                "name": "Apple Inc.",
                "sector": "Technology",
                "industry": "Consumer Electronics",
            }
        },
    }

    result = fa_output_adapter(mock_input)
    print(f"Sub-output keys: {list(result.keys())}")

    # Simulate Global State
    global_state = {"fundamental_analysis": result["fundamental_analysis"]}
    mapped = NodeOutputMapper.map_all_outputs(global_state)

    if "fundamental_analysis" in mapped:
        print("✅ FA Artifact Found")
        artifact = mapped["fundamental_analysis"]
        print(f"Summary: {artifact.get('summary')}")
        print(f"Preview Keys: {list(artifact.get('preview', {}).keys())}")
        print(f"Reference: {artifact.get('reference')}")
    else:
        print("❌ FA Artifact Missing")


def test_technical_adapter():
    print("\n--- Testing Technical Analysis Adapter ---")
    mock_input = {
        "technical_analysis": {
            "chart_data_id": "chart_789",
            "signal": "buy",
            "optimal_d": 0.45,
            # Mocking fields expected by mapper/adapter
            "raw_data": {"z_score_series": {}},
            "frac_diff_metrics": {"optimal_d": 0.45, "adf_pvalue": 0.01},
            "signal_state": {"z_score": 1.5, "risk_level": "low"},
            "ticker": "AAPL",
        },
        "ticker": "AAPL",
    }

    result = ta_output_adapter(mock_input)

    # Simulate Global State
    global_state = {"technical_analysis": result["technical_analysis"]}
    mapped = NodeOutputMapper.map_all_outputs(global_state)

    if "technical_analysis" in mapped:
        print("✅ TA Artifact Found")
        artifact = mapped["technical_analysis"]
        print(f"Summary: {artifact.get('summary')}")
        print(f"Preview Keys: {list(artifact.get('preview', {}).keys())}")
        print(f"Reference: {artifact.get('reference')}")
    else:
        print("❌ TA Artifact Missing")


if __name__ == "__main__":
    test_fundamental_adapter()
    test_technical_adapter()
