"""SEC XBRL extraction, mapping, and forward-signal producer package."""

from .provider import (
    extract_forward_signals_from_sec_text,
    extract_forward_signals_from_xbrl_reports,
    fetch_financial_payload,
)

__all__ = [
    "fetch_financial_payload",
    "extract_forward_signals_from_xbrl_reports",
    "extract_forward_signals_from_sec_text",
]
