"""
LLM interpretation adapter for technical analysis.

Deterministic semantic decision rules are owned by domain policies.
This module only translates semantic tags into natural-language narration.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping

from src.agents.technical.application.ports import (
    TechnicalInterpretationInput,
    TechnicalInterpretationResult,
    TechnicalProviderFailure,
)
from src.agents.technical.interface.contracts import (
    AnalystPerspectiveEvidenceItemModel,
    AnalystPerspectiveModel,
    AnalystPerspectiveSignalExplainerModel,
)
from src.agents.technical.interface.interpretation_prompt_spec import (
    build_interpretation_prompt_spec,
)
from src.agents.technical.interface.prompt_renderers import (
    build_interpretation_chat_prompt,
)
from src.infrastructure.llm.provider import get_llm
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject

logger = get_logger(__name__)


async def generate_interpretation(
    payload: TechnicalInterpretationInput,
) -> TechnicalInterpretationResult:
    risk_level = payload.risk_level
    try:
        log_event(
            logger,
            event="technical_llm_interpretation_started",
            message="technical llm interpretation started",
            fields={"ticker": payload.ticker},
        )
        prompt_spec = build_interpretation_prompt_spec()

        prompt = build_interpretation_chat_prompt(
            system_prompt=prompt_spec.system,
            user_prompt=prompt_spec.user,
        )
        llm = get_llm()
        structured_llm = llm.with_structured_output(AnalystPerspectiveModel)
        chain = prompt | structured_llm

        response = await chain.ainvoke(
            {
                "ticker": payload.ticker,
                "direction": payload.direction,
                "risk_level": risk_level,
                "confidence": payload.confidence_calibrated,
                "summary_tags": json.dumps(
                    list(payload.summary_tags), ensure_ascii=True
                ),
                "momentum_extremes": _dump_json(payload.momentum_extremes),
                "setup_context": _dump_json(payload.setup_context),
                "signal_explainer_context": _dump_signal_explainer_context(payload),
                "validation_context": _dump_json(payload.validation_context),
                "diagnostics_context": _dump_json(payload.diagnostics_context),
                "evidence": _dump_json(list(payload.evidence_items)),
            }
        )
        response = _finalize_perspective(response, payload)

        interpretation = response.rationale_summary.strip()
        log_event(
            logger,
            event="technical_llm_interpretation_completed",
            message="technical llm interpretation completed",
            fields={
                "ticker": payload.ticker,
                "interpretation_preview": interpretation[:120],
                "stance": response.stance,
            },
        )
        return TechnicalInterpretationResult(
            perspective=response,
        )
    except Exception as exc:
        log_event(
            logger,
            event="technical_llm_interpretation_failed",
            message="technical llm interpretation failed",
            level=logging.ERROR,
            error_code="TECHNICAL_LLM_INTERPRETATION_FAILED",
            fields={"ticker": payload.ticker, "exception": str(exc)},
        )
        fallback = _build_fallback_perspective(payload)
        return TechnicalInterpretationResult(
            perspective=fallback,
            is_fallback=True,
            failure=TechnicalProviderFailure(
                failure_code="TECHNICAL_LLM_INTERPRETATION_FAILED",
                reason=str(exc),
            ),
        )


class TechnicalInterpretationProvider:
    async def generate_interpretation(
        self,
        payload: TechnicalInterpretationInput,
    ) -> TechnicalInterpretationResult:
        return await generate_interpretation(payload)


def _dump_json(value: object) -> str:
    if value is None:
        return "null"
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _dump_signal_explainer_context(payload: TechnicalInterpretationInput) -> str:
    items = [
        {
            "signal": item.signal,
            "plain_name": item.plain_name,
            "value_text": item.value_text,
            "timeframe": item.timeframe,
            "state": item.state,
            "what_it_measures": item.what_it_measures,
            "current_reading_hint": item.current_reading_hint,
            "why_it_matters": item.why_it_matters,
        }
        for item in payload.signal_explainer_context
    ]
    return _dump_json(items)


def _build_fallback_perspective(
    payload: TechnicalInterpretationInput,
) -> AnalystPerspectiveModel:
    stance = _resolve_stance(payload.direction, payload.validation_context)
    validation_note = _resolve_validation_note(payload.validation_context)
    top_evidence = [
        AnalystPerspectiveEvidenceItemModel(
            label=f"Signal {index + 1}",
            value_text=None,
            timeframe=None,
            rationale=item,
        )
        for index, item in enumerate(payload.evidence_items[:3])
    ]
    rationale_summary = _resolve_rationale_summary(
        direction=payload.direction,
        risk_level=payload.risk_level,
        evidence_items=payload.evidence_items,
        validation_note=validation_note,
    )
    perspective = AnalystPerspectiveModel(
        stance=stance,
        stance_summary=_resolve_stance_summary(stance, payload.risk_level),
        rationale_summary=rationale_summary,
        top_evidence=top_evidence or None,
        trigger_condition=_resolve_trigger_condition(payload.setup_context),
        invalidation_condition=_resolve_invalidation_condition(payload.setup_context),
        invalidation_level=_resolve_invalidation_level(payload.setup_context),
        validation_note=validation_note,
        confidence_note=_resolve_confidence_note(payload.confidence_calibrated),
        decision_posture=_resolve_decision_posture(stance),
    )
    return _finalize_perspective(perspective, payload)


def _finalize_perspective(
    perspective: AnalystPerspectiveModel,
    payload: TechnicalInterpretationInput,
) -> AnalystPerspectiveModel:
    plain_language_summary = _normalize_plain_language_summary(
        perspective.plain_language_summary,
        payload=payload,
        perspective=perspective,
    )
    signal_explainers = _normalize_signal_explainers(
        perspective.signal_explainers,
        payload=payload,
    )
    top_evidence = perspective.top_evidence[:3] if perspective.top_evidence else None
    return perspective.model_copy(
        update={
            "plain_language_summary": plain_language_summary,
            "signal_explainers": signal_explainers,
            "top_evidence": top_evidence,
        }
    )


def _normalize_plain_language_summary(
    raw_summary: str | None,
    *,
    payload: TechnicalInterpretationInput,
    perspective: AnalystPerspectiveModel,
) -> str:
    if isinstance(raw_summary, str) and raw_summary.strip():
        return raw_summary.strip()

    opening = _build_plain_language_opening(perspective.stance)
    detail_sentences = [
        item.current_reading_hint for item in payload.signal_explainer_context[:2]
    ]
    parts = [opening, *detail_sentences]
    validation_note = _resolve_validation_note(payload.validation_context)
    if validation_note is not None:
        parts.append(validation_note)
    return " ".join(part.strip() for part in parts if part and part.strip())


def _build_plain_language_opening(stance: str) -> str:
    if stance == "WAIT":
        return "The setup is not clear enough to support a strong directional view right now."
    if stance == "BULLISH_WATCH":
        return "The setup leans bullish, but it still looks more like a watchlist situation than a fully confirmed move."
    if stance == "BEARISH_WATCH":
        return "The setup leans bearish, but it still looks more like a watchlist situation than a decisive breakdown."
    return (
        "The setup looks mixed, so the market still reads as broadly neutral for now."
    )


def _normalize_signal_explainers(
    raw_explainers: list[AnalystPerspectiveSignalExplainerModel] | None,
    *,
    payload: TechnicalInterpretationInput,
) -> list[AnalystPerspectiveSignalExplainerModel] | None:
    fallback_map = {
        item.signal: AnalystPerspectiveSignalExplainerModel(
            signal=item.signal,
            plain_name=item.plain_name,
            value_text=item.value_text,
            timeframe=item.timeframe,
            what_it_means_now=item.current_reading_hint,
            why_it_matters_now=item.why_it_matters,
        )
        for item in payload.signal_explainer_context[:3]
    }
    if not raw_explainers:
        return list(fallback_map.values()) or None

    normalized: list[AnalystPerspectiveSignalExplainerModel] = []
    for explainer in raw_explainers[:3]:
        fallback = fallback_map.get(explainer.signal)
        normalized.append(
            explainer.model_copy(
                update={
                    "plain_name": explainer.plain_name
                    or (fallback.plain_name if fallback else explainer.signal),
                    "value_text": explainer.value_text
                    or (fallback.value_text if fallback else None),
                    "timeframe": explainer.timeframe
                    or (fallback.timeframe if fallback else None),
                    "what_it_means_now": explainer.what_it_means_now.strip()
                    if explainer.what_it_means_now.strip()
                    else (fallback.what_it_means_now if fallback else ""),
                    "why_it_matters_now": explainer.why_it_matters_now.strip()
                    if explainer.why_it_matters_now.strip()
                    else (fallback.why_it_matters_now if fallback else ""),
                }
            )
        )
    return normalized


def _resolve_stance(direction: str, validation_context: JSONObject | None) -> str:
    if validation_context is not None and validation_context.get("is_degraded") is True:
        return "WAIT"
    upper = direction.upper()
    if "BULLISH" in upper:
        return "BULLISH_WATCH"
    if "BEARISH" in upper:
        return "BEARISH_WATCH"
    return "NEUTRAL"


def _resolve_stance_summary(stance: str, risk_level: str) -> str:
    if stance == "WAIT":
        return "Signals are not reliable enough to press a directional view yet."
    return f"{stance.replace('_', ' ').title()} with {risk_level} risk."


def _resolve_rationale_summary(
    *,
    direction: str,
    risk_level: str,
    evidence_items: tuple[str, ...],
    validation_note: str | None,
) -> str:
    evidence_summary = (
        evidence_items[0] if evidence_items else "No strong confluence was detected."
    )
    if validation_note:
        return (
            f"Deterministic technical signals point to {direction.lower()}, "
            f"with {risk_level} risk. {evidence_summary} {validation_note}"
        )
    return (
        f"Deterministic technical signals point to {direction.lower()}, "
        f"with {risk_level} risk. {evidence_summary}"
    )


def _resolve_validation_note(validation_context: JSONObject | None) -> str | None:
    if validation_context is None:
        return None
    if validation_context.get("is_degraded") is True:
        return "Verification coverage is degraded, so the view should be treated cautiously."
    baseline_status = validation_context.get("baseline_status")
    if isinstance(baseline_status, str) and baseline_status.lower() not in {
        "pass",
        "ok",
    }:
        return (
            f"Validation status is {baseline_status.lower()}, which weakens conviction."
        )
    robustness_flags = validation_context.get("robustness_flags")
    if isinstance(robustness_flags, list) and robustness_flags:
        return "Verification flags are present and should temper conviction."
    return None


def _resolve_confidence_note(confidence: float | None) -> str | None:
    if confidence is None:
        return None
    return f"Calibrated confidence is {confidence:.0%}."


def _resolve_decision_posture(stance: str) -> str:
    if stance == "WAIT":
        return "WAIT"
    if stance == "NEUTRAL":
        return "MONITOR"
    return "CONFIRMATION_NEEDED"


def _resolve_trigger_condition(setup_context: JSONObject | None) -> str | None:
    if setup_context is None:
        return None
    breakouts = setup_context.get("breakout_signals")
    if not isinstance(breakouts, list) or not breakouts:
        return None
    first = breakouts[0]
    if not isinstance(first, Mapping):
        return None
    name = first.get("name")
    notes = first.get("notes")
    if isinstance(name, str) and isinstance(notes, str) and notes:
        return f"{name}: {notes}"
    if isinstance(name, str):
        return name
    return None


def _resolve_invalidation_condition(setup_context: JSONObject | None) -> str | None:
    if setup_context is None:
        return None
    support_levels = setup_context.get("support_levels")
    resistance_levels = setup_context.get("resistance_levels")
    if isinstance(support_levels, list) and support_levels:
        return f"Break below support near {support_levels[0]} invalidates the current watch."
    if isinstance(resistance_levels, list) and resistance_levels:
        return f"Failure around resistance near {resistance_levels[0]} invalidates follow-through."
    return None


def _resolve_invalidation_level(setup_context: JSONObject | None) -> float | None:
    if setup_context is None:
        return None
    support_levels = setup_context.get("support_levels")
    if isinstance(support_levels, list) and support_levels:
        value = support_levels[0]
        if isinstance(value, int | float):
            return float(value)
    resistance_levels = setup_context.get("resistance_levels")
    if isinstance(resistance_levels, list) and resistance_levels:
        value = resistance_levels[0]
        if isinstance(value, int | float):
            return float(value)
    return None
