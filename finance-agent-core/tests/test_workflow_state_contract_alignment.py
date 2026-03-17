from src.workflow.state import (
    AgentState,
    FinancialNewsContext,
    FundamentalAnalysisContext,
    TechnicalAnalysisContext,
)


def test_fundamental_context_contract_is_canonical() -> None:
    keys = set(FundamentalAnalysisContext.__annotations__)
    assert keys == {
        "model_type",
        "financial_reports_artifact_id",
        "artifact",
    }


def test_news_context_contract_is_canonical() -> None:
    keys = set(FinancialNewsContext.__annotations__)
    assert keys == {
        "search_artifact_id",
        "selection_artifact_id",
        "news_items_artifact_id",
        "report_id",
        "artifact",
    }


def test_technical_context_contract_is_canonical() -> None:
    keys = set(TechnicalAnalysisContext.__annotations__)
    assert keys == {
        "latest_price",
        "optimal_d",
        "z_score_latest",
        "signal",
        "statistical_strength",
        "risk_level",
        "llm_interpretation",
        "semantic_tags",
        "memory_strength",
        "is_degraded",
        "degraded_reasons",
        "window_length",
        "adf_statistic",
        "adf_pvalue",
        "bollinger",
        "statistical_strength_val",
        "macd",
        "obv",
        "price_artifact_id",
        "chart_data_id",
        "timeseries_bundle_id",
        "indicator_series_id",
        "alerts_id",
        "feature_pack_id",
        "pattern_pack_id",
        "regime_pack_id",
        "fusion_report_id",
        "verification_report_id",
        "artifact",
    }
    assert "status" not in keys
    assert "signals" not in keys


def test_root_state_contains_internal_progress_contract() -> None:
    keys = set(AgentState.__annotations__)
    assert "internal_progress" in keys
    assert "ticker" not in keys
