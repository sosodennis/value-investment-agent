from __future__ import annotations

import logging
import os
from collections.abc import Callable

from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject

from .filtering.fls_filter import filter_forward_looking_sentences_with_stats
from .matching.matchers.dependency_signal_matcher import find_metric_dependency_hits
from .matching.matchers.lemma_signal_matcher import find_metric_lemma_hits
from .matching.matchers.regex_signal_extractor import (
    contains_numeric_guidance_cue,
    extract_metric_regex_hits,
    has_forward_tense_cue,
)
from .matching.pipeline_evidence_service import (
    _append_unique_evidence,
    _build_evidence_preview,
    _extract_snippet,
)
from .matching.pipeline_scalar_service import (
    _as_float,
    _as_int,
    _clamp,
)
from .matching.record_processor import _process_records_for_signals
from .matching.rules.signal_pattern_catalog import (
    FLS_SKIP_SIGNAL_PHRASES,
    load_runtime_signal_catalog,
)
from .postprocess.finbert_direction import review_signal_direction_with_finbert
from .postprocess.pipeline_filing_metadata_service import (
    _build_doc_type,
    _build_sec_source_url,
    _filing_age_days,
    _staleness_confidence_penalty,
)
from .postprocess.pipeline_runner import (
    _build_pipeline_diagnostics_fields,
    _emit_signals_from_grouped,
    _summarize_focus_usage,
)
from .postprocess.text_signal_diagnostics_service import build_text_signal_log_fields
from .postprocess.text_signal_postprocess_service import (
    apply_finbert_direction_reviews as apply_finbert_direction_reviews_util,
)
from .postprocess.text_signal_postprocess_service import (
    build_forward_signal_payload as build_forward_signal_payload_util,
)
from .postprocess.text_signal_postprocess_service import (
    preview_sentence as preview_sentence_util,
)
from .postprocess.text_signal_postprocess_service import (
    should_fast_skip_fls_with_phrases as should_fast_skip_fls_with_phrases_util,
)
from .retrieval import focus_text_extractor as _focus_text_extractor
from .retrieval.filing_section_selector import is_8k_form, refine_8k_analysis_text
from .retrieval.hybrid_retriever import retrieve_relevant_sentences_batch
from .retrieval.pipeline_text_normalization_service import (
    _normalize_text as _normalize_text_util,
)
from .retrieval.sentence_pipeline import join_sentences, split_text_into_sentences
from .retrieval.text_record import FilingTextRecord
from .retrieval.text_signal_record_loader_service import load_sec_text_records

logger = get_logger(__name__)
_extract_focus_text = _focus_text_extractor._extract_focus_text
_extract_focus_text_from_filing = _focus_text_extractor._extract_focus_text_from_filing
_extract_focus_text_with_strategy_from_filing = (
    _focus_text_extractor._extract_focus_text_with_strategy_from_filing
)
_normalize_text = _normalize_text_util

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
    records = load_sec_text_records(
        ticker=ticker,
        max_filings_per_form=max_filings_per_form,
        form_source_type=_FORM_SOURCE_TYPE,
        fetch_records_fn=fetch_records_fn,
        logger_=logger,
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
        build_evidence_preview_fn=_build_evidence_preview,
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
    finbert_direction_diag = _apply_finbert_direction_reviews(signals)

    if signals:
        log_event(
            logger,
            event="fundamental_forward_signal_text_producer_completed",
            message="forward signal text producer generated signals",
            fields=build_text_signal_log_fields(
                ticker=ticker,
                focus_diag=focus_diag,
                pipeline_diag=pipeline_diag,
                finbert_direction_diag=finbert_direction_diag,
                debug_retrieval_preview_enabled=_DEBUG_RETRIEVAL_PREVIEW_ENABLED,
                build_pipeline_diagnostics_fields_fn=_build_pipeline_diagnostics_fields,
                signals=signals,
            ),
        )
    else:
        log_event(
            logger,
            event="fundamental_forward_signal_text_producer_no_signal",
            message="forward signal text producer found no eligible signals",
            fields=build_text_signal_log_fields(
                ticker=ticker,
                focus_diag=focus_diag,
                pipeline_diag=pipeline_diag,
                finbert_direction_diag=finbert_direction_diag,
                debug_retrieval_preview_enabled=_DEBUG_RETRIEVAL_PREVIEW_ENABLED,
                build_pipeline_diagnostics_fields_fn=_build_pipeline_diagnostics_fields,
            ),
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
    return build_forward_signal_payload_util(
        signal_id=signal_id,
        source_type=source_type,
        metric=metric,
        direction=direction,
        value_basis_points=value_basis_points,
        confidence=confidence,
        median_filing_age_days=median_filing_age_days,
        evidence=evidence,
    )


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
    return should_fast_skip_fls_with_phrases_util(
        analysis_sentences=analysis_sentences,
        fls_skip_signal_phrases=fls_skip_signal_phrases,
        has_forward_tense_cue_fn=has_forward_tense_cue,
        contains_numeric_guidance_cue_fn=contains_numeric_guidance_cue,
    )


def _preview_sentence(sentence: str) -> str | None:
    return preview_sentence_util(
        sentence,
        max_chars=_DEBUG_RETRIEVAL_PREVIEW_CHARS,
    )


def _apply_finbert_direction_reviews(
    signals: list[dict[str, object]],
) -> dict[str, object]:
    return apply_finbert_direction_reviews_util(
        signals=signals,
        review_signal_direction_with_finbert_fn=review_signal_direction_with_finbert,
        clamp_fn=_clamp,
    )
