from __future__ import annotations

import time
from typing import TYPE_CHECKING, Protocol

from .pipeline_runner import _MetricSignalAccumulator, _TextPipelineDiagnostics
from .rules.signal_pattern_catalog import MetricPatternSet

if TYPE_CHECKING:
    from .text_record import FilingTextRecord


class _FocusExtractorFn(Protocol):
    def __call__(self, *, form: str, text: str) -> str | None: ...


class _Is8KFormFn(Protocol):
    def __call__(self, form: str) -> bool: ...


class _Refined8KResult(Protocol):
    text: str | None
    sections_selected: int
    noise_sentences_skipped: int


class _Refine8KAnalysisTextFn(Protocol):
    def __call__(self, text: str) -> _Refined8KResult: ...


class _SplitTextIntoSentencesFn(Protocol):
    def __call__(self, text: str) -> list[str]: ...


class _ShouldFastSkipFlsFn(Protocol):
    def __call__(self, analysis_sentences: list[str]) -> bool: ...


class _FilterForwardLookingSentencesWithStatsFn(Protocol):
    def __call__(
        self, sentences: list[str]
    ) -> tuple[list[str], dict[str, float | int]]: ...


class _AsFloatFn(Protocol):
    def __call__(self, value: object) -> float: ...


class _AsIntFn(Protocol):
    def __call__(self, value: object) -> int: ...


class _BuildDocTypeFn(Protocol):
    def __call__(self, form: str, *, used_focus: bool) -> str: ...


class _BuildSecSourceUrlFn(Protocol):
    def __call__(
        self,
        *,
        ticker: str,
        accession_number: str | None,
        cik: str | None,
    ) -> str: ...


class _RetrieveRelevantSentencesBatchFn(Protocol):
    def __call__(
        self, *, queries: list[str], corpus: list[str], top_k: int
    ) -> list[list[str]]: ...


class _PreviewSentenceFn(Protocol):
    def __call__(self, sentence: str) -> str | None: ...


class _JoinSentencesFn(Protocol):
    def __call__(self, sentences: list[str]) -> str: ...


class _PatternHit(Protocol):
    start: int
    end: int
    weighted_score: float
    is_forward: bool
    is_historical: bool
    rule: str


class _NumericGuidanceHit(Protocol):
    start: int
    end: int
    direction: str
    score: float
    value_basis_points: float


class _MetricRegexHits(Protocol):
    up_hits: list[_PatternHit]
    down_hits: list[_PatternHit]
    numeric_hits: list[_NumericGuidanceHit]


class _ExtractMetricRegexHitsFn(Protocol):
    def __call__(
        self,
        *,
        analysis_text: str,
        metric_text: str,
        metric: str,
        patterns: MetricPatternSet,
    ) -> _MetricRegexHits: ...


class _FindMetricLemmaHitsFn(Protocol):
    def __call__(
        self, *, text: str, metric: str
    ) -> tuple[list[_PatternHit], list[_PatternHit]]: ...


class _FindMetricDependencyHitsFn(Protocol):
    def __call__(
        self, *, text: str, metric: str
    ) -> tuple[list[_PatternHit], list[_PatternHit]]: ...


class _FilingAgeDaysFn(Protocol):
    def __call__(self, filing_date: str | None) -> int | None: ...


class _ExtractSnippetFn(Protocol):
    def __call__(
        self, text: str, start: int, end: int, radius: int = 70
    ) -> str | None: ...


class _BuildEvidencePreviewFn(Protocol):
    def __call__(self, full_text: str) -> str: ...


class _AppendUniqueEvidenceFn(Protocol):
    def __call__(
        self, evidence: list[dict[str, object]], candidate: dict[str, object]
    ) -> None: ...


def _process_records_for_signals(
    *,
    ticker: str,
    records: list[FilingTextRecord],
    source_weight: dict[str, float],
    signal_pattern_catalog: dict[str, MetricPatternSet],
    metric_retrieval_query: dict[str, str],
    debug_retrieval_preview_enabled: bool,
    debug_retrieval_preview_limit: int,
    extract_focus_text_fn: _FocusExtractorFn,
    is_8k_form_fn: _Is8KFormFn,
    refine_8k_analysis_text_fn: _Refine8KAnalysisTextFn,
    split_text_into_sentences_fn: _SplitTextIntoSentencesFn,
    should_fast_skip_fls_fn: _ShouldFastSkipFlsFn,
    filter_forward_looking_sentences_with_stats_fn: _FilterForwardLookingSentencesWithStatsFn,
    as_float_fn: _AsFloatFn,
    as_int_fn: _AsIntFn,
    build_doc_type_fn: _BuildDocTypeFn,
    build_sec_source_url_fn: _BuildSecSourceUrlFn,
    retrieve_relevant_sentences_batch_fn: _RetrieveRelevantSentencesBatchFn,
    preview_sentence_fn: _PreviewSentenceFn,
    join_sentences_fn: _JoinSentencesFn,
    extract_metric_regex_hits_fn: _ExtractMetricRegexHitsFn,
    find_metric_lemma_hits_fn: _FindMetricLemmaHitsFn,
    find_metric_dependency_hits_fn: _FindMetricDependencyHitsFn,
    filing_age_days_fn: _FilingAgeDaysFn,
    extract_snippet_fn: _ExtractSnippetFn,
    build_evidence_preview_fn: _BuildEvidencePreviewFn,
    append_unique_evidence_fn: _AppendUniqueEvidenceFn,
) -> tuple[dict[str, dict[str, _MetricSignalAccumulator]], _TextPipelineDiagnostics]:
    grouped: dict[str, dict[str, _MetricSignalAccumulator]] = {}
    pipeline_diag = _TextPipelineDiagnostics()

    for record in records:
        pipeline_diag.records_processed += 1
        focused_section = record.focus_text or extract_focus_text_fn(
            form=record.form, text=record.text
        )
        analysis_text = focused_section or record.text
        if is_8k_form_fn(record.form):
            refined_8k = refine_8k_analysis_text_fn(analysis_text)
            analysis_text = refined_8k.text or analysis_text
            pipeline_diag.eight_k_sections_selected_total += (
                refined_8k.sections_selected
            )
            pipeline_diag.eight_k_noise_sentences_skipped_total += (
                refined_8k.noise_sentences_skipped
            )

        split_started = time.perf_counter()
        analysis_sentences = split_text_into_sentences_fn(analysis_text)
        pipeline_diag.split_ms_total += (time.perf_counter() - split_started) * 1000.0

        fls_stats: dict[str, float | int] = {}
        if should_fast_skip_fls_fn(analysis_sentences):
            forward_sentences = []
            pipeline_diag.fls_fast_skip_records_total += 1
            pipeline_diag.fls_fast_skip_sentences_total += len(analysis_sentences)
        else:
            fls_started = time.perf_counter()
            forward_sentences, fls_stats = (
                filter_forward_looking_sentences_with_stats_fn(analysis_sentences)
            )
            pipeline_diag.fls_ms_total += (time.perf_counter() - fls_started) * 1000.0
            pipeline_diag.fls_model_load_ms_total += as_float_fn(
                fls_stats.get("model_load_ms")
            )
            pipeline_diag.fls_inference_ms_total += as_float_fn(
                fls_stats.get("inference_ms")
            )
            pipeline_diag.fls_sentences_scored_total += as_int_fn(
                fls_stats.get("sentences_scored")
            )
            pipeline_diag.fls_prefilter_selected_total += as_int_fn(
                fls_stats.get("prefilter_selected")
            )
            pipeline_diag.fls_batches_total += as_int_fn(fls_stats.get("batches"))
            pipeline_diag.fls_cache_hits_total += as_int_fn(fls_stats.get("cache_hits"))
            pipeline_diag.fls_cache_misses_total += as_int_fn(
                fls_stats.get("cache_misses")
            )

        retrieval_corpus = (
            forward_sentences if forward_sentences else analysis_sentences
        )
        pipeline_diag.analysis_sentences_total += len(analysis_sentences)
        pipeline_diag.forward_sentences_total += len(forward_sentences)
        pipeline_diag.retrieval_corpus_sentences_total += len(retrieval_corpus)

        doc_type = build_doc_type_fn(
            record.form, used_focus=focused_section is not None
        )
        source_url = build_sec_source_url_fn(
            ticker=ticker,
            accession_number=record.accession_number,
            cik=record.cik,
        )

        metric_order = list(signal_pattern_catalog.keys())
        metric_queries = [
            metric_retrieval_query.get(metric, metric.replace("_", " "))
            for metric in metric_order
        ]
        pipeline_diag.metric_queries_total += len(metric_order)

        retrieval_started = time.perf_counter()
        metric_retrieval_results = retrieve_relevant_sentences_batch_fn(
            queries=metric_queries,
            corpus=retrieval_corpus,
            top_k=24,
        )
        pipeline_diag.retrieval_ms_total += (
            time.perf_counter() - retrieval_started
        ) * 1000.0

        record_has_signal_candidates = False
        for idx, metric in enumerate(metric_order):
            patterns = signal_pattern_catalog[metric]
            metric_sentences = (
                metric_retrieval_results[idx]
                if idx < len(metric_retrieval_results)
                else []
            )
            if (
                debug_retrieval_preview_enabled
                and debug_retrieval_preview_limit > 0
                and metric not in pipeline_diag.retrieval_preview_by_metric
                and metric_sentences
            ):
                previews = [
                    preview_sentence_fn(sentence)
                    for sentence in metric_sentences[:debug_retrieval_preview_limit]
                ]
                pipeline_diag.retrieval_preview_by_metric[metric] = [
                    item for item in previews if item
                ]

            pipeline_diag.metric_retrieved_sentences_total += len(metric_sentences)
            pipeline_diag.retrieval_sentences_by_metric[metric] += len(metric_sentences)
            metric_text = join_sentences_fn(metric_sentences) or analysis_text

            pattern_started = time.perf_counter()
            regex_hits = extract_metric_regex_hits_fn(
                analysis_text=metric_text,
                metric=metric,
                metric_text=metric_text,
                patterns=patterns,
            )
            lemma_up_hits, lemma_down_hits = find_metric_lemma_hits_fn(
                text=metric_text,
                metric=metric,
            )
            dependency_up_hits, dependency_down_hits = find_metric_dependency_hits_fn(
                text=metric_text,
                metric=metric,
            )
            up_hits = regex_hits.up_hits + lemma_up_hits + dependency_up_hits
            down_hits = regex_hits.down_hits + lemma_down_hits + dependency_down_hits
            numeric_hits = regex_hits.numeric_hits
            pipeline_diag.pattern_ms_total += (
                time.perf_counter() - pattern_started
            ) * 1000.0

            lexical_hit_count = len(regex_hits.up_hits) + len(regex_hits.down_hits)
            lemma_hit_count = len(lemma_up_hits) + len(lemma_down_hits)
            dependency_hit_count = len(dependency_up_hits) + len(dependency_down_hits)
            numeric_hit_count = len(numeric_hits)
            pipeline_diag.lexical_hits_total += lexical_hit_count
            pipeline_diag.lemma_hits_total += lemma_hit_count
            pipeline_diag.dependency_hits_total += dependency_hit_count
            pipeline_diag.numeric_hits_total += numeric_hit_count
            pipeline_diag.lexical_hits_by_metric[metric] += lexical_hit_count
            pipeline_diag.lemma_hits_by_metric[metric] += lemma_hit_count
            pipeline_diag.dependency_hits_by_metric[metric] += dependency_hit_count
            pipeline_diag.numeric_hits_by_metric[metric] += numeric_hit_count
            if not up_hits and not down_hits and not numeric_hits:
                continue
            record_has_signal_candidates = True

            source_bucket = grouped.setdefault(record.source_type, {})
            existing = source_bucket.get(metric)
            if existing is None:
                existing = _MetricSignalAccumulator(
                    up_score=0.0,
                    down_score=0.0,
                    evidence=[],
                    forward_hit_count=0,
                    historical_hit_count=0,
                    numeric_hit_count=0,
                    numeric_basis_points_samples=[],
                    filing_age_days_samples=[],
                )

            weight = source_weight.get(record.source_type, 1.0)
            up_score = existing.up_score + (
                sum(hit.weighted_score for hit in up_hits) * weight
            )
            down_score = existing.down_score + (
                sum(hit.weighted_score for hit in down_hits) * weight
            )
            evidence = list(existing.evidence)
            forward_hit_count = existing.forward_hit_count
            historical_hit_count = existing.historical_hit_count
            numeric_hit_count = existing.numeric_hit_count
            numeric_basis_points_samples = list(existing.numeric_basis_points_samples)
            filing_age_days_samples = list(existing.filing_age_days_samples)
            filing_age_days = filing_age_days_fn(record.filing_date)
            if filing_age_days is not None:
                filing_age_days_samples.append(filing_age_days)

            for hit in up_hits + down_hits:
                if hit.is_forward:
                    forward_hit_count += 1
                if hit.is_historical:
                    historical_hit_count += 1
                snippet = extract_snippet_fn(metric_text, hit.start, hit.end)
                if not snippet:
                    continue
                preview_text = build_evidence_preview_fn(snippet)
                append_unique_evidence_fn(
                    evidence,
                    {
                        "preview_text": preview_text,
                        "full_text": snippet,
                        "source_url": source_url,
                        "doc_type": doc_type,
                        "period": record.period or "N/A",
                        "filing_date": record.filing_date,
                        "accession_number": record.accession_number,
                        "focus_strategy": record.focus_strategy,
                        "rule": hit.rule,
                        "source_locator": {
                            "text_scope": "metric_text",
                            "char_start": hit.start,
                            "char_end": hit.end,
                        },
                    },
                )
                if len(evidence) >= 5:
                    break

            if len(evidence) < 5:
                for numeric_hit in numeric_hits:
                    numeric_hit_count += 1
                    numeric_basis_points_samples.append(numeric_hit.value_basis_points)
                    if numeric_hit.direction == "up":
                        up_score += numeric_hit.score * weight
                    else:
                        down_score += numeric_hit.score * weight
                    snippet = extract_snippet_fn(
                        metric_text, numeric_hit.start, numeric_hit.end
                    )
                    if not snippet:
                        continue
                    preview_text = build_evidence_preview_fn(snippet)
                    append_unique_evidence_fn(
                        evidence,
                        {
                            "preview_text": preview_text,
                            "full_text": snippet,
                            "source_url": source_url,
                            "doc_type": doc_type,
                            "period": record.period or "N/A",
                            "filing_date": record.filing_date,
                            "accession_number": record.accession_number,
                            "focus_strategy": record.focus_strategy,
                            "rule": "numeric_guidance",
                            "value_basis_points": round(
                                numeric_hit.value_basis_points, 2
                            ),
                            "source_locator": {
                                "text_scope": "metric_text",
                                "char_start": numeric_hit.start,
                                "char_end": numeric_hit.end,
                            },
                        },
                    )
                    if len(evidence) >= 5:
                        break

            source_bucket[metric] = _MetricSignalAccumulator(
                up_score=up_score,
                down_score=down_score,
                evidence=evidence,
                forward_hit_count=forward_hit_count,
                historical_hit_count=historical_hit_count,
                numeric_hit_count=numeric_hit_count,
                numeric_basis_points_samples=numeric_basis_points_samples,
                filing_age_days_samples=filing_age_days_samples,
            )

        if record_has_signal_candidates:
            pipeline_diag.records_with_signal_candidates += 1

    return grouped, pipeline_diag
