"""Matcher implementations for SEC text forward-signal extraction."""

from .dependency_signal_matcher import find_metric_dependency_hits
from .lemma_signal_matcher import find_metric_lemma_hits
from .regex_signal_extractor import (
    MetricRegexHits,
    NumericGuidanceHit,
    PatternHit,
    contains_numeric_guidance_cue,
    extract_metric_regex_hits,
    has_forward_tense_cue,
)

__all__ = [
    "PatternHit",
    "NumericGuidanceHit",
    "MetricRegexHits",
    "contains_numeric_guidance_cue",
    "extract_metric_regex_hits",
    "has_forward_tense_cue",
    "find_metric_lemma_hits",
    "find_metric_dependency_hits",
]
