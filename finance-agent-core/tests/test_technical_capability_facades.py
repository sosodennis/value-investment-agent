from __future__ import annotations

from importlib import import_module

import pytest


@pytest.mark.parametrize(
    ("module_name", "required_exports"),
    [
        (
            "src.agents.technical.capabilities.alerts.public",
            {
                "AlertRuntimeRequest",
                "AlertRuntimeResult",
                "AlertRuntimeService",
                "AlertSignal",
            },
        ),
        (
            "src.agents.technical.capabilities.calibration.public",
            {
                "TechnicalDirectionCalibrationConfig",
                "TechnicalDirectionCalibrationObservation",
                "calibrate_direction_confidence",
                "load_technical_direction_calibration_mapping",
            },
        ),
        (
            "src.observability.technical.public",
            {
                "TechnicalPredictionEventRecord",
                "OutcomeLabelingRequest",
                "TechnicalDecisionObservabilityRuntimeService",
                "TechnicalDecisionObservabilityRepository",
            },
        ),
        (
            "src.agents.technical.capabilities.features.public",
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
            "src.agents.technical.capabilities.interpretation.public",
            {"InterpretationGuardrailOutcome", "apply_interpretation_guardrail"},
        ),
        (
            "src.agents.technical.capabilities.artifacts",
            {"build_default_technical_artifact_repository"},
        ),
        (
            "src.agents.technical.capabilities.governance",
            {"TechnicalGovernanceRegistry", "build_technical_governance_registry"},
        ),
        (
            "src.agents.technical.capabilities.market_data.public",
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
            "src.agents.technical.capabilities.patterns.public",
            {"PatternRuntimeRequest", "PatternRuntimeResult", "PatternRuntimeService"},
        ),
        (
            "src.agents.technical.capabilities.regime.public",
            {"RegimeFrame", "RegimePack", "RegimeRuntimeService"},
        ),
        (
            "src.agents.technical.capabilities.signal_fusion.public",
            {
                "FusionRuntimeService",
                "SemanticTagPolicyInput",
                "assemble_semantic_tags",
                "safe_float",
            },
        ),
        (
            "src.agents.technical.capabilities.verification.public",
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


def test_market_data_package_facade_does_not_expose_provider_adapter() -> None:
    facade = import_module("src.agents.technical.capabilities.market_data")
    public = import_module("src.agents.technical.capabilities.market_data.public")

    assert set(facade.__all__) == set(public.__all__)
    assert all(hasattr(facade, name) for name in facade.__all__)
    assert not hasattr(facade, "YahooMarketDataProvider")


def test_technical_capability_roots_do_not_expose_infrastructure_adapters() -> None:
    artifacts = import_module("src.agents.technical.capabilities.artifacts")
    interpretation = import_module("src.agents.technical.capabilities.interpretation")

    assert not hasattr(artifacts, "TechnicalArtifactRepository")
    assert not hasattr(interpretation, "TechnicalInterpretationProvider")


def test_observability_facade_matches_public_contract_without_infrastructure() -> None:
    facade = import_module("src.observability.technical")
    public = import_module("src.observability.technical.public")

    assert facade.__all__ == public.__all__
    assert all(hasattr(facade, name) for name in facade.__all__)
    assert "TechnicalDecisionObservabilityRepository" in facade.__all__
    assert not any(name.startswith("SqlAlchemy") for name in facade.__all__)
    assert not any("Worker" in name for name in facade.__all__)
    assert not any(name.startswith("build_default") for name in facade.__all__)
