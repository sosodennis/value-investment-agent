from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from src.agents.technical.interface.contracts import (
    EvidenceBreakoutSignalModel,
    EvidenceScorecardSummaryModel,
    QuantContextSummaryModel,
    RegimeSummaryModel,
    StructureConfluenceSummaryModel,
    VolumeProfileSummaryModel,
)
from src.shared.kernel.types import JSONObject


class TechnicalEvidenceBundleLike(Protocol):
    primary_timeframe: str | None
    support_levels: Sequence[float]
    resistance_levels: Sequence[float]
    breakout_signals: Sequence[EvidenceBreakoutSignalModel]
    scorecard_summary: EvidenceScorecardSummaryModel | None
    quant_context_summary: QuantContextSummaryModel | None
    regime_summary: RegimeSummaryModel | None
    volume_profile_summary: VolumeProfileSummaryModel | None
    structure_confluence_summary: StructureConfluenceSummaryModel | None
    conflict_reasons: Sequence[str]


def build_projection_context_from_evidence(
    evidence_bundle: TechnicalEvidenceBundleLike | None,
) -> JSONObject:
    if evidence_bundle is None:
        return {}
    projection_context: JSONObject = {}
    regime_summary = _model_payload(evidence_bundle.regime_summary)
    if regime_summary is not None:
        projection_context["regime_summary"] = regime_summary
    quant_context_summary = _model_payload(evidence_bundle.quant_context_summary)
    if quant_context_summary is not None:
        projection_context["quant_context_summary"] = quant_context_summary
    volume_profile_summary = _model_payload(evidence_bundle.volume_profile_summary)
    if volume_profile_summary is not None:
        projection_context["volume_profile_summary"] = volume_profile_summary
    structure_confluence_summary = _model_payload(
        evidence_bundle.structure_confluence_summary
    )
    if structure_confluence_summary is not None:
        projection_context["structure_confluence_summary"] = (
            structure_confluence_summary
        )
    return projection_context


def serialize_evidence_bundle(
    evidence_bundle: TechnicalEvidenceBundleLike | None,
) -> JSONObject | None:
    if evidence_bundle is None or _is_empty_evidence_bundle(evidence_bundle):
        return None

    payload: JSONObject = {
        "primary_timeframe": evidence_bundle.primary_timeframe,
        "support_levels": list(evidence_bundle.support_levels),
        "resistance_levels": list(evidence_bundle.resistance_levels),
        "breakout_signals": [
            signal.model_dump(mode="json", exclude_none=True)
            for signal in evidence_bundle.breakout_signals
        ],
        "conflict_reasons": list(evidence_bundle.conflict_reasons),
    }
    scorecard_summary = _model_payload(evidence_bundle.scorecard_summary)
    if scorecard_summary is not None:
        payload["scorecard_summary"] = scorecard_summary
    quant_context_summary = _model_payload(evidence_bundle.quant_context_summary)
    if quant_context_summary is not None:
        payload["quant_context_summary"] = quant_context_summary
    regime_summary = _model_payload(evidence_bundle.regime_summary)
    if regime_summary is not None:
        payload["regime_summary"] = regime_summary
    volume_profile_summary = _model_payload(evidence_bundle.volume_profile_summary)
    if volume_profile_summary is not None:
        payload["volume_profile_summary"] = volume_profile_summary
    structure_confluence_summary = _model_payload(
        evidence_bundle.structure_confluence_summary
    )
    if structure_confluence_summary is not None:
        payload["structure_confluence_summary"] = structure_confluence_summary
    return payload


def build_setup_context_from_evidence(
    evidence_bundle: TechnicalEvidenceBundleLike | None,
) -> JSONObject | None:
    if evidence_bundle is None or _is_empty_evidence_bundle(evidence_bundle):
        return None

    setup_context: JSONObject = {
        "primary_timeframe": evidence_bundle.primary_timeframe,
        "support_levels": list(evidence_bundle.support_levels),
        "resistance_levels": list(evidence_bundle.resistance_levels),
        "breakout_signals": [
            signal.model_dump(mode="json", exclude_none=True)
            for signal in evidence_bundle.breakout_signals
        ],
        "scorecard_summary": _model_payload(evidence_bundle.scorecard_summary),
        "quant_context_summary": _model_payload(evidence_bundle.quant_context_summary),
        "conflict_reasons": list(evidence_bundle.conflict_reasons),
    }
    setup_context.update(build_projection_context_from_evidence(evidence_bundle))
    return setup_context


def _is_empty_evidence_bundle(evidence_bundle: TechnicalEvidenceBundleLike) -> bool:
    return (
        evidence_bundle.primary_timeframe is None
        and not evidence_bundle.support_levels
        and not evidence_bundle.resistance_levels
        and not evidence_bundle.breakout_signals
        and evidence_bundle.scorecard_summary is None
        and evidence_bundle.quant_context_summary is None
        and not evidence_bundle.conflict_reasons
        and evidence_bundle.regime_summary is None
        and evidence_bundle.volume_profile_summary is None
        and evidence_bundle.structure_confluence_summary is None
    )


def _model_payload(
    value: EvidenceScorecardSummaryModel
    | QuantContextSummaryModel
    | RegimeSummaryModel
    | VolumeProfileSummaryModel
    | StructureConfluenceSummaryModel
    | None,
) -> JSONObject | None:
    if value is None:
        return None
    payload = value.model_dump(mode="json", exclude_none=True)
    return payload if isinstance(payload, dict) else None
