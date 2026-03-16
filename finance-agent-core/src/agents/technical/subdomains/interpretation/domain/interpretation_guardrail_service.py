from __future__ import annotations

from dataclasses import dataclass

INTERPRETATION_GUARDRAIL_VERSION = "ta_interpretation_guardrail_v1"

_BULLISH_HINTS = (
    "bullish",
    "uptrend",
    "upward",
    "breakout",
    "strengthening",
    "strong buy",
    "buy",
    "long",
)
_BEARISH_HINTS = (
    "bearish",
    "downtrend",
    "downward",
    "breakdown",
    "weakening",
    "strong sell",
    "sell",
    "short",
)
_NEUTRAL_HINTS = (
    "neutral",
    "sideways",
    "range",
    "range-bound",
    "consolidation",
    "choppy",
    "indecision",
    "flat",
    "hold",
)


@dataclass(frozen=True)
class InterpretationGuardrailOutcome:
    content: str
    is_aligned: bool
    detected_direction: str | None
    violation_reason: str | None
    guardrail_version: str = INTERPRETATION_GUARDRAIL_VERSION


def apply_interpretation_guardrail(
    *,
    direction: str,
    risk_level: str,
    interpretation: str,
) -> InterpretationGuardrailOutcome:
    expected = _normalize_expected_direction(direction)
    normalized_text = (interpretation or "").strip()
    if not normalized_text:
        fallback = _fallback_text(expected, risk_level)
        return InterpretationGuardrailOutcome(
            content=fallback,
            is_aligned=False,
            detected_direction=None,
            violation_reason="interpretation_empty",
        )

    detected = _detect_direction_hint(normalized_text)
    if detected is None:
        return InterpretationGuardrailOutcome(
            content=normalized_text,
            is_aligned=True,
            detected_direction=None,
            violation_reason=None,
        )

    if detected != expected:
        fallback = _fallback_text(expected, risk_level)
        return InterpretationGuardrailOutcome(
            content=fallback,
            is_aligned=False,
            detected_direction=detected,
            violation_reason=f"direction_mismatch:expected={expected},detected={detected}",
        )

    return InterpretationGuardrailOutcome(
        content=normalized_text,
        is_aligned=True,
        detected_direction=detected,
        violation_reason=None,
    )


def _normalize_expected_direction(direction: str) -> str:
    upper = (direction or "").upper()
    if "BULLISH" in upper:
        return "bullish"
    if "BEARISH" in upper:
        return "bearish"
    return "neutral"


def _detect_direction_hint(text: str) -> str | None:
    lowered = text.lower()
    bullish_hits = _count_hits(lowered, _BULLISH_HINTS)
    bearish_hits = _count_hits(lowered, _BEARISH_HINTS)
    neutral_hits = _count_hits(lowered, _NEUTRAL_HINTS)

    scores = {
        "bullish": bullish_hits,
        "bearish": bearish_hits,
        "neutral": neutral_hits,
    }

    max_hits = max(scores.values())
    if max_hits == 0:
        return None
    top = [label for label, count in scores.items() if count == max_hits]
    if len(top) != 1:
        return None
    return top[0]


def _count_hits(text: str, hints: tuple[str, ...]) -> int:
    return sum(1 for hint in hints if hint in text)


def _fallback_text(expected: str, risk_level: str) -> str:
    if expected == "bullish":
        posture = "bullish"
    elif expected == "bearish":
        posture = "bearish"
    else:
        posture = "neutral"
    return (
        "Technical analysis indicates a "
        f"{posture} posture with {risk_level} risk. "
        "This interpretation is aligned with the deterministic signal."
    )


__all__ = [
    "InterpretationGuardrailOutcome",
    "apply_interpretation_guardrail",
    "INTERPRETATION_GUARDRAIL_VERSION",
]
