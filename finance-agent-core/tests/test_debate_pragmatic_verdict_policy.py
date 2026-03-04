from src.agents.debate.domain.pragmatic_verdict_policy import (
    calculate_pragmatic_verdict,
)


def test_calculate_pragmatic_verdict_data_quality_path_is_safe() -> None:
    conclusion_data = {
        "scenario_analysis": {
            "bull_case": {"probability": 40, "price_implication": "FLAT"},
            "base_case": {"probability": 30, "price_implication": "FLAT"},
            "bear_case": {"probability": 30, "price_implication": "FLAT"},
        },
        "risk_profile": "GROWTH_TECH",
    }

    metrics = calculate_pragmatic_verdict(
        conclusion_data,
        ticker="GOOG",
        get_risk_free_rate=lambda: 0.03,
        get_payoff_map=lambda _ticker, _risk_profile: {
            "SURGE": 0.25,
            "MODERATE_UP": 0.1,
            "FLAT": 0.0,
            "MODERATE_DOWN": -0.1,
            "CRASH": -0.25,
        },
    )

    assert metrics["data_quality_warning"] is True
    assert metrics["final_verdict"] == "NEUTRAL"
    assert metrics["analysis_bias"] == "UNCERTAIN"
    assert metrics["conviction"] == 30
    assert isinstance(metrics["rr_ratio"], float)
