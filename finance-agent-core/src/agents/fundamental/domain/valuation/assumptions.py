from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from src.shared.kernel.traceable import ManualProvenance, TraceableField

# Enterprise-grade policy note:
# - Do NOT silently assume values in production.
# - Defaults are allowed only for preview/prototyping and must be surfaced for review.
# - Every assumed value must be explicitly tagged with ManualProvenance.

DEFAULT_WACC = 0.10
DEFAULT_TERMINAL_GROWTH = 0.02
DEFAULT_DA_RATE = 0.04

BASELINE_HISTORICAL_WEIGHT = 0.30
BASELINE_CONSENSUS_WEIGHT = 0.50
BASELINE_ADJUSTMENT_WEIGHT = 0.20

MATURE_HISTORICAL_WEIGHT = 0.60
MATURE_CONSENSUS_WEIGHT = 0.35
MATURE_ADJUSTMENT_WEIGHT = 0.05

VOLATILE_HISTORICAL_WEIGHT = 0.10
VOLATILE_CONSENSUS_WEIGHT = 0.80
VOLATILE_ADJUSTMENT_WEIGHT = 0.10

MATURE_VOLATILITY_THRESHOLD = 0.05
DEFAULT_LONG_RUN_GROWTH_TARGET = 0.025
DEFAULT_HIGH_GROWTH_TRIGGER = 0.30
DEFAULT_FORWARD_SIGNAL_CONFIDENCE_THRESHOLD = 0.55
DEFAULT_FORWARD_SIGNAL_MAX_ADJUSTMENT_BPS = 300.0

SUPPORTED_FORWARD_SIGNAL_METRICS: tuple[str, ...] = (
    "growth_outlook",
    "margin_outlook",
    "capex_outlook",
    "credit_cost_outlook",
)
SUPPORTED_FORWARD_SIGNAL_SOURCES: tuple[str, ...] = (
    "mda",
    "earnings_call",
    "press_release",
    "news",
    "debate",
    "manual",
)
SUPPORTED_FORWARD_SIGNAL_DIRECTIONS: tuple[str, ...] = ("up", "down", "neutral")
SUPPORTED_FORWARD_SIGNAL_UNITS: tuple[str, ...] = ("bps", "ratio")


@dataclass(frozen=True)
class GrowthBlendWeights:
    historical: float
    consensus: float
    adjustment: float
    profile: str


@dataclass(frozen=True)
class GrowthBlendResult:
    blended_growth: float
    weights: GrowthBlendWeights
    rationale: str


@dataclass(frozen=True)
class ForwardSignalEvidence:
    text_snippet: str
    source_url: str
    doc_type: str | None = None
    period: str | None = None


@dataclass(frozen=True)
class ForwardSignal:
    signal_id: str
    source_type: str
    metric: str
    direction: str
    value: float
    unit: str
    confidence: float
    as_of: str | None
    evidence: tuple[ForwardSignalEvidence, ...]


@dataclass(frozen=True)
class ForwardSignalDecision:
    signal_id: str
    metric: str
    accepted: bool
    reason: str
    effective_bps: float
    risk_tag: str | None


@dataclass(frozen=True)
class ForwardSignalPolicyResult:
    total_count: int
    accepted_count: int
    rejected_count: int
    evidence_count: int
    growth_adjustment: float
    margin_adjustment: float
    growth_adjustment_bps: float
    margin_adjustment_bps: float
    risk_level: Literal["low", "medium", "high"]
    source_types: tuple[str, ...]
    decisions: tuple[ForwardSignalDecision, ...]

    def to_summary(self) -> dict[str, object]:
        return {
            "signals_total": self.total_count,
            "signals_accepted": self.accepted_count,
            "signals_rejected": self.rejected_count,
            "evidence_count": self.evidence_count,
            "growth_adjustment_bps": self.growth_adjustment_bps,
            "margin_adjustment_bps": self.margin_adjustment_bps,
            "risk_level": self.risk_level,
            "source_types": list(self.source_types),
            "decisions": [
                {
                    "signal_id": decision.signal_id,
                    "metric": decision.metric,
                    "accepted": decision.accepted,
                    "reason": decision.reason,
                    "effective_bps": decision.effective_bps,
                    "risk_tag": decision.risk_tag,
                }
                for decision in self.decisions
            ],
        }


def resolve_growth_blend_weights(
    historical_volatility: float | None,
) -> GrowthBlendWeights:
    if historical_volatility is None:
        return GrowthBlendWeights(
            historical=BASELINE_HISTORICAL_WEIGHT,
            consensus=BASELINE_CONSENSUS_WEIGHT,
            adjustment=BASELINE_ADJUSTMENT_WEIGHT,
            profile="baseline",
        )
    if historical_volatility < MATURE_VOLATILITY_THRESHOLD:
        return GrowthBlendWeights(
            historical=MATURE_HISTORICAL_WEIGHT,
            consensus=MATURE_CONSENSUS_WEIGHT,
            adjustment=MATURE_ADJUSTMENT_WEIGHT,
            profile="mature_stable",
        )
    return GrowthBlendWeights(
        historical=VOLATILE_HISTORICAL_WEIGHT,
        consensus=VOLATILE_CONSENSUS_WEIGHT,
        adjustment=VOLATILE_ADJUSTMENT_WEIGHT,
        profile="volatile_or_cyclical",
    )


def blend_growth_rate(
    *,
    historical_growth: float | None,
    consensus_growth: float | None,
    adjustment_growth: float | None = None,
    historical_volatility: float | None = None,
) -> GrowthBlendResult | None:
    weights = resolve_growth_blend_weights(historical_volatility)

    weighted_components: list[tuple[float, float, str]] = []
    if historical_growth is not None:
        weighted_components.append(
            (historical_growth, weights.historical, "historical")
        )
    if consensus_growth is not None:
        weighted_components.append((consensus_growth, weights.consensus, "consensus"))
    if adjustment_growth is not None:
        weighted_components.append(
            (adjustment_growth, weights.adjustment, "adjustment")
        )

    if not weighted_components:
        return None

    total_weight = sum(item[1] for item in weighted_components)
    blended = sum(value * weight for value, weight, _ in weighted_components) / (
        total_weight if total_weight > 0 else 1.0
    )

    components = ", ".join(name for _, _, name in weighted_components)
    rationale = (
        f"Context-aware growth blend ({weights.profile}); components={components}; "
        f"weights(historical={weights.historical:.2f}, "
        f"consensus={weights.consensus:.2f}, adjustment={weights.adjustment:.2f})"
    )
    return GrowthBlendResult(
        blended_growth=blended,
        weights=weights,
        rationale=rationale,
    )


def project_growth_rate_series(
    *,
    base_growth: float,
    projection_years: int,
    long_run_target: float = DEFAULT_LONG_RUN_GROWTH_TARGET,
    high_growth_trigger: float = DEFAULT_HIGH_GROWTH_TRIGGER,
) -> list[float]:
    if projection_years <= 0:
        raise ValueError("projection_years must be positive")

    if base_growth <= high_growth_trigger:
        return [base_growth] * projection_years

    if projection_years == 1:
        return [max(long_run_target, base_growth)]

    step = (base_growth - long_run_target) / float(projection_years - 1)
    series: list[float] = []
    for idx in range(projection_years):
        value = base_growth - (step * idx)
        series.append(max(long_run_target, value))
    return series


def assume_rate(name: str, value: float, description: str) -> TraceableField[float]:
    return TraceableField(
        name=name,
        value=value,
        provenance=ManualProvenance(
            description=description,
            author="PolicyDefault",
            modified_at=str(datetime.now()),
        ),
    )


def assume_rate_series(
    name: str, value: float, count: int, description: str
) -> TraceableField[list[float]]:
    return TraceableField(
        name=name,
        value=[value] * count,
        provenance=ManualProvenance(
            description=description,
            author="PolicyDefault",
            modified_at=str(datetime.now()),
        ),
    )


def parse_forward_signals(raw: object) -> tuple[ForwardSignal, ...]:
    if not isinstance(raw, list | tuple):
        return ()

    parsed: list[ForwardSignal] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            continue
        signal = _parse_forward_signal(item, index=index)
        if signal is not None:
            parsed.append(signal)
    return tuple(parsed)


def apply_forward_signal_policy(
    signals: tuple[ForwardSignal, ...],
    *,
    confidence_threshold: float = DEFAULT_FORWARD_SIGNAL_CONFIDENCE_THRESHOLD,
    max_adjustment_bps: float = DEFAULT_FORWARD_SIGNAL_MAX_ADJUSTMENT_BPS,
) -> ForwardSignalPolicyResult:
    decisions: list[ForwardSignalDecision] = []
    weighted_bps: dict[str, float] = {"growth_outlook": 0.0, "margin_outlook": 0.0}
    weights: dict[str, float] = {"growth_outlook": 0.0, "margin_outlook": 0.0}
    evidence_count = 0

    for signal in signals:
        evidence_count += len(signal.evidence)
        metric = signal.metric
        if metric not in {"growth_outlook", "margin_outlook"}:
            decisions.append(
                ForwardSignalDecision(
                    signal_id=signal.signal_id,
                    metric=metric,
                    accepted=False,
                    reason="unsupported_metric_for_v1",
                    effective_bps=0.0,
                    risk_tag=None,
                )
            )
            continue

        if len(signal.evidence) == 0:
            decisions.append(
                ForwardSignalDecision(
                    signal_id=signal.signal_id,
                    metric=metric,
                    accepted=False,
                    reason="missing_evidence",
                    effective_bps=0.0,
                    risk_tag="high_risk",
                )
            )
            continue

        signed_bps = _signed_signal_bps(signal)
        confidence = _clamp(signal.confidence, 0.0, 1.0)
        risk_tag: str | None = None
        weight = confidence
        if confidence < confidence_threshold:
            risk_tag = "low_confidence"
            weight = confidence * 0.25

        if weight <= 0.0:
            decisions.append(
                ForwardSignalDecision(
                    signal_id=signal.signal_id,
                    metric=metric,
                    accepted=False,
                    reason="zero_weight_after_policy",
                    effective_bps=0.0,
                    risk_tag=risk_tag,
                )
            )
            continue

        weighted_bps[metric] += signed_bps * weight
        weights[metric] += weight
        decisions.append(
            ForwardSignalDecision(
                signal_id=signal.signal_id,
                metric=metric,
                accepted=True,
                reason="accepted",
                effective_bps=signed_bps,
                risk_tag=risk_tag,
            )
        )

    growth_bps = 0.0
    margin_bps = 0.0
    if weights["growth_outlook"] > 0.0:
        growth_bps = weighted_bps["growth_outlook"] / weights["growth_outlook"]
    if weights["margin_outlook"] > 0.0:
        margin_bps = weighted_bps["margin_outlook"] / weights["margin_outlook"]

    growth_bps = _clamp(growth_bps, -max_adjustment_bps, max_adjustment_bps)
    margin_bps = _clamp(margin_bps, -max_adjustment_bps, max_adjustment_bps)

    accepted_count = sum(1 for item in decisions if item.accepted)
    rejected_count = len(decisions) - accepted_count
    has_low_confidence = any(
        item.accepted and item.risk_tag == "low_confidence" for item in decisions
    )
    source_types = tuple(
        sorted({signal.source_type for signal in signals if signal.source_type})
    )
    if len(decisions) == 0:
        risk_level: Literal["low", "medium", "high"] = "low"
    elif has_low_confidence:
        risk_level = "high"
    elif rejected_count > 0:
        risk_level = "medium"
    else:
        risk_level = "low"

    return ForwardSignalPolicyResult(
        total_count=len(decisions),
        accepted_count=accepted_count,
        rejected_count=rejected_count,
        evidence_count=evidence_count,
        growth_adjustment=growth_bps / 10_000.0,
        margin_adjustment=margin_bps / 10_000.0,
        growth_adjustment_bps=growth_bps,
        margin_adjustment_bps=margin_bps,
        risk_level=risk_level,
        source_types=source_types,
        decisions=tuple(decisions),
    )


def _parse_forward_signal(
    raw: Mapping[str, object], *, index: int
) -> ForwardSignal | None:
    signal_id_raw = raw.get("signal_id")
    signal_id = (
        signal_id_raw
        if isinstance(signal_id_raw, str) and signal_id_raw
        else f"signal_{index + 1}"
    )

    source_type = _normalize_text(raw.get("source_type"))
    metric = _normalize_text(raw.get("metric"))
    direction = _normalize_text(raw.get("direction"))
    unit = _normalize_text(raw.get("unit"), default="bps")
    confidence = _to_float(raw.get("confidence"))
    value = _to_float(raw.get("value"))

    if source_type not in SUPPORTED_FORWARD_SIGNAL_SOURCES:
        return None
    if metric not in SUPPORTED_FORWARD_SIGNAL_METRICS:
        return None
    if direction not in SUPPORTED_FORWARD_SIGNAL_DIRECTIONS:
        return None
    if unit not in SUPPORTED_FORWARD_SIGNAL_UNITS:
        return None
    if confidence is None or value is None:
        return None

    as_of_raw = raw.get("as_of")
    as_of = as_of_raw if isinstance(as_of_raw, str) and as_of_raw else None
    evidence_raw = raw.get("evidence")
    evidence = _parse_forward_signal_evidence(evidence_raw)
    return ForwardSignal(
        signal_id=signal_id,
        source_type=source_type,
        metric=metric,
        direction=direction,
        value=value,
        unit=unit,
        confidence=confidence,
        as_of=as_of,
        evidence=evidence,
    )


def _parse_forward_signal_evidence(raw: object) -> tuple[ForwardSignalEvidence, ...]:
    if not isinstance(raw, list | tuple):
        return ()
    items: list[ForwardSignalEvidence] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        snippet_raw = item.get("text_snippet")
        source_url_raw = item.get("source_url")
        if not isinstance(snippet_raw, str) or not snippet_raw.strip():
            continue
        if not isinstance(source_url_raw, str) or not source_url_raw.strip():
            continue
        doc_type_raw = item.get("doc_type")
        period_raw = item.get("period")
        doc_type = (
            doc_type_raw if isinstance(doc_type_raw, str) and doc_type_raw else None
        )
        period = period_raw if isinstance(period_raw, str) and period_raw else None
        items.append(
            ForwardSignalEvidence(
                text_snippet=snippet_raw.strip(),
                source_url=source_url_raw.strip(),
                doc_type=doc_type,
                period=period,
            )
        )
    return tuple(items)


def _normalize_text(value: object, *, default: str | None = None) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized:
            return normalized
    return default or ""


def _to_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _signed_signal_bps(signal: ForwardSignal) -> float:
    raw_bps = signal.value * 10_000.0 if signal.unit == "ratio" else signal.value
    magnitude = abs(raw_bps)
    if signal.direction == "down":
        return -magnitude
    if signal.direction == "neutral":
        return 0.0
    return magnitude
