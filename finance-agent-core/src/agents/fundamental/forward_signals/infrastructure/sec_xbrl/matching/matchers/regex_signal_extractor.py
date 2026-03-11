from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from ..rules.signal_pattern_catalog import MetricPatternSet

_NEGATION_PATTERN = re.compile(
    r"\b(?:no|not|never|without|lack of|did not|does not|can't|cannot|unlikely)\b",
    re.IGNORECASE,
)
_FORWARD_TENSE_PATTERN = re.compile(
    r"\b(?:will|expects?|expecting|guidance|outlook|forecast|project(?:s|ed)?|"
    r"anticipat(?:e|es|ed)|target(?:s|ed)?)\b",
    re.IGNORECASE,
)
_HISTORICAL_TENSE_PATTERN = re.compile(
    r"\b(?:last year|prior year|previous quarter|for the year ended|was|were|had been)\b",
    re.IGNORECASE,
)
_NUMERIC_GUIDANCE_PATTERN = re.compile(
    r"\b(?P<direction>raise(?:d)?|increase(?:d)?|lower(?:ed)?|decrease(?:d)?|"
    r"reduc(?:e|ed)|improv(?:e|ed)|expand(?:ed)?|compress(?:ed)?)"
    r"[^.]{0,80}?\b(?:guidance|outlook|revenue|sales|growth|margin|operating margin)\b"
    r"[^.]{0,40}?\b(?:by|to)\s+(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>%|percent|percentage points?|bps|basis points?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PatternHit:
    pattern: str
    start: int
    end: int
    weighted_score: float
    is_forward: bool
    is_historical: bool
    rule: str = "lexical_pattern"


@dataclass(frozen=True)
class NumericGuidanceHit:
    direction: str
    start: int
    end: int
    value_basis_points: float
    score: float


@dataclass(frozen=True)
class MetricRegexHits:
    up_hits: list[PatternHit]
    down_hits: list[PatternHit]
    numeric_hits: list[NumericGuidanceHit]


def has_forward_tense_cue(text: str) -> bool:
    return _FORWARD_TENSE_PATTERN.search(text) is not None


def contains_numeric_guidance_cue(text: str) -> bool:
    return _NUMERIC_GUIDANCE_PATTERN.search(text) is not None


def extract_metric_regex_hits(
    *,
    analysis_text: str,
    metric_text: str,
    metric: str,
    patterns: MetricPatternSet,
) -> MetricRegexHits:
    return MetricRegexHits(
        up_hits=find_pattern_hits(metric_text, patterns.up),
        down_hits=find_pattern_hits(metric_text, patterns.down),
        numeric_hits=find_numeric_guidance_hits(
            analysis_text=analysis_text,
            metric=metric,
        ),
    )


def find_pattern_hits(text: str, patterns: tuple[str, ...]) -> list[PatternHit]:
    normalized = text.lower()
    hits: list[PatternHit] = []
    for pattern in patterns:
        compiled = _compile_phrase_pattern(pattern.lower())
        match_count = 0
        for match in compiled.finditer(normalized):
            context_left = max(0, match.start() - 70)
            context_right = min(len(normalized), match.end() + 90)
            context = normalized[context_left:context_right]
            if _NEGATION_PATTERN.search(context):
                continue
            is_forward = _FORWARD_TENSE_PATTERN.search(context) is not None
            is_historical = _HISTORICAL_TENSE_PATTERN.search(context) is not None
            weighted_score = 1.0
            if is_forward:
                weighted_score *= 1.2
            if is_historical and not is_forward:
                weighted_score *= 0.7
            hits.append(
                PatternHit(
                    pattern=pattern,
                    start=match.start(),
                    end=match.end(),
                    weighted_score=weighted_score,
                    is_forward=is_forward,
                    is_historical=is_historical,
                )
            )
            match_count += 1
            if match_count >= 2:
                break
    return hits


def find_numeric_guidance_hits(
    *,
    analysis_text: str,
    metric: str,
) -> list[NumericGuidanceHit]:
    text_lower = analysis_text.lower()
    hits: list[NumericGuidanceHit] = []
    for match in _NUMERIC_GUIDANCE_PATTERN.finditer(text_lower):
        snippet = text_lower[match.start() : match.end()]
        if metric == "growth_outlook" and not any(
            token in snippet for token in ("revenue", "sales", "growth", "guidance")
        ):
            continue
        if metric == "margin_outlook" and "margin" not in snippet:
            continue
        direction = _normalize_guidance_direction(match.group("direction"))
        value_basis_points = _parse_numeric_guidance_value(
            value_text=match.group("value"),
            unit_text=match.group("unit"),
        )
        if value_basis_points <= 0:
            continue
        score = _clamp(value_basis_points / 85.0, 0.5, 3.5)
        hits.append(
            NumericGuidanceHit(
                direction=direction,
                start=match.start(),
                end=match.end(),
                value_basis_points=value_basis_points,
                score=score,
            )
        )
    return hits[:3]


@lru_cache(maxsize=256)
def _compile_phrase_pattern(phrase: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(phrase)}\b")


def _normalize_guidance_direction(direction_text: str) -> str:
    normalized = direction_text.lower()
    if normalized.startswith(("raise", "increase", "improv", "expand")):
        return "up"
    return "down"


def _parse_numeric_guidance_value(*, value_text: str, unit_text: str) -> float:
    try:
        value = float(value_text)
    except ValueError:
        return 0.0
    unit = unit_text.lower().strip()
    if unit in {"%", "percent", "percentage point", "percentage points"}:
        return value * 100.0
    return value


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
