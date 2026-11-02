from __future__ import annotations

from ..extract.financial_payload_service import (
    fetch_financial_reports_payload as _fetch_financial_reports_payload,
)
from ..map.canonical_mapper import to_canonical_financial_reports


def fetch_financial_reports_payload(ticker: str, years: int = 5) -> dict[str, object]:
    """Stable adapter entrypoint for SEC XBRL reports payload."""
    payload = _fetch_financial_reports_payload(ticker=ticker, years=years)
    reports_raw = payload.get("financial_reports")
    diagnostics_raw = payload.get("diagnostics")
    quality_gates_raw = payload.get("quality_gates")
    diagnostics = dict(diagnostics_raw) if isinstance(diagnostics_raw, dict) else None
    quality_gates = (
        dict(quality_gates_raw) if isinstance(quality_gates_raw, dict) else None
    )

    return {
        "financial_reports": to_canonical_financial_reports(reports_raw),
        "diagnostics": diagnostics,
        "quality_gates": quality_gates,
    }


__all__ = [
    "fetch_financial_reports_payload",
]
