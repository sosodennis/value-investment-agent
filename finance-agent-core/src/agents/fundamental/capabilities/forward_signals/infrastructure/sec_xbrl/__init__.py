"""SEC filing forward-signal extraction pipeline."""

from .filtering.fls_filter import build_forward_looking_filter
from .forward_signals import extract_forward_signals_from_xbrl_reports
from .forward_signals_text import extract_forward_signals_from_sec_text
from .matching.matchers.dependency_signal_matcher import warmup_dependency_matcher
from .postprocess.finbert_direction import build_finbert_direction_reviewer

__all__ = [
    "build_finbert_direction_reviewer",
    "build_forward_looking_filter",
    "extract_forward_signals_from_xbrl_reports",
    "extract_forward_signals_from_sec_text",
    "warmup_dependency_matcher",
]
