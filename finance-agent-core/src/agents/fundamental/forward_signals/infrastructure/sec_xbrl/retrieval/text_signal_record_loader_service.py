from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date

from edgar import Company

from src.agents.fundamental.financial_statements.infrastructure.sec_xbrl.fetch.filing_fetcher import (
    call_with_sec_retry,
)
from src.shared.kernel.tools.logger import log_event

from . import focus_text_extractor as _focus_text_extractor
from .filing_text_loader import _load_recent_filing_text_records
from .pipeline_filing_access_service import _safe_get_filing, _safe_get_filing_text
from .pipeline_text_normalization_service import _normalize_cik, _normalize_text
from .text_record import FilingTextRecord


def load_sec_text_records(
    *,
    ticker: str,
    max_filings_per_form: int,
    form_source_type: dict[str, str],
    fetch_records_fn: Callable[[str, int], list[FilingTextRecord]] | None,
    logger_: logging.Logger,
) -> list[FilingTextRecord]:
    if fetch_records_fn is not None:
        return fetch_records_fn(ticker, max_filings_per_form)
    return _load_recent_filing_text_records(
        ticker=ticker,
        max_filings_per_form=max_filings_per_form,
        form_source_type=form_source_type,
        current_year=date.today().year,
        call_with_sec_retry_fn=call_with_sec_retry,
        company_factory_fn=Company,
        normalize_text_fn=_normalize_text,
        normalize_cik_fn=_normalize_cik,
        safe_get_filing_fn=_safe_get_filing,
        safe_get_filing_text_fn=_safe_get_filing_text,
        extract_focus_text_with_strategy_from_filing_fn=(
            _focus_text_extractor._extract_focus_text_with_strategy_from_filing
        ),
        extract_focus_text_fn=_focus_text_extractor._extract_focus_text,
        record_factory_fn=FilingTextRecord,
        log_event_fn=log_event,
        logger=logger_,
    )
