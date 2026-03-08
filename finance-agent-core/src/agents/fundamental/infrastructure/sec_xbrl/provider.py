from __future__ import annotations

from collections.abc import Callable

from .canonical_mapper import to_canonical_financial_reports
from .financial_payload_service import (
    fetch_financial_payload as _fetch_financial_payload,
)
from .forward_signals import (
    extract_forward_signals_from_xbrl_reports as _extract_forward_signals_from_xbrl_reports,
)
from .forward_signals_text import (
    extract_forward_signals_from_sec_text as _extract_forward_signals_from_sec_text,
)
from .report_contracts import FinancialReport
from .text_record import FilingTextRecord


def extract_forward_signals_from_xbrl_reports(
    *,
    ticker: str,
    reports: list[FinancialReport],
) -> list[dict[str, object]]:
    """Stable adapter entrypoint for XBRL trend-based forward signals."""
    return _extract_forward_signals_from_xbrl_reports(ticker=ticker, reports=reports)


def extract_forward_signals_from_sec_text(
    *,
    ticker: str,
    max_filings_per_form: int = 2,
    fetch_records_fn: Callable[[str, int], list[FilingTextRecord]] | None = None,
    rules_sector: str | None = None,
) -> list[dict[str, object]]:
    """Stable adapter entrypoint for SEC text-based forward signals."""
    return _extract_forward_signals_from_sec_text(
        ticker=ticker,
        max_filings_per_form=max_filings_per_form,
        fetch_records_fn=fetch_records_fn,
        rules_sector=rules_sector,
    )


def fetch_financial_payload(ticker: str, years: int = 5) -> dict[str, object]:
    """Stable adapter entrypoint for SEC XBRL reports plus forward signals."""
    payload = _fetch_financial_payload(ticker=ticker, years=years)
    reports_raw = payload.get("financial_reports")
    forward_signals_raw = payload.get("forward_signals")
    if not isinstance(forward_signals_raw, list):
        forward_signals_raw = None

    return {
        "financial_reports": to_canonical_financial_reports(reports_raw),
        "forward_signals": forward_signals_raw,
    }


__all__ = [
    "fetch_financial_payload",
    "extract_forward_signals_from_xbrl_reports",
    "extract_forward_signals_from_sec_text",
]
