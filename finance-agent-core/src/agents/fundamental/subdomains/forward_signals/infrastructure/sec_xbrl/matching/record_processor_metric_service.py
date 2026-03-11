from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ..postprocess.pipeline_runner import _MetricSignalAccumulator
from .rules.signal_pattern_catalog import MetricPatternSet


class PatternHit(Protocol):
    start: int
    end: int
    weighted_score: float
    is_forward: bool
    is_historical: bool
    rule: str


class NumericGuidanceHit(Protocol):
    start: int
    end: int
    direction: str
    score: float
    value_basis_points: float


class MetricRegexHits(Protocol):
    up_hits: list[PatternHit]
    down_hits: list[PatternHit]
    numeric_hits: list[NumericGuidanceHit]


class ExtractMetricRegexHitsFn(Protocol):
    def __call__(
        self,
        *,
        analysis_text: str,
        metric_text: str,
        metric: str,
        patterns: MetricPatternSet,
    ) -> MetricRegexHits: ...


class FindMetricLemmaHitsFn(Protocol):
    def __call__(
        self,
        *,
        text: str,
        metric: str,
    ) -> tuple[list[PatternHit], list[PatternHit]]: ...


class FindMetricDependencyHitsFn(Protocol):
    def __call__(
        self,
        *,
        text: str,
        metric: str,
    ) -> tuple[list[PatternHit], list[PatternHit]]: ...


@dataclass(frozen=True)
class MetricEvidenceContext:
    source_url: str
    doc_type: str
    period: str
    filing_date: str | None
    accession_number: str | None
    focus_strategy: str | None


@dataclass(frozen=True)
class MetricProcessingDiagnostics:
    retrieved_sentences_count: int
    lexical_hit_count: int
    lemma_hit_count: int
    dependency_hit_count: int
    numeric_hit_count: int


@dataclass(frozen=True)
class MetricProcessingResult:
    accumulator: _MetricSignalAccumulator | None
    diagnostics: MetricProcessingDiagnostics
    has_signal_candidates: bool


def process_metric_signal_for_record(
    *,
    metric: str,
    patterns: MetricPatternSet,
    metric_sentences: list[str],
    analysis_text: str,
    existing: _MetricSignalAccumulator | None,
    source_weight: float,
    filing_age_days: int | None,
    evidence_context: MetricEvidenceContext,
    join_sentences_fn: Callable[[list[str]], str],
    extract_metric_regex_hits_fn: ExtractMetricRegexHitsFn,
    find_metric_lemma_hits_fn: FindMetricLemmaHitsFn,
    find_metric_dependency_hits_fn: FindMetricDependencyHitsFn,
    extract_snippet_fn: Callable[[str, int, int, int], str | None],
    build_evidence_preview_fn: Callable[[str], str],
    append_unique_evidence_fn: Callable[
        [list[dict[str, object]], dict[str, object]], None
    ],
) -> MetricProcessingResult:
    metric_text = join_sentences_fn(metric_sentences) or analysis_text

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

    lexical_hit_count = len(regex_hits.up_hits) + len(regex_hits.down_hits)
    lemma_hit_count = len(lemma_up_hits) + len(lemma_down_hits)
    dependency_hit_count = len(dependency_up_hits) + len(dependency_down_hits)
    numeric_hit_count = len(numeric_hits)

    diagnostics = MetricProcessingDiagnostics(
        retrieved_sentences_count=len(metric_sentences),
        lexical_hit_count=lexical_hit_count,
        lemma_hit_count=lemma_hit_count,
        dependency_hit_count=dependency_hit_count,
        numeric_hit_count=numeric_hit_count,
    )

    if not up_hits and not down_hits and not numeric_hits:
        return MetricProcessingResult(
            accumulator=existing,
            diagnostics=diagnostics,
            has_signal_candidates=False,
        )

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

    up_score = existing.up_score + (
        sum(hit.weighted_score for hit in up_hits) * source_weight
    )
    down_score = existing.down_score + (
        sum(hit.weighted_score for hit in down_hits) * source_weight
    )
    evidence = list(existing.evidence)
    forward_hit_count = existing.forward_hit_count
    historical_hit_count = existing.historical_hit_count
    numeric_hit_total = existing.numeric_hit_count
    numeric_basis_points_samples = list(existing.numeric_basis_points_samples)
    filing_age_days_samples = list(existing.filing_age_days_samples)

    if filing_age_days is not None:
        filing_age_days_samples.append(filing_age_days)

    for hit in up_hits + down_hits:
        if hit.is_forward:
            forward_hit_count += 1
        if hit.is_historical:
            historical_hit_count += 1

        snippet = extract_snippet_fn(metric_text, hit.start, hit.end, 70)
        if not snippet:
            continue

        preview_text = build_evidence_preview_fn(snippet)
        append_unique_evidence_fn(
            evidence,
            {
                "preview_text": preview_text,
                "full_text": snippet,
                "source_url": evidence_context.source_url,
                "doc_type": evidence_context.doc_type,
                "period": evidence_context.period,
                "filing_date": evidence_context.filing_date,
                "accession_number": evidence_context.accession_number,
                "focus_strategy": evidence_context.focus_strategy,
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
            numeric_hit_total += 1
            numeric_basis_points_samples.append(numeric_hit.value_basis_points)
            if numeric_hit.direction == "up":
                up_score += numeric_hit.score * source_weight
            else:
                down_score += numeric_hit.score * source_weight

            snippet = extract_snippet_fn(
                metric_text, numeric_hit.start, numeric_hit.end, 70
            )
            if not snippet:
                continue

            preview_text = build_evidence_preview_fn(snippet)
            append_unique_evidence_fn(
                evidence,
                {
                    "preview_text": preview_text,
                    "full_text": snippet,
                    "source_url": evidence_context.source_url,
                    "doc_type": evidence_context.doc_type,
                    "period": evidence_context.period,
                    "filing_date": evidence_context.filing_date,
                    "accession_number": evidence_context.accession_number,
                    "focus_strategy": evidence_context.focus_strategy,
                    "rule": "numeric_guidance",
                    "value_basis_points": round(numeric_hit.value_basis_points, 2),
                    "source_locator": {
                        "text_scope": "metric_text",
                        "char_start": numeric_hit.start,
                        "char_end": numeric_hit.end,
                    },
                },
            )
            if len(evidence) >= 5:
                break

    updated = _MetricSignalAccumulator(
        up_score=up_score,
        down_score=down_score,
        evidence=evidence,
        forward_hit_count=forward_hit_count,
        historical_hit_count=historical_hit_count,
        numeric_hit_count=numeric_hit_total,
        numeric_basis_points_samples=numeric_basis_points_samples,
        filing_age_days_samples=filing_age_days_samples,
    )
    return MetricProcessingResult(
        accumulator=updated,
        diagnostics=diagnostics,
        has_signal_candidates=True,
    )
