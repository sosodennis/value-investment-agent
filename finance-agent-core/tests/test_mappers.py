"""
Test script to verify the mapper architecture works correctly.
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.interface.mappers import NodeOutputMapper


# Test Technical Analysis mapping
def test_technical_analysis_mapping():
    # Simulate nested state from graph
    nested_output = {
        "technical_analysis": {
            "artifact": {
                "ticker": "AAPL",
                "frac_diff_metrics": {"optimal_d": 0.42, "adf_pvalue": 0.001},
                "signal_state": {"z_score": 1.5},
            }
        }
    }

    result = NodeOutputMapper.transform("technical_analysis", nested_output)

    assert result is not None, "Mapper returned None"
    assert "frac_diff_metrics" in result, "Missing frac_diff_metrics"
    assert (
        result["frac_diff_metrics"]["optimal_d"] == 0.42
    ), "optimal_d not extracted correctly"
    print("✅ Technical Analysis mapping works")


# Test Financial News mapping
def test_financial_news_mapping():
    nested_output = {
        "financial_news_research": {
            "artifact": {
                "ticker": "AAPL",
                "news_items": [{"id": "1", "title": "Test News"}],
                "overall_sentiment": "BULLISH",
            }
        }
    }

    result = NodeOutputMapper.transform("financial_news_research", nested_output)

    assert result is not None, "Mapper returned None"
    assert "news_items" in result, "Missing news_items"
    assert len(result["news_items"]) == 1, "news_items not extracted correctly"
    print("✅ Financial News mapping works")


# Test Fundamental Analysis mapping
def test_fundamental_analysis_mapping():
    nested_output = {
        "fundamental_analysis": {
            "artifact": {
                "ticker": "AAPL",
                "model_type": "DCF",
                "reasoning": "Test reasoning",
            }
        }
    }

    result = NodeOutputMapper.transform("fundamental_analysis", nested_output)

    assert result is not None, "Mapper returned None"
    assert "model_type" in result, "Missing model_type"
    assert result["model_type"] == "DCF", "model_type not extracted correctly"
    print("✅ Fundamental Analysis mapping works")


# Test Debate mapping
def test_debate_mapping():
    nested_output = {
        "debate": {"artifact": {"final_verdict": "LONG", "conviction": 75}}
    }

    result = NodeOutputMapper.transform("debate", nested_output)

    assert result is not None, "Mapper returned None"
    assert "final_verdict" in result, "Missing final_verdict"
    assert result["final_verdict"] == "LONG", "final_verdict not extracted correctly"
    print("✅ Debate mapping works")


if __name__ == "__main__":
    test_technical_analysis_mapping()
    test_financial_news_mapping()
    test_fundamental_analysis_mapping()
    test_debate_mapping()
    print("\n🎉 All mapper tests passed!")
