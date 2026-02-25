from __future__ import annotations

import logging
import os
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from statistics import median

from edgar import Company
from pydantic import ValidationError

from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject

from .dependency_signal_matcher import find_metric_dependency_hits
from .filing_fetcher import call_with_sec_retry
from .filing_section_selector import is_8k_form, refine_8k_analysis_text
from .fls_filter import filter_forward_looking_sentences_with_stats
from .hybrid_retriever import retrieve_relevant_sentences_batch
from .lemma_signal_matcher import find_metric_lemma_hits
from .regex_signal_extractor import (
    contains_numeric_guidance_cue,
    extract_metric_regex_hits,
    has_forward_tense_cue,
)
from .sentence_pipeline import join_sentences, split_text_into_sentences
from .signal_pattern_catalog import (
    FORWARD_SIGNAL_PATTERN_CATALOG,
    METRIC_RETRIEVAL_QUERY,
    build_fls_skip_signal_phrases,
)
from .signal_schema import ForwardSignalEvidencePayload, ForwardSignalPayload

logger = get_logger(__name__)

_SEC_SEARCH_URL_TEMPLATE = "https://www.sec.gov/edgar/search/#/entityName={ticker}"
_SEC_ARCHIVES_INDEX_URL_TEMPLATE = (
    "https://www.sec.gov/Archives/edgar/data/"
    "{cik}/{accession_no_dash}/{accession}-index.html"
)
_TEXT_MAX_CHARS = 120_000

_FORM_SOURCE_TYPE: dict[str, str] = {
    "10-K": "mda",
    "10-Q": "mda",
    "8-K": "press_release",
}

_SOURCE_WEIGHT: dict[str, float] = {"mda": 1.0, "press_release": 0.75}
_SIGNAL_MIN_SCORE = 1.0
_SIGNAL_STALE_WARNING_DAYS = 540
_SIGNAL_STALE_HIGH_RISK_DAYS = 900
_FLS_SKIP_SIGNAL_PHRASES: tuple[str, ...] = tuple(
    build_fls_skip_signal_phrases(FORWARD_SIGNAL_PATTERN_CATALOG)
)


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

    grouped, pipeline_diag = _group_records_for_signals(ticker=ticker, records=records)
    focus_diag = _summarize_focus_usage(records)
    signals: list[dict[str, object]] = []
    for source_type, metrics in grouped.items():
        for metric, acc in metrics.items():
            score = acc.up_score - acc.down_score
            if abs(score) < _SIGNAL_MIN_SCORE:
                continue
            direction = "up" if score > 0 else "down"
            lexical_value_basis_points = abs(score) * 35.0
            numeric_anchor_basis_points = (
                median(acc.numeric_basis_points_samples)
                if acc.numeric_basis_points_samples
                else 0.0
            )
            value_basis_points = _clamp(
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
            staleness_penalty = _staleness_confidence_penalty(median_filing_age_days)
            confidence = _clamp(
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
            payload = _build_forward_signal_payload(
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
                continue
            signals.append(payload)

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
                **_build_pipeline_diagnostics_fields(pipeline_diag),
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
                **_build_pipeline_diagnostics_fields(pipeline_diag),
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


def _fetch_recent_filing_text_records(
    ticker: str,
    max_filings_per_form: int,
) -> list[FilingTextRecord]:
    company = call_with_sec_retry(
        operation="company_init",
        ticker=ticker,
        execute=lambda: Company(ticker),
    )
    company_cik = _normalize_cik(getattr(company, "cik", None))
    current_year = date.today().year
    years = [current_year - offset for offset in range(3)]

    records: list[FilingTextRecord] = []
    for form, source_type in _FORM_SOURCE_TYPE.items():
        current_form = form
        try:
            filings = call_with_sec_retry(
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
            subset = filings.head(max_filings_per_form)
        except Exception as exc:
            log_event(
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
            filing = _safe_get_filing(subset, idx)
            if filing is None:
                break
            text = _safe_get_filing_text(filing)
            if not text:
                continue
            focus_text, focus_strategy = _extract_focus_text_with_strategy_from_filing(
                form=form, filing=filing
            )
            if focus_text is None:
                focus_text = _extract_focus_text(form=form, text=text)
                if focus_text is not None:
                    focus_strategy = "regex_marker"
            records.append(
                FilingTextRecord(
                    form=form,
                    source_type=source_type,
                    text=text,
                    focus_text=focus_text,
                    period=_normalize_text(getattr(filing, "period_of_report", None)),
                    accession_number=_normalize_text(
                        getattr(filing, "accession_number", None)
                    ),
                    filing_date=_normalize_text(getattr(filing, "filing_date", None)),
                    cik=_normalize_cik(getattr(filing, "cik", None)) or company_cik,
                    focus_strategy=focus_strategy,
                )
            )
    return records


def _group_records_for_signals(
    *,
    ticker: str,
    records: list[FilingTextRecord],
) -> tuple[dict[str, dict[str, _MetricSignalAccumulator]], _TextPipelineDiagnostics]:
    grouped: dict[str, dict[str, _MetricSignalAccumulator]] = {}
    pipeline_diag = _TextPipelineDiagnostics()
    for record in records:
        pipeline_diag.records_processed += 1
        focused_section = record.focus_text or _extract_focus_text(
            form=record.form, text=record.text
        )
        analysis_text = focused_section or record.text
        if is_8k_form(record.form):
            refined_8k = refine_8k_analysis_text(analysis_text)
            analysis_text = refined_8k.text or analysis_text
            pipeline_diag.eight_k_sections_selected_total += (
                refined_8k.sections_selected
            )
            pipeline_diag.eight_k_noise_sentences_skipped_total += (
                refined_8k.noise_sentences_skipped
            )
        split_started = time.perf_counter()
        analysis_sentences = split_text_into_sentences(analysis_text)
        pipeline_diag.split_ms_total += (time.perf_counter() - split_started) * 1000.0
        fls_stats: dict[str, float | int] = {}
        if _should_fast_skip_fls(analysis_sentences):
            forward_sentences = []
            pipeline_diag.fls_fast_skip_records_total += 1
            pipeline_diag.fls_fast_skip_sentences_total += len(analysis_sentences)
        else:
            fls_started = time.perf_counter()
            forward_sentences, fls_stats = filter_forward_looking_sentences_with_stats(
                analysis_sentences
            )
            pipeline_diag.fls_ms_total += (time.perf_counter() - fls_started) * 1000.0
            pipeline_diag.fls_model_load_ms_total += _as_float(
                fls_stats.get("model_load_ms")
            )
            pipeline_diag.fls_inference_ms_total += _as_float(
                fls_stats.get("inference_ms")
            )
            pipeline_diag.fls_sentences_scored_total += _as_int(
                fls_stats.get("sentences_scored")
            )
            pipeline_diag.fls_prefilter_selected_total += _as_int(
                fls_stats.get("prefilter_selected")
            )
            pipeline_diag.fls_batches_total += _as_int(fls_stats.get("batches"))
            pipeline_diag.fls_cache_hits_total += _as_int(fls_stats.get("cache_hits"))
            pipeline_diag.fls_cache_misses_total += _as_int(
                fls_stats.get("cache_misses")
            )
        retrieval_corpus = (
            forward_sentences if forward_sentences else analysis_sentences
        )
        pipeline_diag.analysis_sentences_total += len(analysis_sentences)
        pipeline_diag.forward_sentences_total += len(forward_sentences)
        pipeline_diag.retrieval_corpus_sentences_total += len(retrieval_corpus)
        doc_type = _build_doc_type(record.form, used_focus=focused_section is not None)
        source_url = _build_sec_source_url(
            ticker=ticker,
            accession_number=record.accession_number,
            cik=record.cik,
        )
        metric_order = list(FORWARD_SIGNAL_PATTERN_CATALOG.keys())
        metric_queries = [
            METRIC_RETRIEVAL_QUERY.get(metric, metric.replace("_", " "))
            for metric in metric_order
        ]
        pipeline_diag.metric_queries_total += len(metric_order)
        retrieval_started = time.perf_counter()
        metric_retrieval_results = retrieve_relevant_sentences_batch(
            queries=metric_queries,
            corpus=retrieval_corpus,
            top_k=24,
        )
        pipeline_diag.retrieval_ms_total += (
            time.perf_counter() - retrieval_started
        ) * 1000.0
        record_has_signal_candidates = False
        for idx, metric in enumerate(metric_order):
            patterns = FORWARD_SIGNAL_PATTERN_CATALOG[metric]
            metric_sentences = (
                metric_retrieval_results[idx]
                if idx < len(metric_retrieval_results)
                else []
            )
            if (
                _DEBUG_RETRIEVAL_PREVIEW_ENABLED
                and _DEBUG_RETRIEVAL_PREVIEW_LIMIT > 0
                and metric not in pipeline_diag.retrieval_preview_by_metric
                and metric_sentences
            ):
                previews = [
                    _preview_sentence(sentence)
                    for sentence in metric_sentences[:_DEBUG_RETRIEVAL_PREVIEW_LIMIT]
                ]
                pipeline_diag.retrieval_preview_by_metric[metric] = [
                    item for item in previews if item
                ]
            pipeline_diag.metric_retrieved_sentences_total += len(metric_sentences)
            pipeline_diag.retrieval_sentences_by_metric[metric] += len(metric_sentences)
            metric_text = join_sentences(metric_sentences) or analysis_text
            pattern_started = time.perf_counter()
            regex_hits = extract_metric_regex_hits(
                analysis_text=metric_text,
                metric=metric,
                metric_text=metric_text,
                patterns=patterns,
            )
            lemma_up_hits, lemma_down_hits = find_metric_lemma_hits(
                text=metric_text,
                metric=metric,
            )
            dependency_up_hits, dependency_down_hits = find_metric_dependency_hits(
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

            weight = _SOURCE_WEIGHT.get(record.source_type, 1.0)
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
            filing_age_days = _filing_age_days(record.filing_date)
            if filing_age_days is not None:
                filing_age_days_samples.append(filing_age_days)

            for hit in up_hits + down_hits:
                if hit.is_forward:
                    forward_hit_count += 1
                if hit.is_historical:
                    historical_hit_count += 1
                snippet = _extract_snippet(metric_text, hit.start, hit.end)
                if not snippet:
                    continue
                _append_unique_evidence(
                    evidence,
                    {
                        "text_snippet": snippet,
                        "source_url": source_url,
                        "doc_type": doc_type,
                        "period": record.period or "N/A",
                        "filing_date": record.filing_date,
                        "accession_number": record.accession_number,
                        "focus_strategy": record.focus_strategy,
                        "rule": hit.rule,
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
                    snippet = _extract_snippet(
                        metric_text, numeric_hit.start, numeric_hit.end
                    )
                    if not snippet:
                        continue
                    _append_unique_evidence(
                        evidence,
                        {
                            "text_snippet": snippet,
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


def _build_pipeline_diagnostics_fields(
    pipeline_diag: _TextPipelineDiagnostics,
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
            if _DEBUG_RETRIEVAL_PREVIEW_ENABLED
            and bool(pipeline_diag.retrieval_preview_by_metric)
            else {}
        ),
    }


def _as_float(value: object) -> float:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _record_used_focus(record: FilingTextRecord) -> bool:
    if isinstance(record.focus_text, str) and record.focus_text:
        return True
    inferred_focus = _extract_focus_text(form=record.form, text=record.text)
    return isinstance(inferred_focus, str) and bool(inferred_focus)


def _should_fast_skip_fls(analysis_sentences: list[str]) -> bool:
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
        if any(phrase in lowered for phrase in _FLS_SKIP_SIGNAL_PHRASES):
            return False
    return True


def _extract_snippet(text: str, start: int, end: int, radius: int = 70) -> str | None:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = " ".join(text[left:right].split())
    if not snippet:
        return None
    if len(snippet) > 220:
        return snippet[:217] + "..."
    return snippet


def _append_unique_evidence(
    evidence: list[dict[str, object]],
    candidate: dict[str, object],
) -> None:
    snippet_raw = candidate.get("text_snippet")
    if not isinstance(snippet_raw, str) or not snippet_raw:
        return
    if _has_duplicate_evidence(evidence, candidate):
        return
    evidence.append(candidate)


def _has_duplicate_evidence(
    evidence: list[dict[str, object]],
    candidate: dict[str, object],
) -> bool:
    candidate_scope = _evidence_scope(candidate)
    candidate_norm = _normalize_evidence_snippet(candidate.get("text_snippet"))
    if not candidate_norm:
        return False
    for existing in evidence:
        if _evidence_scope(existing) != candidate_scope:
            continue
        existing_norm = _normalize_evidence_snippet(existing.get("text_snippet"))
        if not existing_norm:
            continue
        if candidate_norm == existing_norm:
            return True
        if (
            len(candidate_norm) >= 80
            and len(existing_norm) >= 80
            and (candidate_norm in existing_norm or existing_norm in candidate_norm)
        ):
            return True
    return False


def _evidence_scope(
    candidate: dict[str, object],
) -> tuple[str | None, str | None, str | None]:
    accession_raw = candidate.get("accession_number")
    accession = (
        accession_raw if isinstance(accession_raw, str) and accession_raw else None
    )
    source_url_raw = candidate.get("source_url")
    source_url = (
        source_url_raw if isinstance(source_url_raw, str) and source_url_raw else None
    )
    doc_type_raw = candidate.get("doc_type")
    doc_type = doc_type_raw if isinstance(doc_type_raw, str) and doc_type_raw else None
    return accession, source_url, doc_type


def _normalize_evidence_snippet(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    lowered = value.lower()
    lowered = re.sub(r"\s+", " ", lowered)
    normalized = re.sub(r"[^a-z0-9]+", " ", lowered).strip()
    return normalized or None


def _preview_sentence(sentence: str) -> str | None:
    normalized = " ".join(sentence.split())
    if not normalized:
        return None
    if len(normalized) <= _DEBUG_RETRIEVAL_PREVIEW_CHARS:
        return normalized
    return normalized[: _DEBUG_RETRIEVAL_PREVIEW_CHARS - 3] + "..."


def _extract_focus_text_with_strategy_from_filing(
    *, form: str, filing: object
) -> tuple[str | None, str | None]:
    filing_obj = _safe_get_filing_obj(filing)
    if filing_obj is None:
        return None, None
    normalized_form = form.strip().upper()
    if normalized_form == "10-K":
        return _extract_10k_focus_from_obj_with_strategy(filing_obj)
    if normalized_form == "10-Q":
        return _extract_10q_focus_from_obj_with_strategy(filing_obj)
    if normalized_form == "8-K":
        return _extract_8k_focus_from_obj_with_strategy(filing_obj)
    return None, None


def _extract_focus_text_from_filing(*, form: str, filing: object) -> str | None:
    focus_text, _focus_strategy = _extract_focus_text_with_strategy_from_filing(
        form=form, filing=filing
    )
    return focus_text


def _safe_get_filing_obj(filing: object) -> object | None:
    try:
        obj_fn = getattr(filing, "obj", None)
        if callable(obj_fn):
            return obj_fn()
    except Exception:
        return None
    return None


def _extract_10k_focus_from_obj_with_strategy(
    filing_obj: object,
) -> tuple[str | None, str | None]:
    candidates = [
        (
            _safe_call_get_item_with_part(filing_obj, "Part II", "Item 7"),
            "edgartools_part_item",
        ),
        (_safe_call_get_item(filing_obj, "Item 7"), "edgartools_item_lookup"),
        (_safe_call_get_item(filing_obj, "7"), "edgartools_item_lookup"),
        (
            _safe_call_get_item_from_sections(
                filing_obj,
                keys=("part_ii_item_7", "item_7"),
            ),
            "edgartools_sections_lookup",
        ),
    ]
    return _pick_valid_focus_text_with_strategy(candidates, min_len=120)


def _extract_10q_focus_from_obj_with_strategy(
    filing_obj: object,
) -> tuple[str | None, str | None]:
    candidates = [
        (
            _safe_call_get_item_with_part(filing_obj, "Part I", "Item 2"),
            "edgartools_part_item",
        ),
        (_safe_call_get_item(filing_obj, "Item 2"), "edgartools_item_lookup"),
        (_safe_call_get_item(filing_obj, "2"), "edgartools_item_lookup"),
        (
            _safe_call_get_item_from_sections(
                filing_obj,
                keys=("part_i_item_2", "item_2"),
            ),
            "edgartools_sections_lookup",
        ),
    ]
    return _pick_valid_focus_text_with_strategy(candidates, min_len=100)


def _extract_8k_focus_from_obj_with_strategy(
    filing_obj: object,
) -> tuple[str | None, str | None]:
    candidates = [
        (_safe_call_get_item(filing_obj, "Item 2.02"), "edgartools_item_lookup"),
        (_safe_call_get_item(filing_obj, "2.02"), "edgartools_item_lookup"),
        (_safe_call_get_item(filing_obj, "Item 8.01"), "edgartools_item_lookup"),
        (_safe_call_get_item(filing_obj, "8.01"), "edgartools_item_lookup"),
        (_safe_call_get_item(filing_obj, "Item 7.01"), "edgartools_item_lookup"),
        (_safe_call_get_item(filing_obj, "7.01"), "edgartools_item_lookup"),
        (
            _safe_call_get_item_from_sections(
                filing_obj,
                keys=("item_202", "item_801", "item_701"),
            ),
            "edgartools_sections_lookup",
        ),
        (_safe_call_exhibit_99_text(filing_obj), "edgartools_exhibit_99"),
        (_safe_call_press_release_text(filing_obj), "edgartools_press_release"),
    ]
    return _pick_valid_focus_text_with_strategy(candidates, min_len=120)


def _safe_call_get_item_with_part(
    filing_obj: object,
    part: str,
    item: str,
) -> str | None:
    try:
        method = getattr(filing_obj, "get_item_with_part", None)
        if callable(method):
            return _normalize_text(method(part, item))
    except Exception:
        return None
    return None


def _safe_call_get_item(filing_obj: object, key: str) -> str | None:
    try:
        getter = getattr(filing_obj, "__getitem__", None)
        if callable(getter):
            return _normalize_text(getter(key))
    except Exception:
        return None
    return None


def _safe_call_get_item_from_sections(
    filing_obj: object,
    *,
    keys: tuple[str, ...],
) -> str | None:
    try:
        sections = getattr(filing_obj, "sections", None)
        if not isinstance(sections, dict):
            return None
        texts: list[str] = []
        for key in keys:
            section = sections.get(key)
            if section is None:
                continue
            text_fn = getattr(section, "text", None)
            if not callable(text_fn):
                continue
            section_text = _normalize_text(text_fn())
            if section_text:
                texts.append(section_text)
        if not texts:
            return None
        return _normalize_text(" ".join(texts))
    except Exception:
        return None


def _safe_call_press_release_text(filing_obj: object) -> str | None:
    try:
        press_releases = getattr(filing_obj, "press_releases", None)
        if press_releases is None:
            return None
        getter = getattr(press_releases, "__getitem__", None)
        if callable(getter):
            first_release = getter(0)
        else:
            first_release = None
        if first_release is None:
            return None
        text_attr = getattr(first_release, "text", None)
        if isinstance(text_attr, str):
            return _normalize_text(text_attr)
        text_fn = getattr(first_release, "text", None)
        if callable(text_fn):
            return _normalize_text(text_fn())
    except Exception:
        return None
    return None


def _safe_call_exhibit_99_text(filing_obj: object) -> str | None:
    try:
        sections = getattr(filing_obj, "sections", None)
        if isinstance(sections, dict):
            for key, section in sections.items():
                key_text = str(key).lower()
                if "99" not in key_text:
                    continue
                if "exhibit" not in key_text and "ex99" not in key_text:
                    continue
                text_fn = getattr(section, "text", None)
                if callable(text_fn):
                    section_text = _normalize_text(text_fn())
                    if section_text:
                        return section_text
        exhibits = getattr(filing_obj, "exhibits", None)
        if isinstance(exhibits, dict):
            for key, exhibit in exhibits.items():
                key_text = str(key).lower()
                if not key_text.startswith("99"):
                    continue
                text_attr = getattr(exhibit, "text", None)
                if isinstance(text_attr, str):
                    normalized = _normalize_text(text_attr)
                    if normalized:
                        return normalized
                text_fn = getattr(exhibit, "text", None)
                if callable(text_fn):
                    normalized_fn_text = _normalize_text(text_fn())
                    if normalized_fn_text:
                        return normalized_fn_text
    except Exception:
        return None
    return None


def _pick_valid_focus_text_with_strategy(
    candidates: list[tuple[str | None, str]],
    *,
    min_len: int,
) -> tuple[str | None, str | None]:
    for candidate, strategy in candidates:
        normalized = _normalize_text(candidate)
        if normalized and len(normalized) >= min_len:
            return normalized[:_TEXT_MAX_CHARS], strategy
    return None, None


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
            start_patterns=(
                r"item\s+2\.02",
                r"item\s+8\.01",
                r"item\s+7\.01",
                r"exhibit\s+99(?:\.\d+)?",
            ),
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
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized if normalized else None


def _normalize_accession_number(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    accession_match = re.search(r"(\d{10}-\d{2}-\d{6})", stripped)
    if accession_match is not None:
        return accession_match.group(1)
    digits = re.sub(r"\D", "", stripped)
    if len(digits) != 18:
        return None
    return f"{digits[:10]}-{digits[10:12]}-{digits[12:]}"


def _normalize_cik(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        if value < 0:
            return None
        return str(value)
    if isinstance(value, str):
        digits = re.sub(r"\D", "", value)
        if not digits:
            return None
        return digits
    return None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
