"""SEC filing forward-signal extraction pipeline."""

from .forward_signals import extract_forward_signals_from_xbrl_reports

__all__ = [
    "extract_forward_signals_from_xbrl_reports",
]
