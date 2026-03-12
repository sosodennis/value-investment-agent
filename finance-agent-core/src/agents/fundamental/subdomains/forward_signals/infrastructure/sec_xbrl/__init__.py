"""SEC filing forward-signal extraction pipeline."""

from .forward_signals import extract_forward_signals_from_xbrl_reports
from .forward_signals_text import extract_forward_signals_from_sec_text

__all__ = [
    "extract_forward_signals_from_xbrl_reports",
    "extract_forward_signals_from_sec_text",
]
