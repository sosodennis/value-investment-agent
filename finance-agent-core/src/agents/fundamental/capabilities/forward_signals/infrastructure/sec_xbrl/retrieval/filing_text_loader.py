from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeVar

TRecord = TypeVar("TRecord")


class _CompanyLike(Protocol):
    cik: object

    def get_filings(
        self,
        *,
        form: str,
        year: list[int],
        amendments: bool,
        trigger_full_load: bool,
    ) -> object: ...


class _CompanyFactoryFn(Protocol):
    def __call__(self, ticker: str) -> _CompanyLike: ...


class _CallWithSecRetryFn(Protocol):
    def __call__(
        self,
        *,
        operation: str,
        ticker: str,
        execute: Callable[[], object],
    ) -> object: ...


class _NormalizeTextFn(Protocol):
    def __call__(self, value: object) -> str | None: ...


class _NormalizeCikFn(Protocol):
    def __call__(self, value: object) -> str | None: ...


class _SafeGetFilingFn(Protocol):
    def __call__(self, filings: object, index: int) -> object | None: ...


class _SafeGetFilingTextFn(Protocol):
    def __call__(self, filing: object) -> str | None: ...


class _ExtractFocusTextWithStrategyFromFilingFn(Protocol):
    def __call__(
        self, *, form: str, filing: object
    ) -> tuple[str | None, str | None]: ...


class _ExtractFocusTextFn(Protocol):
    def __call__(self, *, form: str, text: str) -> str | None: ...


class _RecordFactoryFn(Protocol[TRecord]):
    def __call__(
        self,
        *,
        form: str,
        source_type: str,
        text: str,
        focus_text: str | None,
        period: str | None,
        accession_number: str | None,
        filing_date: str | None,
        cik: str | None,
        focus_strategy: str | None,
    ) -> TRecord: ...


class _LogEventFn(Protocol):
    def __call__(
        self,
        logger: object,
        *,
        event: str,
        message: str,
        fields: dict[str, object],
    ) -> None: ...


def _load_recent_filing_text_records(
    *,
    ticker: str,
    max_filings_per_form: int,
    form_source_type: dict[str, str],
    current_year: int,
    call_with_sec_retry_fn: _CallWithSecRetryFn,
    company_factory_fn: _CompanyFactoryFn,
    normalize_text_fn: _NormalizeTextFn,
    normalize_cik_fn: _NormalizeCikFn,
    safe_get_filing_fn: _SafeGetFilingFn,
    safe_get_filing_text_fn: _SafeGetFilingTextFn,
    extract_focus_text_with_strategy_from_filing_fn: (
        _ExtractFocusTextWithStrategyFromFilingFn
    ),
    extract_focus_text_fn: _ExtractFocusTextFn,
    record_factory_fn: _RecordFactoryFn[TRecord],
    log_event_fn: _LogEventFn,
    logger: object,
) -> list[TRecord]:
    company = call_with_sec_retry_fn(
        operation="company_init",
        ticker=ticker,
        execute=lambda: company_factory_fn(ticker),
    )
    company_cik = normalize_cik_fn(getattr(company, "cik", None))
    years = [current_year - offset for offset in range(3)]

    records: list[TRecord] = []
    for form, source_type in form_source_type.items():
        current_form = form
        try:
            filings = call_with_sec_retry_fn(
                operation=f"get_filings_{current_form}",
                ticker=ticker,
                execute=lambda form=current_form: company.get_filings(
                    form=form,
                    year=years,
                    amendments=False,
                    trigger_full_load=False,
                ),
            )
            if filings is None:
                continue
            subset = getattr(filings, "head", None)
            if not callable(subset):
                continue
            filing_subset = subset(max_filings_per_form)
        except Exception as exc:
            log_event_fn(
                logger,
                event="fundamental_forward_signal_text_form_failed",
                message="failed to fetch sec text filings for form",
                fields={
                    "ticker": ticker,
                    "form": current_form,
                    "exception": str(exc),
                },
            )
            continue

        for idx in range(max_filings_per_form):
            filing = safe_get_filing_fn(filing_subset, idx)
            if filing is None:
                break
            text = safe_get_filing_text_fn(filing)
            if not text:
                continue
            focus_text, focus_strategy = (
                extract_focus_text_with_strategy_from_filing_fn(
                    form=form,
                    filing=filing,
                )
            )
            if focus_text is None:
                focus_text = extract_focus_text_fn(form=form, text=text)
                if focus_text is not None:
                    focus_strategy = "regex_marker"
            records.append(
                record_factory_fn(
                    form=form,
                    source_type=source_type,
                    text=text,
                    focus_text=focus_text,
                    period=normalize_text_fn(getattr(filing, "period_of_report", None)),
                    accession_number=normalize_text_fn(
                        getattr(filing, "accession_number", None)
                    ),
                    filing_date=normalize_text_fn(getattr(filing, "filing_date", None)),
                    cik=normalize_cik_fn(getattr(filing, "cik", None)) or company_cik,
                    focus_strategy=focus_strategy,
                )
            )
    return records
