from __future__ import annotations

from datetime import date

from .pipeline_text_normalization_service import (
    _normalize_accession_number,
    _normalize_cik,
)

_SEC_SEARCH_URL_TEMPLATE = "https://www.sec.gov/edgar/search/#/entityName={ticker}"
_SEC_ARCHIVES_INDEX_URL_TEMPLATE = (
    "https://www.sec.gov/Archives/edgar/data/"
    "{cik}/{accession_no_dash}/{accession}-index.html"
)
_SIGNAL_STALE_WARNING_DAYS = 540
_SIGNAL_STALE_HIGH_RISK_DAYS = 900


def _filing_age_days(filing_date: str | None) -> int | None:
    if not isinstance(filing_date, str) or not filing_date:
        return None
    try:
        filing_day = date.fromisoformat(filing_date[:10])
    except ValueError:
        return None
    delta_days = (date.today() - filing_day).days
    if delta_days < 0:
        return 0
    return delta_days


def _staleness_confidence_penalty(filing_age_days: int | None) -> float:
    if filing_age_days is None:
        return 0.0
    if filing_age_days > _SIGNAL_STALE_HIGH_RISK_DAYS:
        return 0.10
    if filing_age_days > _SIGNAL_STALE_WARNING_DAYS:
        return 0.05
    return 0.0


def _build_doc_type(form: str, *, used_focus: bool) -> str:
    if used_focus:
        return f"{form}_focused"
    return form


def _build_sec_source_url(
    *,
    ticker: str,
    accession_number: str | None,
    cik: str | None,
) -> str:
    filing_url = _build_sec_filing_index_url(
        accession_number=accession_number,
        cik=cik,
    )
    if filing_url is not None:
        return filing_url
    return _SEC_SEARCH_URL_TEMPLATE.format(ticker=ticker)


def _build_sec_filing_index_url(
    *,
    accession_number: str | None,
    cik: str | None,
) -> str | None:
    normalized_accession = _normalize_accession_number(accession_number)
    if normalized_accession is None:
        return None
    accession_no_dash = normalized_accession.replace("-", "")
    if not accession_no_dash.isdigit():
        return None
    cik_digits = _normalize_cik(cik)
    if cik_digits is None:
        cik_digits = normalized_accession.split("-", maxsplit=1)[0]
    cik_path = cik_digits.lstrip("0")
    if not cik_path:
        return None
    return _SEC_ARCHIVES_INDEX_URL_TEMPLATE.format(
        cik=cik_path,
        accession_no_dash=accession_no_dash,
        accession=normalized_accession,
    )
