from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Generic, TypeVar

from .extractor import SearchConfig, SECExtractResult, SECReportExtractor

T = TypeVar("T")


@dataclass(frozen=True)
class RankedResult:
    result: SECExtractResult
    result_index: int
    period_rank: date
    statement_match: bool
    dimension_preference: int


@dataclass(frozen=True)
class ParsedCandidate(Generic[T]):
    config_index: int
    ranked: RankedResult
    value: T


def rank_results(
    results: list[SECExtractResult], config: SearchConfig
) -> list[RankedResult]:
    ranked: list[RankedResult] = []
    statement_tokens = [t for t in (config.statement_types or []) if t]

    for idx, result in enumerate(results):
        period_rank = SECReportExtractor._period_sort_key(result.period_key)
        statement_match = (
            True
            if not statement_tokens
            else SECReportExtractor._statement_matches(
                result.statement, statement_tokens
            )
        )
        dim_count = len(result.dimension_detail or {})
        if config.type_name == "CONSOLIDATED":
            dimension_preference = 1 if dim_count == 0 else 0
        elif config.type_name == "DIMENSIONAL":
            # For dimensional queries prefer richer dimensional context.
            dimension_preference = dim_count
        else:
            dimension_preference = 0

        ranked.append(
            RankedResult(
                result=result,
                result_index=idx,
                period_rank=period_rank,
                statement_match=statement_match,
                dimension_preference=dimension_preference,
            )
        )

    ranked.sort(
        key=lambda item: (
            item.statement_match,
            item.dimension_preference,
            item.period_rank,
            -item.result_index,
            item.result.concept,
        ),
        reverse=True,
    )
    return ranked


def choose_best_candidate(
    candidates: list[ParsedCandidate[T]],
) -> ParsedCandidate[T] | None:
    if not candidates:
        return None

    return max(
        candidates,
        key=lambda item: (
            -item.config_index,
            item.ranked.statement_match,
            item.ranked.dimension_preference,
            item.ranked.period_rank,
            -item.ranked.result_index,
            item.ranked.result.concept,
        ),
    )
