from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from statistics import median
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .text_record import FilingTextRecord


class _BuildForwardSignalPayloadFn(Protocol):
    def __call__(
        self,
        *,
        signal_id: str,
        source_type: str,
        metric: str,
        direction: str,
        value_basis_points: float,
        confidence: float,
        median_filing_age_days: int | None,
        evidence: list[dict[str, object]],
    ) -> dict[str, object] | None: ...


@dataclass(frozen=True)
class _MetricSignalAccumulator:
    up_score: float
    down_score: float
    evidence: list[dict[str, object]]
    forward_hit_count: int
    historical_hit_count: int
    numeric_hit_count: int
    numeric_basis_points_samples: list[float]
    filing_age_days_samples: list[int]


@dataclass
class _TextPipelineDiagnostics:
    records_processed: int = 0
    records_with_signal_candidates: int = 0
    analysis_sentences_total: int = 0
    forward_sentences_total: int = 0
    retrieval_corpus_sentences_total: int = 0
    metric_queries_total: int = 0
    metric_retrieved_sentences_total: int = 0
    eight_k_sections_selected_total: int = 0
    eight_k_noise_sentences_skipped_total: int = 0
    lexical_hits_total: int = 0
    lemma_hits_total: int = 0
    dependency_hits_total: int = 0
    numeric_hits_total: int = 0
    retrieval_sentences_by_metric: Counter[str] = field(default_factory=Counter)
    lexical_hits_by_metric: Counter[str] = field(default_factory=Counter)
    lemma_hits_by_metric: Counter[str] = field(default_factory=Counter)
    dependency_hits_by_metric: Counter[str] = field(default_factory=Counter)
    numeric_hits_by_metric: Counter[str] = field(default_factory=Counter)
    split_ms_total: float = 0.0
    fls_ms_total: float = 0.0
    fls_model_load_ms_total: float = 0.0
    fls_inference_ms_total: float = 0.0
    fls_sentences_scored_total: int = 0
    fls_prefilter_selected_total: int = 0
    fls_batches_total: int = 0
    fls_cache_hits_total: int = 0
    fls_cache_misses_total: int = 0
    fls_fast_skip_records_total: int = 0
    fls_fast_skip_sentences_total: int = 0
    retrieval_ms_total: float = 0.0
    pattern_ms_total: float = 0.0
    retrieval_preview_by_metric: dict[str, list[str]] = field(default_factory=dict)


def _emit_signals_from_grouped(
    *,
    grouped: dict[str, dict[str, _MetricSignalAccumulator]],
    signal_min_score: float,
    clamp_fn: Callable[[float, float, float], float],
    staleness_confidence_penalty_fn: Callable[[int | None], float],
    build_forward_signal_payload_fn: _BuildForwardSignalPayloadFn,
    on_payload_invalid: Callable[[str, str, str], None] | None = None,
) -> list[dict[str, object]]:
    signals: list[dict[str, object]] = []
    for source_type, metrics in grouped.items():
        for metric, acc in metrics.items():
            score = acc.up_score - acc.down_score
            if abs(score) < signal_min_score:
                continue
            direction = "up" if score > 0 else "down"
            lexical_value_basis_points = abs(score) * 35.0
            numeric_anchor_basis_points = (
                median(acc.numeric_basis_points_samples)
                if acc.numeric_basis_points_samples
                else 0.0
            )
            value_basis_points = clamp_fn(
                max(lexical_value_basis_points, numeric_anchor_basis_points * 0.75),
                25.0,
                220.0,
            )
            total_context_hits = acc.forward_hit_count + acc.historical_hit_count
            forward_ratio = (
                acc.forward_hit_count / total_context_hits
                if total_context_hits > 0
                else 0.0
            )
            historical_ratio = (
                acc.historical_hit_count / total_context_hits
                if total_context_hits > 0
                else 0.0
            )
            numeric_bonus = min(acc.numeric_hit_count, 2) * 0.04
            median_filing_age_days = (
                int(median(acc.filing_age_days_samples))
                if acc.filing_age_days_samples
                else None
            )
            staleness_penalty = staleness_confidence_penalty_fn(median_filing_age_days)
            confidence = clamp_fn(
                0.54
                + min(abs(score), 7.0) * 0.024
                + (forward_ratio * 0.09)
                + numeric_bonus
                - (historical_ratio * 0.06)
                - staleness_penalty,
                0.52,
                0.86,
            )
            evidence = acc.evidence[:3]
            if not evidence:
                continue
            signal_id = (
                f"sec_text_{source_type}_{metric}_"
                f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
            )
            payload = build_forward_signal_payload_fn(
                signal_id=signal_id,
                source_type=source_type,
                metric=metric,
                direction=direction,
                value_basis_points=value_basis_points,
                confidence=confidence,
                median_filing_age_days=median_filing_age_days,
                evidence=evidence,
            )
            if payload is None:
                if on_payload_invalid is not None:
                    on_payload_invalid(source_type, metric, signal_id)
                continue
            signals.append(payload)
    return signals


def _summarize_focus_usage(
    records: list[FilingTextRecord],
    *,
    record_used_focus_fn: Callable[[FilingTextRecord], bool],
) -> dict[str, object]:
    focused_form_counter: Counter[str] = Counter()
    fallback_form_counter: Counter[str] = Counter()
    for record in records:
        if record_used_focus_fn(record):
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


def _build_pipeline_diagnostics_fields(
    pipeline_diag: _TextPipelineDiagnostics,
    *,
    debug_retrieval_preview_enabled: bool,
) -> dict[str, object]:
    forward_sentence_ratio = (
        pipeline_diag.forward_sentences_total / pipeline_diag.analysis_sentences_total
        if pipeline_diag.analysis_sentences_total > 0
        else 0.0
    )
    avg_retrieved_sentences_per_query = (
        pipeline_diag.metric_retrieved_sentences_total
        / pipeline_diag.metric_queries_total
        if pipeline_diag.metric_queries_total > 0
        else 0.0
    )
    fast_skip_ratio = (
        pipeline_diag.fls_fast_skip_records_total / pipeline_diag.records_processed
        if pipeline_diag.records_processed > 0
        else 0.0
    )
    return {
        "pipeline_records_processed": pipeline_diag.records_processed,
        "pipeline_records_with_signal_candidates": (
            pipeline_diag.records_with_signal_candidates
        ),
        "pipeline_analysis_sentences_total": pipeline_diag.analysis_sentences_total,
        "pipeline_forward_sentences_total": pipeline_diag.forward_sentences_total,
        "pipeline_retrieval_corpus_sentences_total": (
            pipeline_diag.retrieval_corpus_sentences_total
        ),
        "pipeline_forward_sentence_ratio": round(forward_sentence_ratio, 4),
        "pipeline_metric_queries_total": pipeline_diag.metric_queries_total,
        "pipeline_metric_retrieved_sentences_total": (
            pipeline_diag.metric_retrieved_sentences_total
        ),
        "pipeline_8k_sections_selected_total": (
            pipeline_diag.eight_k_sections_selected_total
        ),
        "pipeline_8k_noise_paragraphs_skipped_total": (
            pipeline_diag.eight_k_noise_sentences_skipped_total
        ),
        "pipeline_avg_retrieved_sentences_per_query": round(
            avg_retrieved_sentences_per_query, 4
        ),
        "pipeline_lexical_hits_total": pipeline_diag.lexical_hits_total,
        "pipeline_pattern_regex_hits_total": pipeline_diag.lexical_hits_total,
        "pipeline_pattern_lemma_hits_total": pipeline_diag.lemma_hits_total,
        "pipeline_pattern_dependency_hits_total": pipeline_diag.dependency_hits_total,
        "pipeline_numeric_hits_total": pipeline_diag.numeric_hits_total,
        "pipeline_retrieval_sentences_by_metric": dict(
            pipeline_diag.retrieval_sentences_by_metric
        ),
        "pipeline_lexical_hits_by_metric": dict(pipeline_diag.lexical_hits_by_metric),
        "pipeline_pattern_regex_hits_by_metric": dict(
            pipeline_diag.lexical_hits_by_metric
        ),
        "pipeline_pattern_lemma_hits_by_metric": dict(
            pipeline_diag.lemma_hits_by_metric
        ),
        "pipeline_pattern_dependency_hits_by_metric": dict(
            pipeline_diag.dependency_hits_by_metric
        ),
        "pipeline_numeric_hits_by_metric": dict(pipeline_diag.numeric_hits_by_metric),
        "pipeline_split_ms_total": round(pipeline_diag.split_ms_total, 3),
        "pipeline_fls_ms_total": round(pipeline_diag.fls_ms_total, 3),
        "pipeline_fls_model_load_ms_total": round(
            pipeline_diag.fls_model_load_ms_total, 3
        ),
        "pipeline_fls_inference_ms_total": round(
            pipeline_diag.fls_inference_ms_total, 3
        ),
        "pipeline_fls_sentences_scored_total": (
            pipeline_diag.fls_sentences_scored_total
        ),
        "pipeline_fls_prefilter_selected_total": (
            pipeline_diag.fls_prefilter_selected_total
        ),
        "pipeline_fls_batches_total": pipeline_diag.fls_batches_total,
        "pipeline_fls_cache_hits_total": pipeline_diag.fls_cache_hits_total,
        "pipeline_fls_cache_misses_total": pipeline_diag.fls_cache_misses_total,
        "pipeline_fls_fast_skip_records_total": pipeline_diag.fls_fast_skip_records_total,
        "pipeline_fls_fast_skip_sentences_total": (
            pipeline_diag.fls_fast_skip_sentences_total
        ),
        "pipeline_fls_fast_skip_ratio": round(fast_skip_ratio, 4),
        "pipeline_retrieval_ms_total": round(pipeline_diag.retrieval_ms_total, 3),
        "pipeline_pattern_ms_total": round(pipeline_diag.pattern_ms_total, 3),
        **(
            {
                "pipeline_metric_retrieval_preview_by_metric": (
                    pipeline_diag.retrieval_preview_by_metric
                )
            }
            if debug_retrieval_preview_enabled
            and bool(pipeline_diag.retrieval_preview_by_metric)
            else {}
        ),
    }
