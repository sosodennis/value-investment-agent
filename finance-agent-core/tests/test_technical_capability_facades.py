from __future__ import annotations

from importlib import import_module

import pytest


@pytest.mark.parametrize(
    ("module_name", "required_exports"),
    [
        (
            "src.agents.technical.subdomains.calibration.public",
            {
                "TechnicalDirectionCalibrationConfig",
                "TechnicalDirectionCalibrationObservation",
                "calibrate_direction_confidence",
                "load_technical_direction_calibration_mapping",
            },
        ),
        (
            "src.agents.technical.subdomains.decision_observability.public",
            {
                "TechnicalPredictionEventRecord",
                "OutcomeLabelingRequest",
                "TechnicalDecisionObservabilityRuntimeService",
                "TechnicalDecisionObservabilityRepository",
            },
        ),
        (
            "src.agents.technical.subdomains.features.public",
            {
                "FeatureRuntimeService",
                "IIndicatorEngine",
                "MacdIndicator",
                "PandasTaIndicatorEngine",
                "calculate_rolling_fracdiff",
                "compute_realized_volatility",
            },
        ),
        (
            "src.agents.technical.subdomains.interpretation.public",
            {"InterpretationGuardrailOutcome", "apply_interpretation_guardrail"},
        ),
        (
            "src.agents.technical.subdomains.market_data.public",
            {
                "IMarketDataProvider",
                "MarketDataCacheConfig",
                "MarketDataOhlcvFetchResult",
                "MarketDataRetryPolicy",
                "MultiTimeframeFetchRequest",
                "build_default_market_data_provider",
                "fetch_timeseries_bundle",
            },
        ),
        (
            "src.agents.technical.subdomains.regime.public",
            {"RegimeFrame", "RegimePack", "RegimeRuntimeService"},
        ),
        (
            "src.agents.technical.subdomains.signal_fusion.public",
            {
                "FusionRuntimeService",
                "SemanticTagPolicyInput",
                "assemble_semantic_tags",
                "safe_float",
            },
        ),
        (
            "src.agents.technical.subdomains.verification.public",
            {
                "VerificationRuntimeService",
                "VerificationGateResult",
                "evaluate_verification_baseline",
            },
        ),
    ],
)
def test_technical_capability_facade_exports_stable_contracts(
    module_name: str,
    required_exports: set[str],
) -> None:
    facade = import_module(module_name)

    exports = getattr(facade, "__all__", None)
    assert isinstance(exports, list)
    assert len(exports) == len(set(exports))
    assert required_exports <= set(exports)
    assert all(hasattr(facade, name) for name in exports)
    assert not any(
        "infrastructure" in name.lower() or "node" in name.lower() for name in exports
    )
