from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import UTC, date, datetime

from edgar import Company
from pydantic import ValidationError

from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject

from . import focus_text_extractor as _focus_text_extractor
from .filing_fetcher import call_with_sec_retry
from .filing_section_selector import is_8k_form, refine_8k_analysis_text
from .filing_text_loader import _load_recent_filing_text_records
from .fls_filter import filter_forward_looking_sentences_with_stats
from .hybrid_retriever import retrieve_relevant_sentences_batch
from .matchers.dependency_signal_matcher import find_metric_dependency_hits
from .matchers.lemma_signal_matcher import find_metric_lemma_hits
from .matchers.regex_signal_extractor import (
    contains_numeric_guidance_cue,
    extract_metric_regex_hits,
    has_forward_tense_cue,
)
from .pipeline_helpers import (
    _append_unique_evidence,
    _as_float,
    _as_int,
    _build_doc_type,
    _build_sec_source_url,
    _clamp,
    _extract_snippet,
    _filing_age_days,
    _normalize_cik,
    _normalize_text,
    _safe_get_filing,
    _safe_get_filing_text,
    _staleness_confidence_penalty,
)
from .pipeline_runner import (
    _build_pipeline_diagnostics_fields,
    _emit_signals_from_grouped,
    _summarize_focus_usage,
)
from .record_processor import _process_records_for_signals
from .rules.signal_pattern_catalog import (
    FLS_SKIP_SIGNAL_PHRASES,
    load_runtime_signal_catalog,
)
from .sentence_pipeline import join_sentences, split_text_into_sentences
from .signal_schema import ForwardSignalEvidencePayload, ForwardSignalPayload
from .text_record import FilingTextRecord

logger = get_logger(__name__)
_extract_focus_text = _focus_text_extractor._extract_focus_text
_extract_focus_text_from_filing = _focus_text_extractor._extract_focus_text_from_filing
_extract_focus_text_with_strategy_from_filing = (
    _focus_text_extractor._extract_focus_text_with_strategy_from_filing
)

_FORM_SOURCE_TYPE: dict[str, str] = {
    "10-K": "mda",
    "10-Q": "mda",
    "8-K": "press_release",
}

_SOURCE_WEIGHT: dict[str, float] = {"mda": 1.0, "press_release": 0.75}
_SIGNAL_MIN_SCORE = 1.0


def _env_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return max(minimum, parsed)


_DEBUG_RETRIEVAL_PREVIEW_ENABLED = os.getenv(
    "SEC_TEXT_DEBUG_RETRIEVAL_SENTENCES", "0"
).strip().lower() in {"1", "true", "yes"}
_DEBUG_RETRIEVAL_PREVIEW_LIMIT = _env_int(
    "SEC_TEXT_DEBUG_RETRIEVAL_SENTENCES_LIMIT", 3, minimum=0
)
_DEBUG_RETRIEVAL_PREVIEW_CHARS = _env_int(
    "SEC_TEXT_DEBUG_RETRIEVAL_SENTENCE_CHARS", 200, minimum=80
)


def extract_forward_signals_from_sec_text(
    *,
    ticker: str,
    max_filings_per_form: int = 2,
    fetch_records_fn: Callable[[str, int], list[FilingTextRecord]] | None = None,
    rules_sector: str | None = None,
) -> list[dict[str, object]]:
    if fetch_records_fn is not None:
        records = fetch_records_fn(ticker, max_filings_per_form)
    else:
        records = _load_recent_filing_text_records(
            ticker=ticker,
            max_filings_per_form=max_filings_per_form,
            form_source_type=_FORM_SOURCE_TYPE,
            current_year=date.today().year,
            call_with_sec_retry_fn=call_with_sec_retry,
            company_factory_fn=Company,
            normalize_text_fn=_normalize_text,
            normalize_cik_fn=_normalize_cik,
            safe_get_filing_fn=_safe_get_filing,
            safe_get_filing_text_fn=_safe_get_filing_text,
            extract_focus_text_with_strategy_from_filing_fn=(
                _extract_focus_text_with_strategy_from_filing
            ),
            extract_focus_text_fn=_extract_focus_text,
            record_factory_fn=FilingTextRecord,
            log_event_fn=log_event,
            logger=logger,
        )
    if not records:
        return []

    runtime_signal_catalog = load_runtime_signal_catalog(sector=rules_sector)
    grouped, pipeline_diag = _process_records_for_signals(
        ticker=ticker,
        records=records,
        source_weight=_SOURCE_WEIGHT,
        signal_pattern_catalog=runtime_signal_catalog.signal_pattern_catalog,
        metric_retrieval_query=runtime_signal_catalog.metric_retrieval_query,
        debug_retrieval_preview_enabled=_DEBUG_RETRIEVAL_PREVIEW_ENABLED,
        debug_retrieval_preview_limit=_DEBUG_RETRIEVAL_PREVIEW_LIMIT,
        extract_focus_text_fn=_extract_focus_text,
        is_8k_form_fn=is_8k_form,
        refine_8k_analysis_text_fn=refine_8k_analysis_text,
        split_text_into_sentences_fn=split_text_into_sentences,
        should_fast_skip_fls_fn=lambda analysis_sentences: _should_fast_skip_fls_with_phrases(
            analysis_sentences,
            fls_skip_signal_phrases=runtime_signal_catalog.fls_skip_signal_phrases,
        ),
        filter_forward_looking_sentences_with_stats_fn=(
            filter_forward_looking_sentences_with_stats
        ),
        as_float_fn=_as_float,
        as_int_fn=_as_int,
        build_doc_type_fn=_build_doc_type,
        build_sec_source_url_fn=_build_sec_source_url,
        retrieve_relevant_sentences_batch_fn=retrieve_relevant_sentences_batch,
        preview_sentence_fn=_preview_sentence,
        join_sentences_fn=join_sentences,
        extract_metric_regex_hits_fn=extract_metric_regex_hits,
        find_metric_lemma_hits_fn=find_metric_lemma_hits,
        find_metric_dependency_hits_fn=find_metric_dependency_hits,
        filing_age_days_fn=_filing_age_days,
        extract_snippet_fn=_extract_snippet,
        append_unique_evidence_fn=_append_unique_evidence,
    )
    focus_diag = _summarize_focus_usage(
        records, record_used_focus_fn=_record_used_focus
    )

    def _on_payload_invalid(source_type: str, metric: str, signal_id: str) -> None:
        log_event(
            logger,
            event="fundamental_forward_signal_text_payload_invalid",
            message="forward signal text payload failed validation and was skipped",
            level=logging.WARNING,
            error_code="FUNDAMENTAL_FORWARD_SIGNAL_TEXT_PAYLOAD_INVALID",
            fields={
                "ticker": ticker,
                "source_type": source_type,
                "metric": metric,
                "signal_id": signal_id,
            },
        )

    signals = _emit_signals_from_grouped(
        grouped=grouped,
        signal_min_score=_SIGNAL_MIN_SCORE,
        clamp_fn=_clamp,
        staleness_confidence_penalty_fn=_staleness_confidence_penalty,
        build_forward_signal_payload_fn=_build_forward_signal_payload,
        on_payload_invalid=_on_payload_invalid,
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
        emitted_focused_doc_types = sorted(
            {
                doc_type
                for doc_type in emitted_doc_types
                if isinstance(doc_type, str) and doc_type.endswith("_focused")
            }
        )
        focused_signals_count = sum(
            1
            for signal in signals
            if isinstance(signal.get("evidence"), list)
            and any(
                isinstance(evidence, dict)
                and isinstance(evidence.get("doc_type"), str)
                and evidence.get("doc_type", "").endswith("_focused")
                for evidence in signal.get("evidence", [])
            )
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
                "emitted_focused_doc_types": emitted_focused_doc_types,
                "focused_signals_count": focused_signals_count,
                **_build_pipeline_diagnostics_fields(
                    pipeline_diag,
                    debug_retrieval_preview_enabled=_DEBUG_RETRIEVAL_PREVIEW_ENABLED,
                ),
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
                **_build_pipeline_diagnostics_fields(
                    pipeline_diag,
                    debug_retrieval_preview_enabled=_DEBUG_RETRIEVAL_PREVIEW_ENABLED,
                ),
            },
        )
    return signals


def _build_forward_signal_payload(
    *,
    signal_id: str,
    source_type: str,
    metric: str,
    direction: str,
    value_basis_points: float,
    confidence: float,
    median_filing_age_days: int | None,
    evidence: list[JSONObject],
) -> dict[str, object] | None:
    try:
        validated_evidence = [
            ForwardSignalEvidencePayload.model_validate(item) for item in evidence
        ]
        payload = ForwardSignalPayload(
            signal_id=signal_id,
            source_type=source_type,
            metric=metric,
            direction=direction,
            value=round(value_basis_points, 2),
            unit="basis_points",
            confidence=round(confidence, 4),
            as_of=datetime.now(UTC).isoformat(),
            median_filing_age_days=median_filing_age_days,
            evidence=validated_evidence,
        )
        return payload.model_dump()
    except ValidationError:
        return None


def _record_used_focus(record: FilingTextRecord) -> bool:
    if isinstance(record.focus_text, str) and record.focus_text:
        return True
    inferred_focus = _extract_focus_text(form=record.form, text=record.text)
    return isinstance(inferred_focus, str) and bool(inferred_focus)


def _should_fast_skip_fls(analysis_sentences: list[str]) -> bool:
    return _should_fast_skip_fls_with_phrases(
        analysis_sentences,
        fls_skip_signal_phrases=FLS_SKIP_SIGNAL_PHRASES,
    )


def _should_fast_skip_fls_with_phrases(
    analysis_sentences: list[str], *, fls_skip_signal_phrases: tuple[str, ...]
) -> bool:
    if not analysis_sentences:
        return True
    for sentence in analysis_sentences:
        normalized = sentence.strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if has_forward_tense_cue(normalized):
            return False
        if contains_numeric_guidance_cue(normalized):
            return False
        if any(phrase in lowered for phrase in fls_skip_signal_phrases):
            return False
    return True


def _preview_sentence(sentence: str) -> str | None:
    normalized = " ".join(sentence.split())
    if not normalized:
        return None
    if len(normalized) <= _DEBUG_RETRIEVAL_PREVIEW_CHARS:
        return normalized
    return normalized[: _DEBUG_RETRIEVAL_PREVIEW_CHARS - 3] + "..."
