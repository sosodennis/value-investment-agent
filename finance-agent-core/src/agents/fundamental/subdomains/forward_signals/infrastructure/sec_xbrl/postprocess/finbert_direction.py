from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass

from src.agents.fundamental.subdomains.forward_signals.application.ports import (
    FinbertAnalyzerProvider,
)

_FINBERT_DIRECTION_ENABLED = os.getenv(
    "SEC_TEXT_FINBERT_DIRECTION_ENABLED", "1"
).strip().lower() in {"1", "true", "yes"}
_FINBERT_DIRECTION_MIN_CONFIDENCE = float(
    os.getenv("SEC_TEXT_FINBERT_DIRECTION_MIN_CONFIDENCE", "0.72")
)
_FINBERT_DIRECTION_MAX_EVIDENCE = max(
    1, int(os.getenv("SEC_TEXT_FINBERT_DIRECTION_MAX_EVIDENCE", "2"))
)
_FINBERT_DIRECTION_MAX_TEXT_CHARS = max(
    200, int(os.getenv("SEC_TEXT_FINBERT_DIRECTION_MAX_TEXT_CHARS", "1200"))
)
_FINBERT_DIRECTION_ALLOW_NUMERIC = os.getenv(
    "SEC_TEXT_FINBERT_DIRECTION_ALLOW_NUMERIC", "0"
).strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class FinbertDirectionReview:
    elapsed_ms: float
    reviewed: bool
    accepted: bool
    direction: str | None
    confidence: float
    label: str | None
    reason: str


def build_finbert_direction_reviewer(
    get_analyzer_fn: FinbertAnalyzerProvider,
) -> Callable[[str, str, list[dict[str, object]]], FinbertDirectionReview]:
    def _review_signal_direction_with_finbert(
        metric: str,
        baseline_direction: str,
        evidence: list[dict[str, object]],
    ) -> FinbertDirectionReview:
        return review_signal_direction_with_finbert(
            metric=metric,
            baseline_direction=baseline_direction,
            evidence=evidence,
            get_analyzer_fn=get_analyzer_fn,
        )

    return _review_signal_direction_with_finbert


def disabled_finbert_direction_reviewer(
    *,
    metric: str,
    baseline_direction: str,
    evidence: list[dict[str, object]],
) -> FinbertDirectionReview:
    return _review_result(
        elapsed_ms=0.0,
        reviewed=False,
        accepted=False,
        direction=None,
        confidence=0.0,
        label=None,
        reason="disabled",
    )


def review_signal_direction_with_finbert(
    *,
    metric: str,
    baseline_direction: str,
    evidence: list[dict[str, object]],
    get_analyzer_fn: FinbertAnalyzerProvider,
) -> FinbertDirectionReview:
    started = time.perf_counter()
    if not _FINBERT_DIRECTION_ENABLED:
        return _review_result(
            elapsed_ms=_elapsed_ms(started),
            reviewed=False,
            accepted=False,
            direction=None,
            confidence=0.0,
            label=None,
            reason="disabled",
        )
    if metric not in {"growth_outlook", "margin_outlook"}:
        return _review_result(
            elapsed_ms=_elapsed_ms(started),
            reviewed=False,
            accepted=False,
            direction=None,
            confidence=0.0,
            label=None,
            reason="unsupported_metric",
        )
    if not _FINBERT_DIRECTION_ALLOW_NUMERIC and _has_numeric_evidence(evidence):
        return _review_result(
            elapsed_ms=_elapsed_ms(started),
            reviewed=False,
            accepted=False,
            direction=None,
            confidence=0.0,
            label=None,
            reason="numeric_evidence_guard",
        )

    review_text = _build_review_text(evidence)
    if not review_text:
        return _review_result(
            elapsed_ms=_elapsed_ms(started),
            reviewed=False,
            accepted=False,
            direction=None,
            confidence=0.0,
            label=None,
            reason="empty_text",
        )

    analyzer = get_analyzer_fn()
    if not analyzer.is_available():
        return _review_result(
            elapsed_ms=_elapsed_ms(started),
            reviewed=False,
            accepted=False,
            direction=None,
            confidence=0.0,
            label=None,
            reason="model_unavailable",
        )

    result = analyzer.analyze(review_text)
    if result is None:
        return _review_result(
            elapsed_ms=_elapsed_ms(started),
            reviewed=True,
            accepted=False,
            direction=None,
            confidence=0.0,
            label=None,
            reason="inference_failed",
        )

    label = result.label.lower().strip()
    confidence = float(result.score)
    if label not in {"positive", "negative", "neutral"}:
        return _review_result(
            elapsed_ms=_elapsed_ms(started),
            reviewed=True,
            accepted=False,
            direction=None,
            confidence=confidence,
            label=label,
            reason="unknown_label",
        )
    if label == "neutral":
        return _review_result(
            elapsed_ms=_elapsed_ms(started),
            reviewed=True,
            accepted=False,
            direction=None,
            confidence=confidence,
            label=label,
            reason="neutral_label",
        )
    if confidence < _FINBERT_DIRECTION_MIN_CONFIDENCE:
        return _review_result(
            elapsed_ms=_elapsed_ms(started),
            reviewed=True,
            accepted=False,
            direction=None,
            confidence=confidence,
            label=label,
            reason="low_confidence",
        )

    mapped_direction = "up" if label == "positive" else "down"
    if mapped_direction == baseline_direction:
        return _review_result(
            elapsed_ms=_elapsed_ms(started),
            reviewed=True,
            accepted=True,
            direction=mapped_direction,
            confidence=confidence,
            label=label,
            reason="accepted_same_direction",
        )
    return _review_result(
        elapsed_ms=_elapsed_ms(started),
        reviewed=True,
        accepted=True,
        direction=mapped_direction,
        confidence=confidence,
        label=label,
        reason="accepted_override_direction",
    )


def _build_review_text(evidence: list[dict[str, object]]) -> str:
    parts: list[str] = []
    for item in evidence[:_FINBERT_DIRECTION_MAX_EVIDENCE]:
        raw = item.get("full_text")
        if not isinstance(raw, str):
            continue
        normalized = " ".join(raw.split()).strip()
        if not normalized:
            continue
        parts.append(normalized)
    if not parts:
        return ""
    text = " ".join(parts)
    if len(text) <= _FINBERT_DIRECTION_MAX_TEXT_CHARS:
        return text
    clipped = text[:_FINBERT_DIRECTION_MAX_TEXT_CHARS].rstrip()
    boundary = clipped.rfind(" ")
    if boundary >= int(_FINBERT_DIRECTION_MAX_TEXT_CHARS * 0.7):
        return clipped[:boundary].rstrip()
    return clipped


def _has_numeric_evidence(evidence: list[dict[str, object]]) -> bool:
    for item in evidence:
        if item.get("rule") == "numeric_guidance":
            return True
        value_basis_points = item.get("value_basis_points")
        if isinstance(value_basis_points, int | float):
            return True
    return False


def _review_result(
    *,
    elapsed_ms: float,
    reviewed: bool,
    accepted: bool,
    direction: str | None,
    confidence: float,
    label: str | None,
    reason: str,
) -> FinbertDirectionReview:
    return FinbertDirectionReview(
        elapsed_ms=elapsed_ms,
        reviewed=reviewed,
        accepted=accepted,
        direction=direction,
        confidence=confidence,
        label=label,
        reason=reason,
    )


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0
