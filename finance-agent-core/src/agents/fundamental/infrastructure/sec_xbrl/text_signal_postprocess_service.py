from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from pydantic import ValidationError

from src.shared.kernel.types import JSONObject

from .finbert_direction import FinbertDirectionReview
from .signal_schema import ForwardSignalEvidencePayload, ForwardSignalPayload


class ReviewSignalDirectionWithFinbertFn(Protocol):
    def __call__(
        self,
        *,
        metric: str,
        baseline_direction: str,
        evidence: list[dict[str, object]],
    ) -> FinbertDirectionReview: ...


class ClampFn(Protocol):
    def __call__(self, value: float, min_value: float, max_value: float) -> float: ...


def build_forward_signal_payload(
    *,
    signal_id: str,
    source_type: str,
    metric: str,
    direction: str,
    value_basis_points: float,
    confidence: float,
    median_filing_age_days: int | None,
    evidence: list[JSONObject],
) -> dict[str, object] | None:
    try:
        validated_evidence = [
            ForwardSignalEvidencePayload.model_validate(item) for item in evidence
        ]
        payload = ForwardSignalPayload(
            signal_id=signal_id,
            source_type=source_type,
            metric=metric,
            direction=direction,
            value=round(value_basis_points, 2),
            unit="basis_points",
            confidence=round(confidence, 4),
            as_of=datetime.now(UTC).isoformat(),
            median_filing_age_days=median_filing_age_days,
            evidence=validated_evidence,
        )
        return payload.model_dump()
    except ValidationError:
        return None


def should_fast_skip_fls_with_phrases(
    *,
    analysis_sentences: list[str],
    fls_skip_signal_phrases: tuple[str, ...],
    has_forward_tense_cue_fn: Callable[[str], bool],
    contains_numeric_guidance_cue_fn: Callable[[str], bool],
) -> bool:
    if not analysis_sentences:
        return True
    for sentence in analysis_sentences:
        normalized = sentence.strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if has_forward_tense_cue_fn(normalized):
            return False
        if contains_numeric_guidance_cue_fn(normalized):
            return False
        if any(phrase in lowered for phrase in fls_skip_signal_phrases):
            return False
    return True


def preview_sentence(sentence: str, *, max_chars: int) -> str | None:
    normalized = " ".join(sentence.split())
    if not normalized:
        return None
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3] + "..."


def apply_finbert_direction_reviews(
    *,
    signals: list[dict[str, object]],
    review_signal_direction_with_finbert_fn: ReviewSignalDirectionWithFinbertFn,
    clamp_fn: ClampFn,
) -> dict[str, object]:
    if not signals:
        return empty_finbert_direction_diag_fields()

    total_ms = 0.0
    reviewed_total = 0
    accepted_total = 0
    overrides_total = 0
    reason_counter: Counter[str] = Counter()

    for signal in signals:
        metric_raw = signal.get("metric")
        baseline_direction_raw = signal.get("direction")
        evidence_raw = signal.get("evidence")
        if not isinstance(metric_raw, str) or not isinstance(
            baseline_direction_raw, str
        ):
            reason_counter["invalid_signal_shape"] += 1
            continue
        evidence: list[dict[str, object]] = []
        if isinstance(evidence_raw, list):
            evidence = [
                item
                for item in evidence_raw
                if isinstance(item, dict) and bool(item.get("full_text"))
            ]
        review = review_signal_direction_with_finbert_fn(
            metric=metric_raw,
            baseline_direction=baseline_direction_raw,
            evidence=evidence,
        )
        total_ms += review.elapsed_ms
        reason_counter[review.reason] += 1
        if review.reviewed:
            reviewed_total += 1
        if not review.accepted or review.direction is None:
            continue
        accepted_total += 1
        if review.direction != baseline_direction_raw:
            overrides_total += 1
            signal["direction"] = review.direction
        current_confidence = signal.get("confidence")
        if isinstance(current_confidence, int | float):
            blended_confidence = clamp_fn(
                (float(current_confidence) * 0.8) + (review.confidence * 0.2),
                0.52,
                0.90,
            )
            signal["confidence"] = round(blended_confidence, 4)

    review_candidates_total = len(signals)
    avg_ms = total_ms / review_candidates_total if review_candidates_total > 0 else 0.0
    return {
        "pipeline_finbert_direction_review_candidates_total": review_candidates_total,
        "pipeline_finbert_direction_reviewed_total": reviewed_total,
        "pipeline_finbert_direction_accepted_total": accepted_total,
        "pipeline_finbert_direction_overrides_total": overrides_total,
        "pipeline_finbert_direction_ms_total": round(total_ms, 3),
        "pipeline_finbert_direction_avg_ms": round(avg_ms, 3),
        "pipeline_finbert_direction_reasons": dict(reason_counter),
    }


def empty_finbert_direction_diag_fields() -> dict[str, object]:
    return {
        "pipeline_finbert_direction_review_candidates_total": 0,
        "pipeline_finbert_direction_reviewed_total": 0,
        "pipeline_finbert_direction_accepted_total": 0,
        "pipeline_finbert_direction_overrides_total": 0,
        "pipeline_finbert_direction_ms_total": 0.0,
        "pipeline_finbert_direction_avg_ms": 0.0,
        "pipeline_finbert_direction_reasons": {},
    }
