from __future__ import annotations

import asyncio
from collections.abc import Mapping

from pydantic import BaseModel

from src.agents.technical.application.ports import TechnicalInterpretationInput
from src.agents.technical.application.semantic_pipeline_contracts import (
    BacktestContextResult,
    TechnicalPortLike,
    TechnicalProjectionArtifacts,
)
from src.agents.technical.application.signal_explainer_context_service import (
    build_signal_explainer_context,
)
from src.agents.technical.application.technical_evidence_bundle_service import (
    build_setup_context_from_evidence,
    build_technical_evidence_bundle,
)
from src.agents.technical.application.technical_report_projection_service import (
    build_report_projection_context,
)
from src.agents.technical.subdomains.signal_fusion import SemanticTagPolicyResult
from src.interface.artifacts.artifact_data_models import (
    TechnicalFusionReportArtifactData,
)
from src.shared.kernel.types import JSONObject


async def build_interpretation_input(
    *,
    ticker: str,
    technical_context: JSONObject,
    tags_result: SemanticTagPolicyResult,
    backtest_context_result: BacktestContextResult,
    technical_port: TechnicalPortLike,
    projection_artifacts: TechnicalProjectionArtifacts | None = None,
) -> TechnicalInterpretationInput:
    artifacts = projection_artifacts or await load_projection_artifacts(
        technical_context=technical_context,
        technical_port=technical_port,
    )

    confidence_raw = technical_context.get("confidence_calibrated")
    confidence = (
        float(confidence_raw) if isinstance(confidence_raw, int | float) else None
    )
    return TechnicalInterpretationInput(
        ticker=ticker,
        direction=tags_result.direction,
        risk_level=tags_result.risk_level,
        confidence=confidence,
        confidence_calibrated=confidence,
        summary_tags=tuple(tags_result.tags),
        evidence_items=tuple(tags_result.evidence_list),
        momentum_extremes=_read_optional_object(
            technical_context.get("momentum_extremes")
        ),
        setup_context=build_setup_context_from_evidence(artifacts.evidence_bundle),
        validation_context=_build_validation_context(backtest_context_result),
        diagnostics_context=_build_diagnostics_context(
            technical_context=technical_context,
            fusion_report=artifacts.fusion_report,
        ),
        signal_explainer_context=build_signal_explainer_context(artifacts.feature_pack),
    )


async def load_projection_artifacts(
    *,
    technical_context: JSONObject,
    technical_port: TechnicalPortLike,
) -> TechnicalProjectionArtifacts:
    feature_pack_id = _read_optional_text(technical_context.get("feature_pack_id"))
    pattern_pack_id = _read_optional_text(technical_context.get("pattern_pack_id"))
    regime_pack_id = _read_optional_text(technical_context.get("regime_pack_id"))
    fusion_report_id = _read_optional_text(technical_context.get("fusion_report_id"))
    alerts_id = _read_optional_text(technical_context.get("alerts_id"))
    direction_scorecard_id = _read_optional_text(
        technical_context.get("direction_scorecard_id")
    )
    (
        feature_pack,
        pattern_pack,
        regime_pack,
        fusion_report,
        alerts,
        direction_scorecard,
    ) = await asyncio.gather(
        technical_port.load_feature_pack(feature_pack_id),
        technical_port.load_pattern_pack(pattern_pack_id),
        technical_port.load_regime_pack(regime_pack_id),
        technical_port.load_fusion_report(fusion_report_id),
        technical_port.load_alerts(alerts_id),
        technical_port.load_direction_scorecard(direction_scorecard_id),
    )
    return TechnicalProjectionArtifacts(
        feature_pack=feature_pack,
        pattern_pack=pattern_pack,
        regime_pack=regime_pack,
        fusion_report=fusion_report,
        alerts=alerts,
        direction_scorecard=direction_scorecard,
        evidence_bundle=build_technical_evidence_bundle(
            artifacts=TechnicalProjectionArtifacts(
                feature_pack=feature_pack,
                pattern_pack=pattern_pack,
                regime_pack=regime_pack,
                fusion_report=fusion_report,
                alerts=alerts,
                direction_scorecard=direction_scorecard,
            )
        ),
    )


def build_projection_context(
    *,
    artifacts: TechnicalProjectionArtifacts,
) -> JSONObject:
    return build_report_projection_context(artifacts=artifacts)


def _build_validation_context(
    backtest_context_result: BacktestContextResult,
) -> JSONObject | None:
    report = backtest_context_result.verification_report
    if (
        report is None
        and not backtest_context_result.backtest_context
        and not backtest_context_result.wfa_context
    ):
        return None
    baseline_status = None
    baseline_gates = None
    robustness_flags: list[str] = []
    degraded_reasons: list[str] = []
    if report is not None:
        baseline_gates = (
            dict(report.baseline_gates)
            if isinstance(report.baseline_gates, Mapping)
            else None
        )
        if baseline_gates is not None:
            status = baseline_gates.get("status")
            baseline_status = str(status) if isinstance(status, str) else None
        robustness_flags = list(report.robustness_flags or [])
        degraded_reasons = list(report.degraded_reasons or [])
    return {
        "backtest_summary": backtest_context_result.backtest_context or None,
        "wfa_summary": backtest_context_result.wfa_context or None,
        "baseline_status": baseline_status,
        "baseline_gates": baseline_gates,
        "robustness_flags": robustness_flags,
        "degraded_reasons": degraded_reasons,
        "is_degraded": backtest_context_result.is_degraded,
    }


def _build_diagnostics_context(
    *,
    technical_context: JSONObject,
    fusion_report: TechnicalFusionReportArtifactData | None,
) -> JSONObject | None:
    degraded_reasons = technical_context.get("degraded_reasons")
    diagnostics_reasons = (
        list(degraded_reasons) if isinstance(degraded_reasons, list) else []
    )
    if not diagnostics_reasons and fusion_report is not None:
        diagnostics_reasons = list(fusion_report.degraded_reasons or [])
    calibration = _read_optional_object(technical_context.get("confidence_calibration"))
    fusion_conflicts = (
        list(fusion_report.conflict_reasons)
        if fusion_report is not None and fusion_report.conflict_reasons
        else []
    )
    if not diagnostics_reasons and calibration is None and not fusion_conflicts:
        return None
    return {
        "degraded_reasons": diagnostics_reasons,
        "confidence_calibration": calibration,
        "fusion_conflicts": fusion_conflicts,
    }


def _read_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _read_optional_object(value: object) -> JSONObject | None:
    if isinstance(value, BaseModel):
        dumped = value.model_dump(mode="json", exclude_none=True)
        return dumped if isinstance(dumped, dict) else None
    if not isinstance(value, Mapping):
        return None
    return dict(value)
