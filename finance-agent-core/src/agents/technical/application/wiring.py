from __future__ import annotations

from src.agents.technical.application.factory import (
    TechnicalWorkflowDependencies,
    TechnicalWorkflowRunner,
    build_technical_orchestrator,
    build_technical_workflow_runner,
)
from src.agents.technical.subdomains.alerts import AlertRuntimeService
from src.agents.technical.subdomains.artifacts import (
    build_default_technical_artifact_repository,
)
from src.agents.technical.subdomains.features import (
    FeatureRuntimeService,
    IndicatorSeriesRuntimeService,
)
from src.agents.technical.subdomains.features.infrastructure import (
    PandasTaIndicatorEngine,
)
from src.agents.technical.subdomains.interpretation import (
    TechnicalInterpretationProvider,
)
from src.agents.technical.subdomains.market_data import YahooMarketDataProvider
from src.agents.technical.subdomains.patterns import PatternRuntimeService
from src.agents.technical.subdomains.regime import RegimeRuntimeService
from src.agents.technical.subdomains.signal_fusion import (
    FusionRuntimeService,
    assemble_semantic_tags,
)
from src.agents.technical.subdomains.verification import VerificationRuntimeService


def _assemble_semantic_tags_default(*args, **kwargs):
    return assemble_semantic_tags(*args, **kwargs)


def build_default_technical_workflow_runner() -> TechnicalWorkflowRunner:
    repository = build_default_technical_artifact_repository()
    orchestrator = build_technical_orchestrator(port=repository)
    market_data_provider = YahooMarketDataProvider()
    interpretation_provider = TechnicalInterpretationProvider()
    indicator_engine = PandasTaIndicatorEngine()
    if not indicator_engine.availability().available:
        indicator_engine = None
    feature_runtime = FeatureRuntimeService(indicator_engine=indicator_engine)
    indicator_series_runtime = IndicatorSeriesRuntimeService()
    alert_runtime = AlertRuntimeService()
    pattern_runtime = PatternRuntimeService()
    regime_runtime = RegimeRuntimeService()
    fusion_runtime = FusionRuntimeService()
    verification_runtime = VerificationRuntimeService()
    return build_technical_workflow_runner(
        orchestrator=orchestrator,
        deps=TechnicalWorkflowDependencies(
            market_data_provider=market_data_provider,
            interpretation_provider=interpretation_provider,
            feature_runtime=feature_runtime,
            indicator_series_runtime=indicator_series_runtime,
            alert_runtime=alert_runtime,
            pattern_runtime=pattern_runtime,
            regime_runtime=regime_runtime,
            fusion_runtime=fusion_runtime,
            verification_runtime=verification_runtime,
            assemble_semantic_tags_fn=_assemble_semantic_tags_default,
        ),
    )


_technical_workflow_runner: TechnicalWorkflowRunner | None = None


def get_technical_workflow_runner() -> TechnicalWorkflowRunner:
    global _technical_workflow_runner
    if _technical_workflow_runner is None:
        _technical_workflow_runner = build_default_technical_workflow_runner()
    return _technical_workflow_runner


__all__ = [
    "TechnicalWorkflowRunner",
    "build_default_technical_workflow_runner",
    "get_technical_workflow_runner",
]
