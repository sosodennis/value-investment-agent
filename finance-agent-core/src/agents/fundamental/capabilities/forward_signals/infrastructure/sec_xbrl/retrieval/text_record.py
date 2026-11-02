from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FilingTextRecord:
    form: str
    source_type: str
    text: str
    focus_text: str | None = None
    period: str | None = None
    accession_number: str | None = None
    filing_date: str | None = None
    cik: str | None = None
    focus_strategy: str | None = None
