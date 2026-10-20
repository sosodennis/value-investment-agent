from __future__ import annotations

from importlib import import_module
from types import ModuleType

FACADE_EXPORTS: dict[str, set[str]] = {
    "artifacts_provenance": {
        "FundamentalArtifactModel",
        "fundamental_artifact_repository",
        "parse_fundamental_artifact_model",
    },
    "core_valuation": {
        "ParamBuildResult",
        "ParamBuilderPayload",
        "ValuationModel",
        "ValuationModelRegistry",
        "apply_missing_metric_policy",
        "build_params",
        "resolve_calculator_model_type",
    },
    "financial_statements": {
        "FinancialReportBaseLike",
        "FinancialReportLike",
        "FinancialReportModel",
        "FinancialStatementsPayload",
        "FundamentalBaseModel",
        "FundamentalText",
        "OptionalFundamentalNumber",
        "OptionalFundamentalText",
        "TraceableFieldModel",
        "TraceableOptionalText",
        "TraceableProvenance",
        "TraceableValue",
        "ValuationModelRuntime",
        "fetch_financial_reports_payload",
        "parse_calculation_metrics",
        "parse_financial_reports_model",
        "parse_financial_statements_payload",
        "parse_valuation_model_runtime",
    },
    "forward_signals": {
        "DEFAULT_FORWARD_SIGNAL_CALIBRATION_CONFIG",
        "ForwardSignal",
        "ForwardSignalCalibrationConfig",
        "ForwardSignalDecision",
        "ForwardSignalEvidence",
        "ForwardSignalPayload",
        "ForwardSignalPayloadSourceLocator",
        "ForwardSignalPolicyResult",
        "ForwardSignalSourceLocator",
        "apply_forward_signal_policy",
        "build_finbert_direction_reviewer",
        "calibrate_signal_basis_points",
        "extract_forward_signals",
        "extract_forward_signals_from_sec_text",
        "extract_forward_signals_from_xbrl_reports",
        "parse_forward_signal_calibration_config",
        "parse_forward_signals",
        "serialize_forward_signals",
    },
    "model_selection": {
        "DEFAULT_SCORING_WEIGHTS",
        "MODEL_SPECS",
        "FinancialHealthInsights",
        "FundamentalPreviewMetrics",
        "FundamentalSelectionReport",
        "ModelCandidate",
        "ModelSelectionResult",
        "ModelSpec",
        "ScoringWeights",
        "SelectionField",
        "SelectionSignals",
        "build_latest_health_context",
        "build_model_selection_reasoning",
        "calculate_revenue_cagr",
        "extract_latest_health_insights",
        "extract_latest_preview_metrics",
        "project_selection_reports",
        "project_selection_reports_from_models",
        "select_valuation_model",
    },
    "market_data": {
        "MarketDataService",
        "MarketSnapshot",
        "market_data_service",
    },
}


def _load_facade(name: str) -> ModuleType:
    return import_module(f"src.agents.fundamental.subdomains.{name}.public")


def test_fundamental_public_facades_export_stable_contracts_only() -> None:
    for capability, expected_exports in FACADE_EXPORTS.items():
        facade = _load_facade(capability)

        assert set(facade.__all__) == expected_exports
        assert all(hasattr(facade, name) for name in expected_exports)
        assert not any(
            "workflow" in name.lower() or "infrastructure" in name.lower()
            for name in facade.__all__
        )


def test_market_data_public_facade_hides_infrastructure_assembly() -> None:
    facade = _load_facade("market_data")

    assert not hasattr(facade, "build_market_data_service")
    assert not hasattr(facade, "YahooFinanceProvider")
