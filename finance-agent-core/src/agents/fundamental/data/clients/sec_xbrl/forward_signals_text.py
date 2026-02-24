from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from edgar import Company

from src.shared.kernel.tools.logger import get_logger, log_event

logger = get_logger(__name__)

_SEC_SEARCH_URL_TEMPLATE = "https://www.sec.gov/edgar/search/#/entityName={ticker}"
_TEXT_MAX_CHARS = 120_000

_FORM_SOURCE_TYPE: dict[str, str] = {
    "10-K": "mda",
    "10-Q": "mda",
    "8-K": "press_release",
}

_SIGNAL_PATTERNS: dict[str, dict[str, tuple[str, ...]]] = {
    "growth_outlook": {
        "up": (
            "raised guidance",
            "increase guidance",
            "strong demand",
            "accelerating growth",
            "record backlog",
            "expect higher revenue",
        ),
        "down": (
            "lowered guidance",
            "decelerating growth",
            "soft demand",
            "declining demand",
            "revenue headwind",
            "expect lower revenue",
        ),
    },
    "margin_outlook": {
        "up": (
            "margin expansion",
            "operating leverage",
            "cost discipline",
            "pricing power",
            "improved margin",
        ),
        "down": (
            "margin pressure",
            "cost inflation",
            "higher input costs",
            "margin compression",
            "weaker margin",
        ),
    },
}

_SOURCE_WEIGHT: dict[str, float] = {"mda": 1.0, "press_release": 0.75}
_SIGNAL_MIN_SCORE = 1.0


@dataclass(frozen=True)
class FilingTextRecord:
    form: str
    source_type: str
    text: str
    focus_text: str | None = None
    period: str | None = None
    accession_number: str | None = None
    filing_date: str | None = None


@dataclass(frozen=True)
class _MetricSignalAccumulator:
    up_score: float
    down_score: float
    evidence: list[dict[str, object]]


def extract_forward_signals_from_sec_text(
    *,
    ticker: str,
    max_filings_per_form: int = 2,
    fetch_records_fn: Callable[[str, int], list[FilingTextRecord]] | None = None,
) -> list[dict[str, object]]:
    fetch_fn = fetch_records_fn or _fetch_recent_filing_text_records
    records = fetch_fn(ticker, max_filings_per_form)
    if not records:
        return []

    grouped = _group_records_for_signals(ticker=ticker, records=records)
    focus_diag = _summarize_focus_usage(records)
    signals: list[dict[str, object]] = []
    for source_type, metrics in grouped.items():
        for metric, acc in metrics.items():
            score = acc.up_score - acc.down_score
            if abs(score) < _SIGNAL_MIN_SCORE:
                continue
            direction = "up" if score > 0 else "down"
            value_bps = _clamp(abs(score) * 35.0, 25.0, 200.0)
            confidence = _clamp(0.56 + min(abs(score), 6.0) * 0.03, 0.56, 0.80)
            evidence = acc.evidence[:3]
            if not evidence:
                continue
            signal_id = (
                f"sec_text_{source_type}_{metric}_"
                f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
            )
            signals.append(
                {
                    "signal_id": signal_id,
                    "source_type": source_type,
                    "metric": metric,
                    "direction": direction,
                    "value": round(value_bps, 2),
                    "unit": "bps",
                    "confidence": round(confidence, 4),
                    "as_of": datetime.now(UTC).isoformat(),
                    "evidence": evidence,
                }
            )

    if signals:
        emitted_doc_types = sorted(
            {
                str(evidence.get("doc_type"))
                for signal in signals
                for evidence in signal.get("evidence", [])
                if isinstance(evidence, dict)
                and isinstance(evidence.get("doc_type"), str)
                and evidence.get("doc_type")
            }
        )
        log_event(
            logger,
            event="fundamental_forward_signal_text_producer_completed",
            message="forward signal text producer generated signals",
            fields={
                "ticker": ticker,
                "records_total": focus_diag["records_total"],
                "focused_records_total": focus_diag["focused_records_total"],
                "fallback_records_total": focus_diag["fallback_records_total"],
                "focused_form_counts": focus_diag["focused_form_counts"],
                "fallback_form_counts": focus_diag["fallback_form_counts"],
                "signal_count": len(signals),
                "source_types": sorted(
                    {str(item.get("source_type")) for item in signals}
                ),
                "metrics": sorted({str(item.get("metric")) for item in signals}),
                "emitted_doc_types": emitted_doc_types,
            },
        )
    else:
        log_event(
            logger,
            event="fundamental_forward_signal_text_producer_no_signal",
            message="forward signal text producer found no eligible signals",
            fields={
                "ticker": ticker,
                "records_total": focus_diag["records_total"],
                "focused_records_total": focus_diag["focused_records_total"],
                "fallback_records_total": focus_diag["fallback_records_total"],
                "focused_form_counts": focus_diag["focused_form_counts"],
                "fallback_form_counts": focus_diag["fallback_form_counts"],
            },
        )
    return signals


def _fetch_recent_filing_text_records(
    ticker: str,
    max_filings_per_form: int,
) -> list[FilingTextRecord]:
    company = Company(ticker)
    current_year = date.today().year
    years = [current_year - offset for offset in range(3)]

    records: list[FilingTextRecord] = []
    for form, source_type in _FORM_SOURCE_TYPE.items():
        try:
            filings = company.get_filings(
                form=form,
                year=years,
                amendments=False,
                trigger_full_load=False,
            )
            if filings is None:
                continue
            subset = filings.head(max_filings_per_form)
        except Exception as exc:
            log_event(
                logger,
                event="fundamental_forward_signal_text_form_failed",
                message="failed to fetch sec text filings for form",
                fields={
                    "ticker": ticker,
                    "form": form,
                    "exception": str(exc),
                },
            )
            continue
        for idx in range(max_filings_per_form):
            filing = _safe_get_filing(subset, idx)
            if filing is None:
                break
            text = _safe_get_filing_text(filing)
            if not text:
                continue
            records.append(
                FilingTextRecord(
                    form=form,
                    source_type=source_type,
                    text=text,
                    focus_text=_extract_focus_text(form=form, text=text),
                    period=_normalize_text(getattr(filing, "period_of_report", None)),
                    accession_number=_normalize_text(
                        getattr(filing, "accession_number", None)
                    ),
                    filing_date=_normalize_text(getattr(filing, "filing_date", None)),
                )
            )
    return records


def _group_records_for_signals(
    *,
    ticker: str,
    records: list[FilingTextRecord],
) -> dict[str, dict[str, _MetricSignalAccumulator]]:
    grouped: dict[str, dict[str, _MetricSignalAccumulator]] = {}
    for record in records:
        focused_section = record.focus_text or _extract_focus_text(
            form=record.form, text=record.text
        )
        analysis_text = focused_section or record.text
        doc_type = _build_doc_type(record.form, used_focus=focused_section is not None)
        for metric, patterns in _SIGNAL_PATTERNS.items():
            up_hits = _find_pattern_hits(analysis_text, patterns["up"])
            down_hits = _find_pattern_hits(analysis_text, patterns["down"])
            if not up_hits and not down_hits:
                continue

            source_bucket = grouped.setdefault(record.source_type, {})
            existing = source_bucket.get(metric)
            if existing is None:
                existing = _MetricSignalAccumulator(
                    up_score=0.0,
                    down_score=0.0,
                    evidence=[],
                )

            weight = _SOURCE_WEIGHT.get(record.source_type, 1.0)
            up_score = existing.up_score + (len(up_hits) * weight)
            down_score = existing.down_score + (len(down_hits) * weight)
            evidence = list(existing.evidence)

            for _keyword, start, end in up_hits + down_hits:
                snippet = _extract_snippet(analysis_text, start, end)
                if not snippet:
                    continue
                evidence.append(
                    {
                        "text_snippet": snippet,
                        "source_url": _SEC_SEARCH_URL_TEMPLATE.format(ticker=ticker),
                        "doc_type": doc_type,
                        "period": record.period or "N/A",
                    }
                )
                if len(evidence) >= 5:
                    break

            source_bucket[metric] = _MetricSignalAccumulator(
                up_score=up_score,
                down_score=down_score,
                evidence=evidence,
            )
    return grouped


def _summarize_focus_usage(records: list[FilingTextRecord]) -> dict[str, object]:
    focused_form_counter: Counter[str] = Counter()
    fallback_form_counter: Counter[str] = Counter()
    for record in records:
        if _record_used_focus(record):
            focused_form_counter[record.form] += 1
        else:
            fallback_form_counter[record.form] += 1
    focused_records_total = sum(focused_form_counter.values())
    fallback_records_total = sum(fallback_form_counter.values())
    return {
        "records_total": len(records),
        "focused_records_total": focused_records_total,
        "fallback_records_total": fallback_records_total,
        "focused_form_counts": dict(focused_form_counter),
        "fallback_form_counts": dict(fallback_form_counter),
    }


def _record_used_focus(record: FilingTextRecord) -> bool:
    if isinstance(record.focus_text, str) and record.focus_text:
        return True
    inferred_focus = _extract_focus_text(form=record.form, text=record.text)
    return isinstance(inferred_focus, str) and bool(inferred_focus)


def _find_pattern_hits(
    text: str, patterns: tuple[str, ...]
) -> list[tuple[str, int, int]]:
    normalized = text.lower()
    hits: list[tuple[str, int, int]] = []
    for pattern in patterns:
        compiled = re.compile(rf"\b{re.escape(pattern.lower())}\b")
        match_count = 0
        for match in compiled.finditer(normalized):
            hits.append((pattern, match.start(), match.end()))
            match_count += 1
            if match_count >= 2:
                break
    return hits


def _extract_snippet(text: str, start: int, end: int, radius: int = 70) -> str | None:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = " ".join(text[left:right].split())
    if not snippet:
        return None
    if len(snippet) > 220:
        return snippet[:217] + "..."
    return snippet


def _extract_focus_text(*, form: str, text: str) -> str | None:
    normalized_form = form.strip().upper()
    if normalized_form == "10-K":
        return _extract_between_markers(
            text,
            start_patterns=(
                r"item\s+7\s*[\.\-:]*\s*management[’']?s discussion and analysis",
                r"management[’']?s discussion and analysis of financial condition and results of operations",
            ),
            end_patterns=(r"item\s+7a", r"item\s+8"),
            min_len=120,
        )
    if normalized_form == "10-Q":
        return _extract_between_markers(
            text,
            start_patterns=(
                r"item\s+2\s*[\.\-:]*\s*management[’']?s discussion and analysis",
                r"management[’']?s discussion and analysis of financial condition and results of operations",
            ),
            end_patterns=(r"item\s+3", r"item\s+4"),
            min_len=100,
        )
    if normalized_form == "8-K":
        # Prefer earnings-release related sections when present.
        return _extract_between_markers(
            text,
            start_patterns=(r"item\s+2\.02", r"item\s+7\.01"),
            end_patterns=(r"item\s+\d+\.\d+",),
            min_len=120,
        )
    return None


def _extract_between_markers(
    text: str,
    *,
    start_patterns: tuple[str, ...],
    end_patterns: tuple[str, ...],
    min_len: int,
) -> str | None:
    if not text:
        return None

    start_idx: int | None = None
    for pattern in start_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match is None:
            continue
        idx = match.start()
        if start_idx is None or idx < start_idx:
            start_idx = idx

    if start_idx is None:
        return None

    end_idx: int | None = None
    search_from = start_idx + 20
    tail = text[search_from:]
    for pattern in end_patterns:
        match = re.search(pattern, tail, flags=re.IGNORECASE)
        if match is None:
            continue
        idx = search_from + match.start()
        if end_idx is None or idx < end_idx:
            end_idx = idx

    section = text[start_idx:end_idx] if end_idx is not None else text[start_idx:]
    normalized = " ".join(section.split())
    if len(normalized) < min_len:
        return None
    return normalized


def _build_doc_type(form: str, *, used_focus: bool) -> str:
    if used_focus:
        return f"{form}_focused"
    return form


def _safe_get_filing(filings: object, index: int) -> object | None:
    try:
        getter = getattr(filings, "get", None)
        if callable(getter):
            return getter(index)
    except Exception:
        return None
    return None


def _safe_get_filing_text(filing: object) -> str | None:
    try:
        text_fn = getattr(filing, "text", None)
        if callable(text_fn):
            text = text_fn()
            normalized = _normalize_text(text)
            if normalized:
                return normalized[:_TEXT_MAX_CHARS]
        full_text_fn = getattr(filing, "full_text_submission", None)
        if callable(full_text_fn):
            full_text = full_text_fn()
            normalized_full_text = _normalize_text(full_text)
            if normalized_full_text:
                return normalized_full_text[:_TEXT_MAX_CHARS]
    except Exception:
        return None
    return None


def _normalize_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized if normalized else None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
