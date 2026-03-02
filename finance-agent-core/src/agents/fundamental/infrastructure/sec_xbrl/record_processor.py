from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from .pipeline_runner import _MetricSignalAccumulator, _TextPipelineDiagnostics
from .record_processor_metric_service import (
    ExtractMetricRegexHitsFn,
    FindMetricDependencyHitsFn,
    FindMetricLemmaHitsFn,
    MetricEvidenceContext,
    MetricProcessingResult,
    process_metric_signal_for_record,
)
from .record_processor_preparation_service import (
    PreparedRecordDiagnostics,
    PreparedRecordPayload,
    prepare_record_processing_payload,
)
from .rules.signal_pattern_catalog import MetricPatternSet

if TYPE_CHECKING:
    from .text_record import FilingTextRecord


def _process_records_for_signals(
    *,
    ticker: str,
    records: list[FilingTextRecord],
    source_weight: dict[str, float],
    signal_pattern_catalog: dict[str, MetricPatternSet],
    metric_retrieval_query: dict[str, str],
    debug_retrieval_preview_enabled: bool,
    debug_retrieval_preview_limit: int,
    extract_focus_text_fn: Callable[..., str | None],
    is_8k_form_fn: Callable[[str], bool],
    refine_8k_analysis_text_fn: Callable[[str], object],
    split_text_into_sentences_fn: Callable[[str], list[str]],
    should_fast_skip_fls_fn: Callable[[list[str]], bool],
    filter_forward_looking_sentences_with_stats_fn: Callable[
        [list[str]], tuple[list[str], dict[str, float | int]]
    ],
    as_float_fn: Callable[[object], float],
    as_int_fn: Callable[[object], int],
    build_doc_type_fn: Callable[..., str],
    build_sec_source_url_fn: Callable[..., str],
    retrieve_relevant_sentences_batch_fn: Callable[..., list[list[str]]],
    preview_sentence_fn: Callable[[str], str | None],
    join_sentences_fn: Callable[[list[str]], str],
    extract_metric_regex_hits_fn: ExtractMetricRegexHitsFn,
    find_metric_lemma_hits_fn: FindMetricLemmaHitsFn,
    find_metric_dependency_hits_fn: FindMetricDependencyHitsFn,
    filing_age_days_fn: Callable[[str | None], int | None],
    extract_snippet_fn: Callable[[str, int, int, int], str | None],
    build_evidence_preview_fn: Callable[[str], str],
    append_unique_evidence_fn: Callable[
        [list[dict[str, object]], dict[str, object]], None
    ],
) -> tuple[dict[str, dict[str, _MetricSignalAccumulator]], _TextPipelineDiagnostics]:
    grouped: dict[str, dict[str, _MetricSignalAccumulator]] = {}
    pipeline_diag = _TextPipelineDiagnostics()

    for record in records:
        pipeline_diag.records_processed += 1

        prepared, prep_diag = prepare_record_processing_payload(
            ticker=ticker,
            record=record,
            extract_focus_text_fn=extract_focus_text_fn,
            is_8k_form_fn=is_8k_form_fn,
            refine_8k_analysis_text_fn=refine_8k_analysis_text_fn,
            split_text_into_sentences_fn=split_text_into_sentences_fn,
            should_fast_skip_fls_fn=should_fast_skip_fls_fn,
            filter_forward_looking_sentences_with_stats_fn=(
                filter_forward_looking_sentences_with_stats_fn
            ),
            as_float_fn=as_float_fn,
            as_int_fn=as_int_fn,
            build_doc_type_fn=build_doc_type_fn,
            build_sec_source_url_fn=build_sec_source_url_fn,
        )

        _accumulate_preparation_diagnostics(pipeline_diag, prepared, prep_diag)

        metric_order = list(signal_pattern_catalog.keys())
        metric_queries = [
            metric_retrieval_query.get(metric, metric.replace("_", " "))
            for metric in metric_order
        ]
        pipeline_diag.metric_queries_total += len(metric_order)

        retrieval_started = time.perf_counter()
        metric_retrieval_results = retrieve_relevant_sentences_batch_fn(
            queries=metric_queries,
            corpus=prepared.retrieval_corpus,
            top_k=24,
        )
        pipeline_diag.retrieval_ms_total += (
            time.perf_counter() - retrieval_started
        ) * 1000.0

        record_has_signal_candidates = False
        source_bucket = grouped.setdefault(record.source_type, {})
        source_bucket_weight = source_weight.get(record.source_type, 1.0)

        for idx, metric in enumerate(metric_order):
            patterns = signal_pattern_catalog[metric]
            metric_sentences = (
                metric_retrieval_results[idx]
                if idx < len(metric_retrieval_results)
                else []
            )

            _capture_metric_retrieval_preview(
                pipeline_diag=pipeline_diag,
                metric=metric,
                metric_sentences=metric_sentences,
                debug_retrieval_preview_enabled=debug_retrieval_preview_enabled,
                debug_retrieval_preview_limit=debug_retrieval_preview_limit,
                preview_sentence_fn=preview_sentence_fn,
            )

            pattern_started = time.perf_counter()
            result = process_metric_signal_for_record(
                metric=metric,
                patterns=patterns,
                metric_sentences=metric_sentences,
                analysis_text=prepared.analysis_text,
                existing=source_bucket.get(metric),
                source_weight=source_bucket_weight,
                filing_age_days=filing_age_days_fn(record.filing_date),
                evidence_context=MetricEvidenceContext(
                    source_url=prepared.source_url,
                    doc_type=prepared.doc_type,
                    period=record.period or "N/A",
                    filing_date=record.filing_date,
                    accession_number=record.accession_number,
                    focus_strategy=record.focus_strategy,
                ),
                join_sentences_fn=join_sentences_fn,
                extract_metric_regex_hits_fn=extract_metric_regex_hits_fn,
                find_metric_lemma_hits_fn=find_metric_lemma_hits_fn,
                find_metric_dependency_hits_fn=find_metric_dependency_hits_fn,
                extract_snippet_fn=extract_snippet_fn,
                build_evidence_preview_fn=build_evidence_preview_fn,
                append_unique_evidence_fn=append_unique_evidence_fn,
            )
            pipeline_diag.pattern_ms_total += (
                time.perf_counter() - pattern_started
            ) * 1000.0

            _accumulate_metric_diagnostics(pipeline_diag, metric, result)

            if result.has_signal_candidates and result.accumulator is not None:
                source_bucket[metric] = result.accumulator
                record_has_signal_candidates = True

        if record_has_signal_candidates:
            pipeline_diag.records_with_signal_candidates += 1

    return grouped, pipeline_diag


def _accumulate_preparation_diagnostics(
    pipeline_diag: _TextPipelineDiagnostics,
    prepared: PreparedRecordPayload,
    prep_diag: PreparedRecordDiagnostics,
) -> None:
    pipeline_diag.analysis_sentences_total += len(prepared.analysis_sentences)
    pipeline_diag.retrieval_corpus_sentences_total += len(prepared.retrieval_corpus)
    forward_count = len(prepared.retrieval_corpus)
    if forward_count < len(prepared.analysis_sentences):
        pipeline_diag.forward_sentences_total += forward_count

    pipeline_diag.split_ms_total += prep_diag.split_ms
    pipeline_diag.fls_ms_total += prep_diag.fls_ms
    pipeline_diag.fls_model_load_ms_total += prep_diag.fls_model_load_ms
    pipeline_diag.fls_inference_ms_total += prep_diag.fls_inference_ms
    pipeline_diag.fls_sentences_scored_total += prep_diag.fls_sentences_scored
    pipeline_diag.fls_prefilter_selected_total += prep_diag.fls_prefilter_selected
    pipeline_diag.fls_batches_total += prep_diag.fls_batches
    pipeline_diag.fls_cache_hits_total += prep_diag.fls_cache_hits
    pipeline_diag.fls_cache_misses_total += prep_diag.fls_cache_misses
    pipeline_diag.fls_fast_skip_records_total += prep_diag.fls_fast_skip_records
    pipeline_diag.fls_fast_skip_sentences_total += prep_diag.fls_fast_skip_sentences
    pipeline_diag.eight_k_sections_selected_total += prep_diag.eight_k_sections_selected
    pipeline_diag.eight_k_noise_sentences_skipped_total += (
        prep_diag.eight_k_noise_sentences_skipped
    )


def _capture_metric_retrieval_preview(
    *,
    pipeline_diag: _TextPipelineDiagnostics,
    metric: str,
    metric_sentences: list[str],
    debug_retrieval_preview_enabled: bool,
    debug_retrieval_preview_limit: int,
    preview_sentence_fn: Callable[[str], str | None],
) -> None:
    if (
        not debug_retrieval_preview_enabled
        or debug_retrieval_preview_limit <= 0
        or metric in pipeline_diag.retrieval_preview_by_metric
        or not metric_sentences
    ):
        return

    previews = [
        preview_sentence_fn(sentence)
        for sentence in metric_sentences[:debug_retrieval_preview_limit]
    ]
    pipeline_diag.retrieval_preview_by_metric[metric] = [
        item for item in previews if item
    ]


def _accumulate_metric_diagnostics(
    pipeline_diag: _TextPipelineDiagnostics,
    metric: str,
    result: MetricProcessingResult,
) -> None:
    diagnostics = result.diagnostics

    retrieved_count = diagnostics.retrieved_sentences_count
    lexical_count = diagnostics.lexical_hit_count
    lemma_count = diagnostics.lemma_hit_count
    dependency_count = diagnostics.dependency_hit_count
    numeric_count = diagnostics.numeric_hit_count

    pipeline_diag.metric_retrieved_sentences_total += retrieved_count
    pipeline_diag.retrieval_sentences_by_metric[metric] += retrieved_count
    pipeline_diag.lexical_hits_total += lexical_count
    pipeline_diag.lemma_hits_total += lemma_count
    pipeline_diag.dependency_hits_total += dependency_count
    pipeline_diag.numeric_hits_total += numeric_count
    pipeline_diag.lexical_hits_by_metric[metric] += lexical_count
    pipeline_diag.lemma_hits_by_metric[metric] += lemma_count
    pipeline_diag.dependency_hits_by_metric[metric] += dependency_count
    pipeline_diag.numeric_hits_by_metric[metric] += numeric_count
